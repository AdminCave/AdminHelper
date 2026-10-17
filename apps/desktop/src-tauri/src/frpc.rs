// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::Deserialize;
use tauri::{Emitter, Manager};
use tauri_plugin_shell::ShellExt;

/// Writes data with restrictive permissions (0600 on Unix).
/// On Windows the default user ACLs of the AppData folder apply.
fn write_secret(path: &Path, content: &[u8]) -> std::io::Result<()> {
    #[cfg(unix)]
    {
        use std::io::Write;
        use std::os::unix::fs::OpenOptionsExt;
        let mut f = std::fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .mode(0o600)
            .open(path)?;
        f.write_all(content)
    }
    #[cfg(not(unix))]
    {
        std::fs::write(path, content)
    }
}

use crate::auth;
use crate::error::AppError;
use crate::models::{RefreshOutcome, TunnelRefresh, TunnelStatus};

pub type FrpcState = Arc<Mutex<FrpcProcess>>;

pub fn new_frpc_state() -> FrpcState {
    Arc::new(Mutex::new(FrpcProcess::new()))
}

/// Serializes the reconciliations: two at once would both compare against the same running
/// config and both start or reload.
#[derive(Default)]
pub struct RefreshLock(tauri::async_runtime::Mutex<()>);

pub struct FrpcProcess {
    child: Option<tauri_plugin_shell::process::CommandChild>,
    visitor_name: Option<String>,
    connected_since: Option<String>,
    // Bumped on every spawn and every stop so a log task's Terminated handler only reconciles
    // state if it is still the current process (4.29, R-0389).
    generation: u64,
    /// What the running frpc applied; `None` while none runs.
    applied: Option<Applied>,
}

/// The config a running frpc applied: the server TOML, parsed for the next comparison, and the
/// local head it runs with — a reload keeps the head, frp reads `webServer` only at start.
struct Applied {
    server: toml::Value,
    head: LocalHead,
}

/// The desktop's own part of frpc's config: the loopback port of frpc's admin API and its
/// password.
#[derive(Clone)]
struct LocalHead {
    port: u16,
    password: String,
}

impl LocalHead {
    /// A head for a new frpc: a free loopback port and a new password. Every start takes a new
    /// one, a restart after a failed reload included; no head outlives its process.
    fn fresh() -> Result<Self, AppError> {
        // frpc binds the port itself a moment later; if it is taken by then, frpc ends and the
        // next start picks another.
        let port = std::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, 0))?
            .local_addr()?
            .port();
        let mut secret = [0u8; 32];
        crate::tofu::ring_provider()
            .secure_random
            .fill(&mut secret)
            .map_err(|_| {
                AppError::Connection("no randomness for the frpc admin API password".to_string())
            })?;
        let password = secret.iter().map(|b| format!("{b:02x}")).collect();
        Ok(Self { port, password })
    }
}

impl FrpcProcess {
    pub fn new() -> Self {
        Self {
            child: None,
            visitor_name: None,
            connected_since: None,
            generation: 0,
            applied: None,
        }
    }

    /// Reconcile after a Terminated event: clear child/visitor so a later restart isn't blocked by a
    /// stale child ("frpc laeuft bereits") — but only if the event belongs to the CURRENT generation,
    /// so a late Terminated from a restarted-away process doesn't wipe the new child (4.29). A pure
    /// state transition, extracted so it is testable without a real sidecar (6.107).
    ///
    /// Returns whether the event belongs to the current generation, i.e. whether the UI should
    /// hear of it: a stale one would show the running tunnel as disconnected (R-0247).
    fn reconcile_terminated(&mut self, event_generation: u64) -> bool {
        if !self.is_current(event_generation) {
            return false;
        }
        self.child = None;
        self.visitor_name = None;
        self.connected_since = None;
        self.applied = None;
        true
    }

    /// Whether an event from the process spawned as `event_generation` belongs to the running
    /// process. Every event the UI hears of passes this check: a stale `frpc-error` from a
    /// stopped or restarted-away process would show the idle or running tunnel as disconnected
    /// (R-0390), just like a stale Terminated.
    fn is_current(&self, event_generation: u64) -> bool {
        self.generation == event_generation
    }

    /// Retire the current process for a stop: clear the state and bump the generation, so the
    /// stopped process's late Terminated counts as stale and does not reach the UI — it would
    /// turn the idle indicator into "disconnected" (R-0389). Returns the child for the caller to
    /// kill.
    fn retire(&mut self) -> Option<tauri_plugin_shell::process::CommandChild> {
        self.generation += 1;
        self.visitor_name = None;
        self.connected_since = None;
        self.applied = None;
        self.child.take()
    }

    /// Names of the visitors the running frpc applied.
    fn visitors(&self) -> Vec<String> {
        self.applied
            .as_ref()
            .map(|applied| visitor_names(&applied.server))
            .unwrap_or_default()
    }
}

/// The `name` of every visitor in a server TOML.
fn visitor_names(config: &toml::Value) -> Vec<String> {
    config
        .get("visitors")
        .and_then(|visitors| visitors.as_array())
        .into_iter()
        .flatten()
        .filter_map(|visitor| visitor.get("name")?.as_str().map(str::to_string))
        .collect()
}

#[derive(Deserialize)]
struct VisitorBundle {
    toml: String,
    // The server no longer ships PKI material (F2/F3: D6 — the server holds no
    // signing capability). The visitor presents the desktop's own enrolled
    // identity instead; any `pki` field the server still sends is ignored.
}

/// Fetch the visitor bundle from the server. TOML only — the server no longer
/// ships PKI (D6); the identity comes from enrollment. `None` means the user has
/// no tunnels (see [`carries_bundle`]).
async fn fetch_visitor_bundle(
    server_url: &str,
    token: &str,
    allow_self_signed: bool,
) -> Result<Option<VisitorBundle>, AppError> {
    let path = "/api/frp/generate/visitor-bundle";
    let response = auth::authenticated_get(server_url, token, path, allow_self_signed).await?;
    bundle_from(response).await
}

/// The bundle a visitor-bundle reply carries; `None` means no tunnels (see [`carries_bundle`]).
async fn bundle_from(response: reqwest::Response) -> Result<Option<VisitorBundle>, AppError> {
    if !carries_bundle(response.status())? {
        return Ok(None);
    }

    let bundle: VisitorBundle = response.json().await.map_err(AppError::Network)?;
    Ok(Some(bundle))
}

/// Whether a visitor-bundle reply with this status carries a bundle. 404 is no error but "no
/// tunnels": the server answers it both without an FRP config and when the user sees no usable
/// STCP tunnel (generate_router.py). Every other non-2xx — a 401 the refresh could not cure
/// included — is an error.
fn carries_bundle(status: reqwest::StatusCode) -> Result<bool, AppError> {
    if status == reqwest::StatusCode::NOT_FOUND {
        return Ok(false);
    }
    if !status.is_success() {
        return Err(AppError::Validation(
            "Visitor-Bundle konnte nicht geladen werden".to_string(),
        ));
    }
    Ok(true)
}

/// The placeholder the server's visitor generator emits in place of the identity
/// dir; `frpc_config` swaps it for the absolute on-disk path. Must stay
/// in lockstep with `_VISITOR_IDENTITY_DIR` in the server's config_generator.py —
/// an explicit token instead of a fragile `"identity/` substring rewrite.
const IDENTITY_DIR_PLACEHOLDER: &str = "{{IDENTITY_DIR}}";

/// What a tunnel start says without an enrolled identity. The login does not enroll
/// (ADR 0003): the device needs a one-time token from an admin first.
const NO_IDENTITY_HINT: &str = "No mTLS certificate on this device — enroll it with a one-time \
     enrollment token from your administrator first, then start the tunnel.";

/// Replace the server's `{{IDENTITY_DIR}}` placeholder in a visitor TOML with the
/// absolute identity dir the desktop exported its mTLS material into.
///
/// The server writes `_VISITOR_IDENTITY_DIR` only inside basic strings (`"…"`), so the dir goes
/// in escaped for one (TOML v1.0.0, String): unescaped, the backslashes of a Windows path start
/// escapes that are invalid (`\U` of `C:\Users`) or reserved (`\A` of `\AppData`). A literal
/// string (`'…'`) needs no escape but cannot hold the `'` a Windows user name may contain.
fn rewrite_identity_paths(toml: &str, abs_identity_dir: &str) -> String {
    let mut escaped = String::with_capacity(abs_identity_dir.len());
    for c in abs_identity_dir.chars() {
        match c {
            '\\' => escaped.push_str("\\\\"),
            '"' => escaped.push_str("\\\""),
            '\t' => escaped.push(c),
            c if c <= '\u{1f}' || c == '\u{7f}' => {
                escaped.push_str(&format!("\\u{:04X}", u32::from(c)));
            }
            c => escaped.push(c),
        }
    }
    toml.replace(IDENTITY_DIR_PLACEHOLDER, &escaped)
}

/// Export the enrolled identity (key 0600 + cert + CA) into `identity_dir` so the
/// frpc sidecar can read it as files. The visitor presents the desktop's own
/// access cert (F2); the server no longer mints one.
fn export_identity(identity_dir: &Path) -> Result<(), AppError> {
    let (key_pem, cert_pem, ca_pem) = crate::enrollment::load_identity()
        .ok_or_else(|| AppError::Validation(NO_IDENTITY_HINT.to_string()))?;
    std::fs::create_dir_all(identity_dir)?;
    write_secret(&identity_dir.join("key.pem"), key_pem.as_bytes())?;
    std::fs::write(identity_dir.join("cert.pem"), cert_pem.as_bytes())?;
    std::fs::write(identity_dir.join("ca.crt"), ca_pem.as_bytes())?;
    Ok(())
}

/// Allow-list the server-supplied visitor TOML before frpc executes it. Only the keys
/// our own server-side generate_visitor_toml emits are permitted, so a compromised or
/// malicious server cannot inject arbitrary frpc config — notably a `[[proxies]]` block
/// or a visitor plugin (static_file/http_proxy) that would expose local files/network
/// through the frpc process (3.59). Returns the parsed TOML.
///
/// Keep the key lists of [`validate_visitor_table`] in sync with the server's
/// `generate_visitor_toml` and `_tls_client_block`
/// (apps/server/app/modules/frp/config_generator.py): adding a server-side key without
/// listing it here would reject real tunnels. Under `auth` and `transport` too, only the keys
/// those two emit are allowed, `auth.method` only as `token`, and a visitor's `bindAddr` only as
/// `127.0.0.1`.
fn validate_visitor_toml(toml_str: &str) -> Result<toml::Value, AppError> {
    let value: toml::Value =
        toml::from_str(toml_str).map_err(|e| parse_error("visitor.toml", toml_str, &e))?;
    let table = value
        .as_table()
        .ok_or_else(|| AppError::Validation("visitor.toml: kein TOML-Table".to_string()))?;
    validate_visitor_table(table)?;
    Ok(value)
}

/// The allow-list of [`validate_visitor_toml`] over a parsed root table.
fn validate_visitor_table(table: &toml::Table) -> Result<(), AppError> {
    const TOP_KEYS: &[&str] = &[
        "serverAddr",
        "serverPort",
        "user",
        "auth",
        "transport",
        "visitors",
    ];
    const VISITOR_KEYS: &[&str] = &[
        "name",
        "type",
        "serverName",
        "serverUser",
        "secretKey",
        "bindAddr",
        "bindPort",
    ];
    const AUTH_KEYS: &[&str] = &["method", "token"];
    const TRANSPORT_KEYS: &[&str] = &["tls"];
    const TLS_KEYS: &[&str] = &["enable", "trustedCaFile", "certFile", "keyFile"];

    for key in table.keys() {
        if !TOP_KEYS.contains(&key.as_str()) {
            return Err(AppError::Validation(format!(
                "visitor.toml: unerlaubter Top-Level-Key '{key}'"
            )));
        }
    }

    if let Some(auth) = table.get("auth") {
        let auth = allowed_table(auth, "auth", AUTH_KEYS)?;
        if auth
            .get("method")
            .is_some_and(|method| method.as_str() != Some("token"))
        {
            return Err(AppError::Validation(
                "visitor.toml: auth.method must be \"token\"".to_string(),
            ));
        }
    }
    if let Some(transport) = table.get("transport") {
        let transport = allowed_table(transport, "transport", TRANSPORT_KEYS)?;
        if let Some(tls) = transport.get("tls") {
            allowed_table(tls, "transport.tls", TLS_KEYS)?;
        }
    }

    if let Some(visitors) = table.get("visitors") {
        let arr = visitors.as_array().ok_or_else(|| {
            AppError::Validation("visitor.toml: [[visitors]] ist kein Array".to_string())
        })?;
        for v in arr {
            let vt = v.as_table().ok_or_else(|| {
                AppError::Validation("visitor.toml: ein [[visitors]]-Eintrag ist kein Table".into())
            })?;
            if vt.get("type").and_then(|t| t.as_str()) != Some("stcp") {
                return Err(AppError::Validation(
                    "visitor.toml: nur type=\"stcp\"-Visitors erlaubt".to_string(),
                ));
            }
            for key in vt.keys() {
                if !VISITOR_KEYS.contains(&key.as_str()) {
                    return Err(AppError::Validation(format!(
                        "visitor.toml: unerlaubter Visitor-Key '{key}'"
                    )));
                }
            }
            if vt
                .get("bindAddr")
                .is_some_and(|addr| addr.as_str() != Some("127.0.0.1"))
            {
                return Err(AppError::Validation(
                    "visitor.toml: a visitor's bindAddr must be \"127.0.0.1\"".to_string(),
                ));
            }
        }
    }
    Ok(())
}

/// A TOML parse error of `text` that names only line and column (1-based, columns in characters),
/// not the parser's text: that quotes the line, and a line here can hold a token or a secretKey.
fn parse_error(what: &str, text: &str, error: &toml::de::Error) -> AppError {
    let position = error
        .span()
        .and_then(|span| text.get(..span.start))
        .map(|before| {
            let line_start = before.rfind('\n').map_or(0, |nl| nl + 1);
            format!(
                " (line {}, column {})",
                before.matches('\n').count() + 1,
                before[line_start..].chars().count() + 1
            )
        })
        .unwrap_or_default();
    AppError::Validation(format!("{what} does not parse{position}"))
}

/// `value` as a table that holds no key but `keys`; `name` is its path in the visitor TOML.
fn allowed_table<'a>(
    value: &'a toml::Value,
    name: &str,
    keys: &[&str],
) -> Result<&'a toml::Table, AppError> {
    let table = value
        .as_table()
        .ok_or_else(|| AppError::Validation(format!("visitor.toml: {name} is not a table")))?;
    match table.keys().find(|key| !keys.contains(&key.as_str())) {
        Some(key) => Err(AppError::Validation(format!(
            "visitor.toml: key '{name}.{key}' is not allowed"
        ))),
        None => Ok(table),
    }
}

/// User of frpc's local admin API; the generated password is the secret.
const ADMIN_API_USER: &str = "adminhelper";

/// How long frpc may take to answer a reload before the reconciliation restarts it instead.
const RELOAD_TIMEOUT: Duration = Duration::from_secs(5);

/// The config frpc runs: the allow-listed server TOML with the desktop's local head in its root,
/// as the text frpc reads. `loginFailExit = false` keeps frpc retrying while frps is unreachable
/// (frp's default ends it after the first failed login); `webServer.*` opens frpc's admin API on
/// loopback for the reload. The head goes in only after `validate_visitor_toml`, so the allow-list
/// stays as it is and still rejects a server that sends `webServer` or `loginFailExit` itself. The
/// password is never optional — without user and password frp serves the admin API,
/// `GET /api/config` with the frps token and every `secretKey` included, to every local process —
/// and it is the desktop's own hex; anything else is refused.
///
/// frpc gets exactly what was checked: the text is generated from the checked table, not taken
/// from the server, and every string in it stands on one line. toml writes a string with a line
/// break over several lines, so such a value is refused.
fn with_local_head(server_toml: &str, port: u16, password: &str) -> Result<String, AppError> {
    let server = validate_visitor_toml(server_toml)?;
    if password.is_empty() || !password.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(AppError::Validation(
            "frpc admin API password is not hex".to_string(),
        ));
    }
    single_line_strings(&server)?;
    let mut root = server.as_table().cloned().unwrap_or_default();
    root.insert("loginFailExit".to_string(), false.into());
    root.insert(
        "webServer".to_string(),
        toml::Value::Table(admin_api(port, password)),
    );
    toml::to_string(&root)
        .map_err(|e| AppError::Validation(format!("frpc config does not serialize: {e}")))
}

/// The `webServer` table of the local head: frpc's admin API on loopback.
fn admin_api(port: u16, password: &str) -> toml::Table {
    let mut web_server = toml::Table::new();
    web_server.insert("addr".to_string(), "127.0.0.1".into());
    web_server.insert("port".to_string(), i64::from(port).into());
    web_server.insert("user".to_string(), ADMIN_API_USER.into());
    web_server.insert("password".to_string(), password.into());
    web_server
}

/// Refuse a string with a line break anywhere in `value`.
fn single_line_strings(value: &toml::Value) -> Result<(), AppError> {
    match value {
        toml::Value::String(s) if s.contains('\n') => Err(AppError::Validation(
            "visitor.toml: a value holds a line break".to_string(),
        )),
        toml::Value::Array(items) => items.iter().try_for_each(single_line_strings),
        toml::Value::Table(table) => table.values().try_for_each(single_line_strings),
        _ => Ok(()),
    }
}

/// Refuse a text that holds `{{`.
fn no_template_delimiter(text: &str) -> Result<(), AppError> {
    if text.contains("{{") {
        return Err(AppError::Validation(
            "frpc config: '{{' is not allowed".to_string(),
        ));
    }
    Ok(())
}

/// The text frpc runs: the server TOML with `identity_dir` filled in and `head` in its root, as
/// [`with_local_head`] generates it. The identity dir goes in after the allow-list, so the
/// filled-in TOML is checked again, and so is the generated text: its root holds the head exactly
/// as set and otherwise only what the allow-list admits. frp renders the config file as a Go
/// template before it reads the TOML (`pkg/config/load.go`, `RenderWithTemplate`), so neither the
/// server TOML with the identity dir filled in nor the generated text holds `{{` — an escape in
/// the server TOML can spell it in a value.
fn frpc_config(
    server_toml: &str,
    identity_dir: &str,
    head: &LocalHead,
) -> Result<String, AppError> {
    let server_toml = rewrite_identity_paths(server_toml, identity_dir);
    no_template_delimiter(&server_toml)?;
    let config = with_local_head(&server_toml, head.port, &head.password)?;
    no_template_delimiter(&config)?;
    let parsed: toml::Value =
        toml::from_str(&config).map_err(|e| parse_error("frpc config", &config, &e))?;
    let mut root = parsed.as_table().cloned().unwrap_or_default();

    if root.remove("loginFailExit") != Some(toml::Value::Boolean(false))
        || root.remove("webServer")
            != Some(toml::Value::Table(admin_api(head.port, &head.password)))
    {
        return Err(AppError::Validation(
            "frpc config: the local head is not as written".to_string(),
        ));
    }
    validate_visitor_table(&root)?;
    Ok(config)
}

/// What a reconciliation does with the server TOML it fetched.
#[derive(Debug, PartialEq, Eq)]
enum RefreshPlan {
    /// No frpc runs: start one.
    Start,
    /// The common part changed (`serverAddr`, `serverPort`, `user`, `auth`, `transport`): frp
    /// reads it only at start, so stop and start again.
    Restart,
    /// Only the visitors changed: frpc reloads them, unchanged visitors keep their connections.
    Reload,
    /// Nothing changed.
    Unchanged,
}

/// Decide what to do with the server TOML `next`. `running` is the server TOML the running frpc
/// applied, `None` when no frpc runs. Both are compared parsed, so a reformatted TOML is
/// unchanged.
fn plan_refresh(running: Option<&toml::Value>, next: &toml::Value) -> RefreshPlan {
    let Some(running) = running else {
        return RefreshPlan::Start;
    };
    if common_part(running) != common_part(next) {
        RefreshPlan::Restart
    } else if running.get("visitors") != next.get("visitors") {
        RefreshPlan::Reload
    } else {
        RefreshPlan::Unchanged
    }
}

/// The root table without `visitors`: everything frp takes only at start.
fn common_part(config: &toml::Value) -> Option<toml::Table> {
    let mut root = config.as_table()?.clone();
    root.remove("visitors");
    Some(root)
}

/// The file frpc reads its config from, in the app data dir.
const VISITOR_CONFIG: &str = "visitor.toml";

fn app_data_dir(app: &tauri::AppHandle) -> Result<PathBuf, AppError> {
    app.path().app_data_dir().map_err(|e| {
        AppError::Io(std::io::Error::new(
            std::io::ErrorKind::NotFound,
            e.to_string(),
        ))
    })
}

/// Write the config frpc runs to the app data dir and export the enrolled identity it
/// references (F2). The server ships only the TOML; the desktop supplies its own
/// mTLS identity for the visitor.
fn write_visitor_config(
    data_dir: &Path,
    server_toml: &str,
    head: &LocalHead,
) -> Result<(), AppError> {
    std::fs::create_dir_all(data_dir)?;

    // Reject a server-supplied config that isn't a plain STCP visitor before writing
    // and executing it (3.59).
    let identity_dir = data_dir.join("identity");
    let config = frpc_config(server_toml, &identity_dir.to_string_lossy(), head)?;
    if server_toml.contains("[transport.tls]") {
        export_identity(&identity_dir)?;
    }

    // visitor.toml contains the frp auth token and the admin API password -> 0600 on Unix.
    write_secret(&data_dir.join(VISITOR_CONFIG), config.as_bytes())?;
    Ok(())
}

/// What a reconciliation does to the disk and the sidecar, kept apart from its course so the
/// course is testable without either.
trait Sidecar {
    /// Write the config frpc reads: `server_toml` behind `head`.
    fn write(&self, server_toml: &str, head: &LocalHead) -> Result<(), AppError>;
    /// Spawn frpc on the written config into `process`, which is `state` locked by the caller.
    fn spawn(
        &self,
        state: &FrpcState,
        process: &mut FrpcProcess,
        applied: Applied,
    ) -> Result<(), AppError>;
}

/// The real one: `visitor.toml` in the app data dir, frpc through the shell plugin.
struct AppSidecar<'a> {
    app: &'a tauri::AppHandle,
    data_dir: PathBuf,
    username: &'a str,
}

impl Sidecar for AppSidecar<'_> {
    fn write(&self, server_toml: &str, head: &LocalHead) -> Result<(), AppError> {
        write_visitor_config(&self.data_dir, server_toml, head)
    }

    fn spawn(
        &self,
        state: &FrpcState,
        process: &mut FrpcProcess,
        applied: Applied,
    ) -> Result<(), AppError> {
        let config_path = self.data_dir.join(VISITOR_CONFIG);
        start_frpc(
            self.app,
            &config_path,
            state,
            process,
            self.username.to_string(),
            applied,
        )
    }
}

/// Start frpc as a sidecar process with the given config path. `guard` is `state`, locked by the
/// caller across the spawn.
fn start_frpc(
    app: &tauri::AppHandle,
    config_path: &std::path::Path,
    state: &FrpcState,
    guard: &mut FrpcProcess,
    visitor_name: String,
    applied: Applied,
) -> Result<(), AppError> {
    if guard.child.is_some() {
        return Err(AppError::Validation("frpc laeuft bereits".to_string()));
    }

    let config_str = config_path
        .to_str()
        .ok_or_else(|| AppError::Validation("Ungültiger Konfigurationspfad".to_string()))?;

    let shell = app.shell();
    let command = shell
        .sidecar("frpc")
        .map_err(|e| AppError::Connection(format!("frpc-Sidecar nicht gefunden: {e}")))?;

    let (mut rx, child) = command
        .args(["-c", config_str])
        .spawn()
        .map_err(|e| AppError::Connection(format!("frpc konnte nicht gestartet werden: {e}")))?;

    // Tag this spawn with a generation. A stop→start restart kills the old process and spawns a
    // new one, but the killed process's Terminated event arrives asynchronously — often AFTER
    // the new spawn. Without this check its log task would wipe the NEW tunnel's child (the
    // handle is dropped so the process keeps running un-killable, status shows "disconnected",
    // and a re-start fails on the taken visitor port) (4.29).
    guard.generation += 1;
    let my_gen = guard.generation;

    // Log frpc output in background
    let app_handle = app.clone();
    let state_for_task = state.clone();
    tauri::async_runtime::spawn(async move {
        use tauri_plugin_shell::process::CommandEvent;
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    log::info!("[frpc stdout] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Stderr(line) => {
                    log::warn!("[frpc stderr] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Terminated(payload) => {
                    log::warn!("[frpc] Prozess beendet: {:?}", payload);
                    // Reconcile the shared state so a stale `child` doesn't block a
                    // later restart with "frpc laeuft bereits". The lock waits for
                    // start_frpc to finish its own guard first (same mutex).
                    // Only reconcile and announce if this is still the current process — a
                    // stale Terminated event from a restarted-away process must neither wipe
                    // the new child (4.29) nor mark the running tunnel disconnected (R-0247).
                    // A poisoned lock leaves the generation unknown, so it announces as before.
                    let current = match state_for_task.lock() {
                        Ok(mut guard) => guard.reconcile_terminated(my_gen),
                        Err(_) => true,
                    };
                    if current {
                        let _ = app_handle.emit("frpc-terminated", payload.code);
                    }
                }
                CommandEvent::Error(err) => {
                    log::error!("[frpc error] {}", err);
                    // Same rule as Terminated: only the current process may announce, and a
                    // poisoned lock leaves the generation unknown, so it announces as before.
                    let current = match state_for_task.lock() {
                        Ok(guard) => guard.is_current(my_gen),
                        Err(_) => true,
                    };
                    if current {
                        let _ = app_handle.emit("frpc-error", err);
                    }
                }
                _ => {}
            }
        }
    });

    guard.child = Some(child);
    guard.visitor_name = Some(visitor_name);
    guard.connected_since = Some(chrono::Utc::now().to_rfc3339());
    guard.applied = Some(applied);

    Ok(())
}

/// Stop the running frpc process.
pub fn stop_frpc(state: &FrpcState) -> Result<(), AppError> {
    let mut guard = state.lock().unwrap_or_else(|e| e.into_inner()); // recover poison (2.84)
    if let Some(child) = guard.retire() {
        let _ = child.kill();
    }
    Ok(())
}

/// Get current tunnel status.
pub fn tunnel_status(state: &FrpcState) -> TunnelStatus {
    let guard = state.lock().unwrap_or_else(|e| e.into_inner());
    TunnelStatus {
        running: guard.child.is_some(),
        visitor_name: guard.visitor_name.clone(),
        connected_since: guard.connected_since.clone(),
        visitors: guard.visitors(),
    }
}

/// Ask the running frpc to reload its config file through its admin API on loopback.
async fn request_reload(head: &LocalHead) -> Result<(), AppError> {
    // An own client: no proxy may see the password, and a reload that hangs counts as failed.
    let client = crate::http_client::with_timeouts(reqwest::Client::builder())
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(RELOAD_TIMEOUT)
        .build()?;
    let response = client
        .get(format!("http://127.0.0.1:{}/api/reload", head.port))
        .basic_auth(ADMIN_API_USER, Some(&head.password))
        .send()
        .await?;
    if !response.status().is_success() {
        return Err(AppError::Connection(format!(
            "frpc reload answered {}",
            response.status()
        )));
    }
    Ok(())
}

/// Bring frpc in line with `server_toml`, the user's visitor TOML as fetched; `None` means no
/// tunnels and stops frpc. `since` is the generation before the fetch: a stop since then wins and
/// nothing starts. A TOML the allow-list rejects leaves the running frpc alone.
async fn reconcile(
    state: &FrpcState,
    sidecar: &impl Sidecar,
    server_toml: Option<&str>,
    since: u64,
) -> Result<RefreshOutcome, AppError> {
    let Some(server_toml) = server_toml else {
        stop_frpc(state)?;
        return Ok(RefreshOutcome::Stopped);
    };
    let next = validate_visitor_toml(server_toml)?;

    let (plan, head) = {
        let guard = state.lock().unwrap_or_else(|e| e.into_inner()); // recover poison (2.84)
        if guard.generation != since {
            return Ok(RefreshOutcome::Stopped);
        }
        let running = guard.applied.as_ref();
        (
            plan_refresh(running.map(|applied| &applied.server), &next),
            running.map(|applied| applied.head.clone()),
        )
    };

    match (plan, head) {
        (RefreshPlan::Unchanged, _) => Ok(RefreshOutcome::Unchanged),
        (RefreshPlan::Reload, Some(head)) => {
            reload(state, sidecar, server_toml, next, head, since).await
        }
        (RefreshPlan::Start, _) => start_fresh(
            state,
            sidecar,
            server_toml,
            next,
            since,
            RefreshOutcome::Started,
        ),
        (RefreshPlan::Restart | RefreshPlan::Reload, _) => start_fresh(
            state,
            sidecar,
            server_toml,
            next,
            since,
            RefreshOutcome::Restarted,
        ),
    }
}

/// Write `server_toml` behind the running frpc's own head and have it reload; it takes the
/// visitors from the file. A failed reload restarts frpc with a new head.
async fn reload(
    state: &FrpcState,
    sidecar: &impl Sidecar,
    server_toml: &str,
    next: toml::Value,
    head: LocalHead,
    since: u64,
) -> Result<RefreshOutcome, AppError> {
    sidecar.write(server_toml, &head)?;
    if let Err(e) = request_reload(&head).await {
        log::warn!("[frpc] reload failed, restarting: {e}");
        return start_fresh(
            state,
            sidecar,
            server_toml,
            next,
            since,
            RefreshOutcome::Restarted,
        );
    }

    let mut guard = state.lock().unwrap_or_else(|e| e.into_inner()); // recover poison (2.84)
    if guard.generation != since {
        return Ok(RefreshOutcome::Stopped);
    }
    if let Some(applied) = guard.applied.as_mut() {
        applied.server = next;
    }
    Ok(RefreshOutcome::Reloaded)
}

/// Stop whatever frpc runs and start one on `server_toml` with a new head, reporting `outcome` —
/// unless a stop came in since `since`, then nothing starts.
fn start_fresh(
    state: &FrpcState,
    sidecar: &impl Sidecar,
    server_toml: &str,
    next: toml::Value,
    since: u64,
    outcome: RefreshOutcome,
) -> Result<RefreshOutcome, AppError> {
    let head = LocalHead::fresh()?;
    sidecar.write(server_toml, &head)?;

    let mut guard = state.lock().unwrap_or_else(|e| e.into_inner()); // recover poison (2.84)
    if guard.generation != since {
        return Ok(RefreshOutcome::Stopped);
    }
    if let Some(child) = guard.retire() {
        let _ = child.kill();
    }
    sidecar.spawn(state, &mut guard, Applied { server: next, head })?;
    Ok(outcome)
}

/// One reconciliation: fetch the visitor bundle and bring frpc in line with it — start, restart,
/// reload or leave it; no tunnels stop it. A failure before that (network, 5xx, a 401 the refresh
/// could not cure) leaves the running frpc alone. `token` is not sent: the fetch sends the
/// session's current access token from the keyring (see [`auth::authenticated_get`]).
pub async fn refresh_tunnel(
    app: tauri::AppHandle,
    state: FrpcState,
    lock: &RefreshLock,
    server_url: &str,
    token: &str,
    username: &str,
    allow_self_signed: bool,
) -> Result<TunnelRefresh, AppError> {
    let _serial = lock.0.lock().await;
    let since = state.lock().unwrap_or_else(|e| e.into_inner()).generation;
    // Fetched under the lock: authenticated_get reads the keyring token only now, so a
    // reconciliation queued behind one that renewed it sends the renewed one and does not
    // refresh again.
    let bundle = fetch_visitor_bundle(server_url, token, allow_self_signed).await?;
    let sidecar = AppSidecar {
        app: &app,
        data_dir: app_data_dir(&app)?,
        username,
    };
    let server_toml = bundle.as_ref().map(|bundle| bundle.toml.as_str());
    let outcome = reconcile(&state, &sidecar, server_toml, since).await?;
    Ok(TunnelRefresh {
        status: tunnel_status(&state),
        outcome,
    })
}

#[cfg(test)]
mod tests {
    use std::cell::{Cell, RefCell};
    use std::sync::{Arc, Mutex, MutexGuard};

    use super::{
        bundle_from, carries_bundle, frpc_config, plan_refresh, reconcile, request_reload,
        rewrite_identity_paths, tunnel_status, validate_visitor_toml, visitor_names,
        with_local_head, Applied, FrpcProcess, FrpcState, LocalHead, RefreshPlan, Sidecar,
        NO_IDENTITY_HINT,
    };
    use crate::error::AppError;
    use crate::models::RefreshOutcome;

    const LEGIT_VISITOR: &str = r#"
serverAddr = "frps.example.net"
serverPort = 7000
user = "ops-admin"
auth.method = "token"
auth.token = "sekret"

[transport.tls]
certFile = "/x/cert.pem"

[[visitors]]
name = "db-visitor"
type = "stcp"
serverName = "db"
serverUser = "srv-a"
secretKey = "s3cr3t"
bindAddr = "127.0.0.1"
bindPort = 6000
"#;

    #[test]
    fn no_identity_hint_names_the_one_time_token_not_a_login() {
        // ADR 0003: the login does not enroll, so the hint must not send anyone there.
        assert!(NO_IDENTITY_HINT.contains("one-time enrollment token from your administrator"));
        let lower = NO_IDENTITY_HINT.to_lowercase();
        for login in ["log in", "login", "sign in", "anmelden"] {
            assert!(
                !lower.contains(login),
                "hint asks for a login: {NO_IDENTITY_HINT}"
            );
        }
    }

    #[test]
    fn validate_visitor_toml_accepts_legit_stcp() {
        assert!(validate_visitor_toml(LEGIT_VISITOR).is_ok());
    }

    #[test]
    fn validate_visitor_toml_rejects_proxies_block() {
        // A server-injected [[proxies]] block (e.g. a static_file plugin) is refused.
        let evil = format!("{LEGIT_VISITOR}\n[[proxies]]\nname = \"x\"\ntype = \"tcp\"\n");
        assert!(validate_visitor_toml(&evil).is_err());
    }

    #[test]
    fn validate_visitor_toml_rejects_visitor_plugin() {
        let evil = concat!(
            "serverAddr = \"f\"\nserverPort = 7000\n\n",
            "[[visitors]]\nname = \"x\"\ntype = \"stcp\"\nsecretKey = \"s\"\n",
            "plugin.type = \"static_file\"\n",
        );
        assert!(validate_visitor_toml(evil).is_err());
    }

    #[test]
    fn validate_visitor_toml_rejects_non_stcp_visitor() {
        let evil = concat!(
            "serverAddr = \"f\"\nserverPort = 7000\n\n",
            "[[visitors]]\nname = \"x\"\ntype = \"xtcp\"\nsecretKey = \"s\"\n",
        );
        assert!(validate_visitor_toml(evil).is_err());
    }

    #[test]
    fn validate_visitor_toml_rejects_unknown_top_key() {
        let evil = format!("{LEGIT_VISITOR}\nevilKey = \"boom\"\n");
        assert!(validate_visitor_toml(&evil).is_err());
    }

    #[test]
    fn validate_visitor_toml_accepts_every_form_the_server_generates() {
        let no_visitors = &SERVER_TOML[..SERVER_TOML.find("\n[[visitors]]").unwrap()];
        for (case, form) in [
            ("TLS block and two visitors", SERVER_TOML.to_string()),
            ("without the TLS block", server_toml_with(TLS_BLOCK, "")),
            (
                "a visitor without serverUser",
                server_toml_with("serverUser = \"srv-a\"\n", ""),
            ),
            ("no visitors", no_visitors.to_string()),
        ] {
            assert!(validate_visitor_toml(&form).is_ok(), "rejected: {case}");
            let config = frpc_config(&form, "/data/app/identity", &head(7400, "c0ffee"));
            assert!(config.is_ok(), "frpc_config rejected: {case}");
        }
    }

    #[test]
    fn validate_visitor_toml_rejects_any_other_key_under_auth_and_transport() {
        let auth = "auth.token = \"sekret\"\n";
        let auth_lines = "auth.method = \"token\"\nauth.token = \"sekret\"\n";
        let tls = "keyFile = \"{{IDENTITY_DIR}}/key.pem\"\n";
        let without_tls = server_toml_with(TLS_BLOCK, "");
        let plus = |at: &str, extra: &str| server_toml_with(at, &format!("{at}{extra}\n"));
        let plus_without_tls =
            |extra: &str| without_tls.replacen(auth, &format!("{auth}{extra}\n"), 1);
        for (case, evil) in [
            (
                "auth.additionalScopes",
                plus(auth, "auth.additionalScopes = [\"HeartBeats\"]"),
            ),
            ("auth.oidc", plus(auth, "auth.oidc.clientID = \"x\"")),
            (
                "transport.protocol",
                plus(auth, "transport.protocol = \"tcp\""),
            ),
            ("transport.poolCount", plus(auth, "transport.poolCount = 5")),
            (
                "transport.tls.serverName",
                plus(tls, "serverName = \"frps\""),
            ),
            (
                "transport.tls.disableCustomTLSFirstByte",
                plus(tls, "disableCustomTLSFirstByte = true"),
            ),
            (
                "auth as a value",
                server_toml_with(auth_lines, "auth = \"sekret\"\n"),
            ),
            (
                "transport as a value",
                plus_without_tls("transport = \"tcp\""),
            ),
            (
                "transport.tls as a value",
                plus_without_tls("transport.tls = true"),
            ),
        ] {
            // The TOML itself is valid: only the allow-list may refuse it.
            parse(&evil);
            assert!(validate_visitor_toml(&evil).is_err(), "accepted: {case}");
        }
    }

    #[test]
    fn validate_visitor_toml_rejects_an_auth_method_other_than_token() {
        for method in ["\"oidc\"", "\"Token\"", "\"\"", "1"] {
            let evil = server_toml_with(
                "auth.method = \"token\"",
                &format!("auth.method = {method}"),
            );
            parse(&evil);
            assert!(
                validate_visitor_toml(&evil).is_err(),
                "accepted: auth.method = {method}"
            );
        }
    }

    #[test]
    fn validate_visitor_toml_admits_only_loopback_as_bind_addr() {
        let loopback = "bindAddr = \"127.0.0.1\"";
        let last = SERVER_TOML.rfind(loopback).unwrap();
        for bind_addr in [
            "\"0.0.0.0\"",
            "\"::\"",
            "\"127.0.0.2\"",
            "\"localhost\"",
            "\"\"",
            "1",
        ] {
            let other = format!("bindAddr = {bind_addr}");
            let mut second = SERVER_TOML.to_string();
            second.replace_range(last..last + loopback.len(), &other);
            for (visitor, evil) in [
                ("the first visitor", server_toml_with(loopback, &other)),
                ("the second visitor", second),
            ] {
                parse(&evil);
                assert!(
                    validate_visitor_toml(&evil).is_err(),
                    "accepted {other} in {visitor}"
                );
                assert!(
                    frpc_config(&evil, "/data/app/identity", &head(7400, "c0ffee")).is_err(),
                    "frpc_config accepted {other} in {visitor}"
                );
            }
        }
    }

    #[test]
    fn visitor_toml_parse_error_names_line_and_column_not_the_line() {
        // The ü puts the column in characters one before the column in bytes.
        let secret = "ünique-secret-5e1d";
        let broken = server_toml_with(
            "secretKey = \"s3cr3t\"",
            &format!("secretKey = \"{secret}\" junk"),
        );
        // The parser's own text quotes the line: the instrument can fail.
        let parser = toml::from_str::<toml::Value>(&broken)
            .unwrap_err()
            .to_string();
        assert!(parser.contains(secret), "{parser}");
        assert!(
            parser.starts_with("TOML parse error at line 19, column 34\n"),
            "{parser}"
        );

        let message = validate_visitor_toml(&broken).unwrap_err().to_string();
        assert!(!message.contains(secret), "{message}");
        assert_eq!(message, "visitor.toml does not parse (line 19, column 34)");
    }

    #[test]
    fn rewrites_identity_placeholder_to_absolute() {
        let toml = "[transport.tls]\n\
             certFile = \"{{IDENTITY_DIR}}/cert.pem\"\n\
             keyFile = \"{{IDENTITY_DIR}}/key.pem\"\n\
             trustedCaFile = \"{{IDENTITY_DIR}}/ca.crt\"\n";
        let out = rewrite_identity_paths(toml, "/data/app/identity");
        assert!(out.contains("certFile = \"/data/app/identity/cert.pem\""));
        assert!(out.contains("keyFile = \"/data/app/identity/key.pem\""));
        assert!(out.contains("trustedCaFile = \"/data/app/identity/ca.crt\""));
        assert!(
            !out.contains("{{IDENTITY_DIR}}"),
            "no placeholder may remain"
        );
    }

    /// The three TLS paths of `config` as frpc reads them.
    fn tls_paths(config: &toml::Value) -> [Option<&str>; 3] {
        let tls = &config["transport"]["tls"];
        ["certFile", "keyFile", "trustedCaFile"].map(|key| tls[key].as_str())
    }

    /// `identity_dir` filled into SERVER_TOML parses back to exactly `<identity_dir>/cert.pem`
    /// and so on, both in the server TOML and in the config frpc runs.
    fn assert_identity_path_round_trips(identity_dir: &str) {
        let expected =
            ["cert.pem", "key.pem", "ca.crt"].map(|file| format!("{identity_dir}/{file}"));
        let expected = expected.each_ref().map(|path| Some(path.as_str()));

        let rewritten = rewrite_identity_paths(SERVER_TOML, identity_dir);
        let rewritten = toml::from_str::<toml::Value>(&rewritten)
            .unwrap_or_else(|e| panic!("{identity_dir:?}: server TOML does not parse: {e}"));
        assert_eq!(
            tls_paths(&rewritten),
            expected,
            "server TOML: {identity_dir:?}"
        );

        let config = frpc_config(SERVER_TOML, identity_dir, &head(7400, "c0ffee"))
            .unwrap_or_else(|e| panic!("{identity_dir:?}: frpc_config refused: {e}"));
        assert_eq!(
            tls_paths(&parse(&config)),
            expected,
            "frpc config: {identity_dir:?}"
        );
    }

    #[test]
    fn identity_path_from_windows_app_data_round_trips() {
        // `\U` and `\O` are an invalid and a reserved escape in a basic string; the `'` rules out
        // a literal string.
        assert_identity_path_round_trips(
            r"C:\Users\O'Brien Test\AppData\Roaming\com.admincave.adminhelper\identity",
        );
    }

    #[test]
    fn identity_path_with_quote_space_or_control_character_round_trips() {
        for identity_dir in [
            "/home/o\"brien test/.local/share/com.admincave.adminhelper/identity",
            "/data/tab\there/del\u{7f}and\u{1}soh/identity",
        ] {
            assert_identity_path_round_trips(identity_dir);
        }
    }

    #[test]
    fn reconcile_terminated_clears_state_only_for_the_current_generation() {
        let mut p = FrpcProcess::new();
        p.generation = 5;
        p.visitor_name = Some("v".to_string());
        p.connected_since = Some("2026-01-01T00:00:00Z".to_string());

        // A stale Terminated (older generation, from a restarted-away process) must NOT wipe the
        // current state (4.29).
        p.reconcile_terminated(3);
        assert!(
            p.visitor_name.is_some(),
            "stale generation must not reconcile"
        );
        assert!(p.connected_since.is_some());

        // The current generation's Terminated clears it, so a later restart isn't blocked with
        // "frpc laeuft bereits".
        p.reconcile_terminated(5);
        assert!(p.visitor_name.is_none());
        assert!(p.connected_since.is_none());
    }

    #[test]
    fn stale_terminated_is_not_announced_while_a_newer_frpc_runs() {
        // stop→start: the killed process was generation 1, generation 2 runs now.
        let mut p = FrpcProcess::new();
        p.generation = 2;
        p.visitor_name = Some("v".to_string());
        p.connected_since = Some("2026-01-01T00:00:00Z".to_string());

        // The old process's late Terminated must not reach the UI, which would show the running
        // tunnel as disconnected; the state stays.
        assert!(
            !p.reconcile_terminated(1),
            "stale generation must not be announced"
        );
        assert!(p.visitor_name.is_some());
        assert!(p.connected_since.is_some());

        // The running process's own Terminated is announced.
        assert!(
            p.reconcile_terminated(2),
            "current generation must be announced"
        );
    }

    #[test]
    fn stop_makes_a_late_terminated_stale() {
        // Generation 1 runs; the user stops it.
        let mut p = FrpcProcess::new();
        p.generation = 1;
        p.visitor_name = Some("v".to_string());
        p.connected_since = Some("2026-01-01T00:00:00Z".to_string());

        assert!(p.retire().is_none(), "no child in a unit test");
        assert!(p.visitor_name.is_none());
        assert!(p.connected_since.is_none());

        // The stopped process's Terminated arrives after the stop: it must not reach the UI,
        // which would turn the idle indicator into "disconnected" (R-0389).
        assert!(
            !p.reconcile_terminated(1),
            "a stopped process's Terminated must be stale"
        );
    }

    #[test]
    fn stale_error_is_not_announced_while_a_newer_frpc_runs() {
        // stop→start: the killed process was generation 1, generation 2 runs now.
        let mut p = FrpcProcess::new();
        p.generation = 2;
        p.visitor_name = Some("v".to_string());
        p.connected_since = Some("2026-01-01T00:00:00Z".to_string());

        // The old process's late Error must not reach the UI, which would show the running
        // tunnel as disconnected (R-0390); the check leaves the state alone.
        assert!(!p.is_current(1), "stale generation must not be announced");
        assert!(p.visitor_name.is_some());
        assert!(p.connected_since.is_some());

        // The running process's own Error is announced.
        assert!(p.is_current(2), "current generation must be announced");

        // After a stop no process is current: even the last one's Error is stale.
        p.retire();
        assert!(!p.is_current(2), "a stopped process's Error must be stale");
    }

    /// What the server's generate_visitor_toml sends: dotted auth keys, the TLS table, two
    /// visitors.
    const SERVER_TOML: &str = r#"serverAddr = "frps.example.net"
serverPort = 7000
user = "ops-admin"

auth.method = "token"
auth.token = "sekret"

[transport.tls]
enable = true
trustedCaFile = "{{IDENTITY_DIR}}/ca.crt"
certFile = "{{IDENTITY_DIR}}/cert.pem"
keyFile = "{{IDENTITY_DIR}}/key.pem"

[[visitors]]
name = "db-visitor"
type = "stcp"
serverName = "db"
serverUser = "srv-a"
secretKey = "s3cr3t"
bindAddr = "127.0.0.1"
bindPort = 6000

[[visitors]]
name = "web-visitor"
type = "stcp"
serverName = "web"
serverUser = "srv-b"
secretKey = "w3b"
bindAddr = "127.0.0.1"
bindPort = 6001
"#;

    fn parse(toml: &str) -> toml::Value {
        toml::from_str(toml).unwrap()
    }

    /// The `[transport.tls]` block of the server's `_tls_client_block`, as it stands in
    /// SERVER_TOML.
    const TLS_BLOCK: &str = "\n[transport.tls]\n\
         enable = true\n\
         trustedCaFile = \"{{IDENTITY_DIR}}/ca.crt\"\n\
         certFile = \"{{IDENTITY_DIR}}/cert.pem\"\n\
         keyFile = \"{{IDENTITY_DIR}}/key.pem\"\n";

    /// SERVER_TOML with the first `from` replaced; a fixture without `from` fails the test
    /// instead of silently comparing two equal configs.
    fn server_toml_with(from: &str, to: &str) -> String {
        assert!(SERVER_TOML.contains(from), "fixture lacks {from:?}");
        SERVER_TOML.replacen(from, to, 1)
    }

    /// [`server_toml_with`], parsed.
    fn changed(from: &str, to: &str) -> toml::Value {
        parse(&server_toml_with(from, to))
    }

    #[test]
    fn refresh_starts_when_no_frpc_runs() {
        assert_eq!(plan_refresh(None, &parse(SERVER_TOML)), RefreshPlan::Start);
    }

    #[test]
    fn refresh_reloads_when_only_visitors_change() {
        let running = parse(SERVER_TOML);
        let added = format!(
            "{SERVER_TOML}\n[[visitors]]\nname = \"ssh-visitor\"\ntype = \"stcp\"\n\
             serverName = \"ssh\"\nsecretKey = \"k\"\nbindAddr = \"127.0.0.1\"\nbindPort = 6002\n"
        );
        let second = SERVER_TOML
            .find("[[visitors]]\nname = \"web-visitor\"")
            .unwrap();
        for (case, next) in [
            ("visitor added", parse(&added)),
            ("visitor gone", parse(&SERVER_TOML[..second])),
            (
                "secret changed",
                changed("secretKey = \"s3cr3t\"", "secretKey = \"n3w\""),
            ),
            (
                "port changed",
                changed("bindPort = 6000", "bindPort = 6100"),
            ),
            (
                "server user changed",
                changed("serverUser = \"srv-a\"", "serverUser = \"srv-c\""),
            ),
        ] {
            assert_eq!(
                plan_refresh(Some(&running), &next),
                RefreshPlan::Reload,
                "{case}"
            );
        }
    }

    #[test]
    fn refresh_restarts_when_the_common_part_changes() {
        let running = parse(SERVER_TOML);
        let token_and_visitor = SERVER_TOML
            .replacen("auth.token = \"sekret\"", "auth.token = \"rotated\"", 1)
            .replacen("bindPort = 6000", "bindPort = 6100", 1);
        for (case, next) in [
            (
                "token rotated",
                changed("auth.token = \"sekret\"", "auth.token = \"rotated\""),
            ),
            (
                "serverAddr",
                changed(
                    "serverAddr = \"frps.example.net\"",
                    "serverAddr = \"frps2.example.net\"",
                ),
            ),
            (
                "serverPort",
                changed("serverPort = 7000", "serverPort = 7001"),
            ),
            (
                "user",
                changed("user = \"ops-admin\"", "user = \"other-admin\""),
            ),
            ("transport", changed("enable = true", "enable = false")),
            // A restart applies the visitors too; a reload would miss the token.
            ("token and a visitor", parse(&token_and_visitor)),
        ] {
            assert_eq!(
                plan_refresh(Some(&running), &next),
                RefreshPlan::Restart,
                "{case}"
            );
        }
    }

    #[test]
    fn refresh_leaves_the_same_config_unchanged_however_it_is_formatted() {
        let running = parse(SERVER_TOML);
        assert_eq!(
            plan_refresh(Some(&running), &parse(SERVER_TOML)),
            RefreshPlan::Unchanged
        );

        // The same values: tables instead of dotted keys and the other way round, an inline
        // array, other key order and spacing, a comment.
        let reformatted = r#"# reformatted
user="ops-admin"
serverPort=7000
serverAddr="frps.example.net"
transport.tls.keyFile = "{{IDENTITY_DIR}}/key.pem"
transport.tls.certFile = "{{IDENTITY_DIR}}/cert.pem"
transport.tls.trustedCaFile = "{{IDENTITY_DIR}}/ca.crt"
transport.tls.enable = true
visitors = [
  { bindPort = 6000, bindAddr = "127.0.0.1", secretKey = "s3cr3t", serverUser = "srv-a", serverName = "db", type = "stcp", name = "db-visitor" },
  { name = "web-visitor", type = "stcp", serverName = "web", serverUser = "srv-b", secretKey = "w3b", bindAddr = "127.0.0.1", bindPort = 6001 },
]

[auth]
token = "sekret"
method = "token"
"#;
        assert_eq!(
            plan_refresh(Some(&running), &parse(reformatted)),
            RefreshPlan::Unchanged
        );
    }

    #[test]
    fn refresh_head_puts_login_retry_and_the_admin_password_in_the_root() {
        let config = parse(&with_local_head(SERVER_TOML, 7400, "c0ffee").unwrap());

        assert_eq!(
            config.get("loginFailExit"),
            Some(&toml::Value::Boolean(false))
        );
        let web = config.get("webServer").expect("webServer in the root");
        assert_eq!(web.get("addr").and_then(|v| v.as_str()), Some("127.0.0.1"));
        assert_eq!(web.get("port").and_then(|v| v.as_integer()), Some(7400));
        assert_eq!(
            web.get("user").and_then(|v| v.as_str()),
            Some("adminhelper")
        );
        // Without a password frp serves the admin API, frps token and secretKeys included,
        // to every local process.
        assert_eq!(web.get("password").and_then(|v| v.as_str()), Some("c0ffee"));

        // Apart from the head, the server TOML arrives as sent: nothing slid into a table.
        let mut rest = config.as_table().unwrap().clone();
        rest.remove("loginFailExit");
        rest.remove("webServer");
        assert_eq!(toml::Value::Table(rest), parse(SERVER_TOML));
    }

    #[test]
    fn refresh_head_keeps_rejecting_a_server_that_sends_its_own() {
        for evil in [
            format!("loginFailExit = true\n{SERVER_TOML}"),
            format!("webServer.port = 7500\n{SERVER_TOML}"),
            format!("{SERVER_TOML}\n[webServer]\naddr = \"0.0.0.0\"\npassword = \"\"\n"),
        ] {
            assert!(
                with_local_head(&evil, 7400, "c0ffee").is_err(),
                "accepted: {evil}"
            );
        }
    }

    #[test]
    fn refresh_404_means_no_tunnels() {
        assert!(!carries_bundle(reqwest::StatusCode::NOT_FOUND).unwrap());
        assert!(carries_bundle(reqwest::StatusCode::OK).unwrap());
    }

    #[test]
    fn refresh_500_and_every_other_failure_is_an_error() {
        for code in [500, 502, 503, 401, 403] {
            let status = reqwest::StatusCode::from_u16(code).unwrap();
            assert!(carries_bundle(status).is_err(), "{status}");
        }
    }

    /// An HTTP/1.1 reply with `status` and `body` that closes the connection.
    fn reply(status: &str, body: &str) -> String {
        format!(
            "HTTP/1.1 {status}\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
            body.len()
        )
    }

    /// Answer one HTTP request on a fresh loopback port with `reply`; the task yields the
    /// request head as received.
    async fn serve_one(reply: String) -> (u16, tokio::task::JoinHandle<String>) {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let task = tokio::spawn(async move {
            let (mut tcp, _) = listener.accept().await.unwrap();
            let mut head = Vec::new();
            let mut buf = [0u8; 1024];
            while !head.windows(4).any(|w| w == b"\r\n\r\n") {
                let n = tcp.read(&mut buf).await.unwrap();
                if n == 0 {
                    break;
                }
                head.extend_from_slice(&buf[..n]);
            }
            tcp.write_all(reply.as_bytes()).await.unwrap();
            let _ = tcp.shutdown().await;
            String::from_utf8_lossy(&head).into_owned()
        });
        (port, task)
    }

    fn head(port: u16, password: &str) -> LocalHead {
        LocalHead {
            port,
            password: password.to_string(),
        }
    }

    /// Records what a reconciliation writes and spawns.
    #[derive(Default)]
    struct FakeSidecar {
        /// Every write: the server TOML and the head it went behind.
        writes: RefCell<Vec<(String, LocalHead)>>,
        spawns: Cell<u32>,
    }

    impl Sidecar for FakeSidecar {
        fn write(&self, server_toml: &str, head: &LocalHead) -> Result<(), AppError> {
            self.writes
                .borrow_mut()
                .push((server_toml.to_string(), head.clone()));
            Ok(())
        }

        fn spawn(
            &self,
            _state: &FrpcState,
            process: &mut FrpcProcess,
            applied: Applied,
        ) -> Result<(), AppError> {
            // What start_frpc does to the state, without a process.
            process.generation += 1;
            process.connected_since = Some(format!("spawn {}", process.generation));
            process.applied = Some(applied);
            self.spawns.set(self.spawns.get() + 1);
            Ok(())
        }
    }

    /// A state whose frpc, generation 1, applied `server` behind `head`.
    fn running(server: &str, head: LocalHead) -> FrpcState {
        let mut process = FrpcProcess::new();
        process.generation = 1;
        process.connected_since = Some("spawn 1".to_string());
        process.applied = Some(Applied {
            server: parse(server),
            head,
        });
        Arc::new(Mutex::new(process))
    }

    fn lock(state: &FrpcState) -> MutexGuard<'_, FrpcProcess> {
        state.lock().unwrap()
    }

    /// SERVER_TOML with one visitor's port changed: a reload.
    fn moved_visitor() -> String {
        SERVER_TOML.replacen("bindPort = 6000", "bindPort = 6100", 1)
    }

    #[tokio::test]
    async fn refresh_reload_asks_the_admin_api_with_basic_auth() {
        let (port, request) = serve_one(reply("200 OK", "")).await;

        request_reload(&head(port, "c0ffee")).await.unwrap();

        let request = request.await.unwrap();
        assert!(
            request.starts_with("GET /api/reload HTTP/1.1\r\n"),
            "{request}"
        );
        let authorization = request.lines().find_map(|line| {
            let (name, value) = line.split_once(':')?;
            name.eq_ignore_ascii_case("authorization")
                .then_some(value.trim())
        });
        // base64("adminhelper:c0ffee")
        assert_eq!(authorization, Some("Basic YWRtaW5oZWxwZXI6YzBmZmVl"));
    }

    #[tokio::test]
    async fn refresh_reload_fails_on_an_error_reply_and_without_frpc() {
        for status in ["500 Internal Server Error", "401 Unauthorized"] {
            let (port, _request) = serve_one(reply(status, "")).await;
            assert!(
                request_reload(&head(port, "c0ffee")).await.is_err(),
                "{status}"
            );
        }
        let (_reserved, port) = crate::test_tls::refused_port();
        assert!(request_reload(&head(port, "c0ffee")).await.is_err());
    }

    #[tokio::test]
    async fn refresh_reloads_behind_the_running_head_and_keeps_the_process() {
        let (port, request) = serve_one(reply("200 OK", "")).await;
        let state = running(SERVER_TOML, head(port, "c0ffee"));
        let sidecar = FakeSidecar::default();
        let next = moved_visitor();

        let outcome = reconcile(&state, &sidecar, Some(&next), 1).await.unwrap();

        assert_eq!(outcome, RefreshOutcome::Reloaded);
        assert!(request.await.unwrap().starts_with("GET /api/reload "));
        let writes = sidecar.writes.borrow();
        assert_eq!(writes.len(), 1);
        assert_eq!(writes[0].0, next);
        assert_eq!(
            (writes[0].1.port, writes[0].1.password.as_str()),
            (port, "c0ffee")
        );
        assert_eq!(sidecar.spawns.get(), 0);
        let process = lock(&state);
        assert_eq!(process.generation, 1);
        assert_eq!(process.connected_since.as_deref(), Some("spawn 1"));
        assert_eq!(process.applied.as_ref().unwrap().server, parse(&next));
    }

    #[tokio::test]
    async fn refresh_reload_failure_restarts_with_a_new_head() {
        // Nothing answers on the admin API port the running frpc was given.
        let (_reserved, port) = crate::test_tls::refused_port();
        let state = running(SERVER_TOML, head(port, "c0ffee"));
        let sidecar = FakeSidecar::default();
        let next = moved_visitor();

        let outcome = reconcile(&state, &sidecar, Some(&next), 1).await.unwrap();

        assert_eq!(outcome, RefreshOutcome::Restarted);
        let writes = sidecar.writes.borrow();
        assert_eq!(writes.len(), 2, "the reload's write, then the restart's");
        let (old, new) = (&writes[0].1, &writes[1].1);
        assert_eq!((old.port, old.password.as_str()), (port, "c0ffee"));
        assert_ne!(new.port, port, "a restart takes a new port");
        assert_ne!(new.password, old.password, "a restart takes a new password");
        assert_eq!(writes[1].0, next);
        assert_eq!(sidecar.spawns.get(), 1);
        let process = lock(&state);
        assert_eq!(process.generation, 3, "retired to 2, spawned as 3");
        assert_eq!(process.applied.as_ref().unwrap().server, parse(&next));
    }

    #[tokio::test]
    async fn refresh_starts_and_restarts_behind_a_new_head_each() {
        let state: FrpcState = Arc::new(Mutex::new(FrpcProcess::new()));
        let sidecar = FakeSidecar::default();

        let outcome = reconcile(&state, &sidecar, Some(SERVER_TOML), 0)
            .await
            .unwrap();
        assert_eq!(outcome, RefreshOutcome::Started);

        let rotated =
            SERVER_TOML.replacen("auth.token = \"sekret\"", "auth.token = \"rotated\"", 1);
        let since = lock(&state).generation;
        let outcome = reconcile(&state, &sidecar, Some(&rotated), since)
            .await
            .unwrap();
        assert_eq!(outcome, RefreshOutcome::Restarted);

        assert_eq!(sidecar.spawns.get(), 2);
        let writes = sidecar.writes.borrow();
        assert_eq!(writes.len(), 2);
        assert_ne!(writes[0].1.password, writes[1].1.password);
        assert_eq!(
            lock(&state).applied.as_ref().unwrap().server,
            parse(&rotated)
        );
    }

    #[tokio::test]
    async fn refresh_leaves_an_unchanged_config_alone() {
        let state = running(SERVER_TOML, head(1, "c0ffee"));
        let sidecar = FakeSidecar::default();

        let outcome = reconcile(&state, &sidecar, Some(SERVER_TOML), 1)
            .await
            .unwrap();

        assert_eq!(outcome, RefreshOutcome::Unchanged);
        assert!(sidecar.writes.borrow().is_empty());
        assert_eq!(sidecar.spawns.get(), 0);
        assert_eq!(lock(&state).generation, 1);
    }

    #[tokio::test]
    async fn refresh_without_tunnels_stops_and_makes_the_old_process_stale() {
        let state = running(SERVER_TOML, head(1, "c0ffee"));
        let sidecar = FakeSidecar::default();

        let outcome = reconcile(&state, &sidecar, None, 1).await.unwrap();

        assert_eq!(outcome, RefreshOutcome::Stopped);
        assert!(sidecar.writes.borrow().is_empty());
        assert_eq!(sidecar.spawns.get(), 0);
        let mut process = lock(&state);
        assert!(process.applied.is_none());
        assert!(
            !process.reconcile_terminated(1),
            "the stopped frpc's Terminated must be stale"
        );
    }

    #[tokio::test]
    async fn refresh_rejected_toml_leaves_the_running_frpc_alone() {
        let state = running(SERVER_TOML, head(1, "c0ffee"));
        let sidecar = FakeSidecar::default();
        let rejected = format!("{SERVER_TOML}\n[[proxies]]\nname = \"x\"\ntype = \"tcp\"\n");

        assert!(reconcile(&state, &sidecar, Some(&rejected), 1)
            .await
            .is_err());

        assert!(sidecar.writes.borrow().is_empty());
        assert_eq!(sidecar.spawns.get(), 0);
        let process = lock(&state);
        assert_eq!(process.generation, 1);
        assert_eq!(process.applied.as_ref().unwrap().server, parse(SERVER_TOML));
    }

    #[tokio::test]
    async fn refresh_starts_nothing_after_a_stop_during_the_fetch() {
        let state: FrpcState = Arc::new(Mutex::new(FrpcProcess::new()));
        let since = lock(&state).generation;
        // The user stops the tunnel while the bundle is on its way.
        lock(&state).retire();
        let sidecar = FakeSidecar::default();

        let outcome = reconcile(&state, &sidecar, Some(SERVER_TOML), since)
            .await
            .unwrap();

        assert_eq!(outcome, RefreshOutcome::Stopped);
        assert_eq!(sidecar.spawns.get(), 0);
        assert!(lock(&state).applied.is_none());
    }

    /// Stops the tunnel on its first write: the user's stop while a reload runs.
    struct StopOnWrite {
        state: FrpcState,
        inner: FakeSidecar,
    }

    impl Sidecar for StopOnWrite {
        fn write(&self, server_toml: &str, head: &LocalHead) -> Result<(), AppError> {
            if self.inner.writes.borrow().is_empty() {
                lock(&self.state).retire();
            }
            self.inner.write(server_toml, head)
        }

        fn spawn(
            &self,
            state: &FrpcState,
            process: &mut FrpcProcess,
            applied: Applied,
        ) -> Result<(), AppError> {
            self.inner.spawn(state, process, applied)
        }
    }

    #[tokio::test]
    async fn refresh_a_stop_during_the_reload_wins() {
        // The stopped frpc no longer answers the reload: the failed reload must not restart it.
        let (_reserved, gone) = crate::test_tls::refused_port();
        // The reload got through just before the stop: it must not count as reloaded.
        let (answered, _request) = serve_one(reply("200 OK", "")).await;
        for port in [gone, answered] {
            let state = running(SERVER_TOML, head(port, "c0ffee"));
            let sidecar = StopOnWrite {
                state: state.clone(),
                inner: FakeSidecar::default(),
            };

            let outcome = reconcile(&state, &sidecar, Some(&moved_visitor()), 1)
                .await
                .unwrap();

            assert_eq!(outcome, RefreshOutcome::Stopped, "admin API port {port}");
            assert_eq!(sidecar.inner.spawns.get(), 0);
            assert!(lock(&state).applied.is_none());
        }
    }

    #[test]
    fn refresh_status_lists_the_applied_visitors() {
        assert_eq!(
            visitor_names(&parse(SERVER_TOML)),
            ["db-visitor", "web-visitor"]
        );
        assert!(visitor_names(&parse("serverAddr = \"f\"\n")).is_empty());

        let state = running(SERVER_TOML, head(1, "c0ffee"));
        assert_eq!(
            tunnel_status(&state).visitors,
            ["db-visitor", "web-visitor"]
        );
        let idle: FrpcState = Arc::new(Mutex::new(FrpcProcess::new()));
        assert!(tunnel_status(&idle).visitors.is_empty());
    }

    #[test]
    fn refresh_head_takes_only_a_hex_password() {
        for password in [
            "",
            "not hex",
            "c0ffeeg",
            "c0ffee\"\nwebServer.addr = \"0.0.0.0",
        ] {
            assert!(
                with_local_head(SERVER_TOML, 7400, password).is_err(),
                "accepted: {password:?}"
            );
        }
        assert!(with_local_head(SERVER_TOML, 7400, "C0FFEE").is_ok());
    }

    #[test]
    fn refresh_fresh_heads_are_hex_and_never_repeat() {
        let (a, b) = (LocalHead::fresh().unwrap(), LocalHead::fresh().unwrap());
        for fresh in [&a, &b] {
            assert_eq!(fresh.password.len(), 64, "32 random bytes, hex");
            assert!(fresh.password.bytes().all(|c| c.is_ascii_hexdigit()));
            assert_ne!(fresh.port, 0);
            assert!(with_local_head(SERVER_TOML, fresh.port, &fresh.password).is_ok());
        }
        assert_ne!(a.password, b.password);
    }

    #[test]
    fn refresh_config_fills_in_the_identity_dir_behind_the_head() {
        let config = frpc_config(SERVER_TOML, "/data/app/identity", &head(7400, "c0ffee"));
        let config = parse(&config.unwrap());

        assert_eq!(
            config.get("loginFailExit"),
            Some(&toml::Value::Boolean(false))
        );
        assert_eq!(config["webServer"]["port"].as_integer(), Some(7400));
        assert_eq!(config["webServer"]["password"].as_str(), Some("c0ffee"));
        assert_eq!(
            config["transport"]["tls"]["certFile"].as_str(),
            Some("/data/app/identity/cert.pem")
        );
    }

    #[test]
    fn refresh_config_checks_the_toml_again_after_the_identity_dir() {
        for identity_dir in [
            "/x/\"\n[[proxies]]\nname = \"p\"\ntype = \"tcp\"\n#",
            "/x/\"\n[webServer]\naddr = \"0.0.0.0\"\n#",
        ] {
            assert!(
                frpc_config(SERVER_TOML, identity_dir, &head(7400, "c0ffee")).is_err(),
                "accepted: {identity_dir:?}"
            );
        }
    }

    #[test]
    fn visitor_config_holds_no_template_delimiter() {
        let identity_dir = "/data/app/identity";
        for (case, server, identity_dir) in [
            (
                "serverAddr",
                server_toml_with("frps.example.net", "frps{{.example.net"),
                identity_dir,
            ),
            (
                "user",
                server_toml_with("\"ops-admin\"", "\"ops{{admin\""),
                identity_dir,
            ),
            (
                "auth.token",
                server_toml_with("\"sekret\"", "\"se{{kret\""),
                identity_dir,
            ),
            (
                "a TLS path",
                server_toml_with("{{IDENTITY_DIR}}/ca.crt", "{{IDENTITY_DIR}}/{{ca.crt"),
                identity_dir,
            ),
            (
                "a placeholder other than the identity dir",
                server_toml_with("{{IDENTITY_DIR}}/ca.crt", "{{IDENTITY}}/ca.crt"),
                identity_dir,
            ),
            (
                "a visitor name",
                server_toml_with("\"db-visitor\"", "\"db{{-visitor\""),
                identity_dir,
            ),
            (
                "a visitor secretKey",
                server_toml_with("\"s3cr3t\"", "\"s3{{cr3t\""),
                identity_dir,
            ),
            (
                "a comment",
                "# a {{ b\n".to_string() + SERVER_TOML,
                identity_dir,
            ),
            (
                "the identity dir",
                SERVER_TOML.to_string(),
                "/data/{{app/identity",
            ),
            (
                "an escape that spells it in a value",
                server_toml_with("\"ops-admin\"", "\"ops\\u007B\\u007Badmin\""),
                identity_dir,
            ),
        ] {
            // The allow-list itself admits it: only the delimiter may refuse it.
            assert!(validate_visitor_toml(&server).is_ok(), "allow-list: {case}");
            assert!(
                frpc_config(&server, identity_dir, &head(7400, "c0ffee")).is_err(),
                "accepted a template delimiter in {case}"
            );
        }
    }

    /// Whether every non-empty line of `text` is a table header or a key with its value, complete
    /// on its own: no string spans lines, and no line stems from anything but the table — a
    /// comment parses to nothing.
    fn every_line_is_complete(text: &str) -> bool {
        text.lines().all(|line| {
            line.is_empty()
                || toml::from_str::<toml::Table>(line).is_ok_and(|table| !table.is_empty())
        })
    }

    #[test]
    fn visitor_config_is_the_checked_table_with_every_string_on_one_line() {
        let identity_dir = "/data/app/identity";
        // The generator's values in other forms TOML allows for them: strings over several lines
        // without a line break in the value, an escape, a comment.
        let mut other_forms = SERVER_TOML.to_string();
        for (from, to) in [
            ("user = \"ops-admin\"", "user = \"\"\"\nops-admin\"\"\""),
            ("auth.token = \"sekret\"", "auth.token = '''sekret'''"),
            (
                "secretKey = \"s3cr3t\"",
                "secretKey = \"\"\"s3\\\n    cr3t\"\"\"",
            ),
            ("\"frps.example.net\"", "\"frps\\u002Eexample.net\""),
        ] {
            assert!(other_forms.contains(from), "fixture lacks {from:?}");
            other_forms = other_forms.replacen(from, to, 1);
        }
        other_forms.insert_str(0, "# a comment\n");
        let no_visitors = &SERVER_TOML[..SERVER_TOML.find("\n[[visitors]]").unwrap()];
        let without_tls = server_toml_with(TLS_BLOCK, "");
        let without_server_user = server_toml_with("serverUser = \"srv-a\"\n", "");

        let mut web_server = toml::Table::new();
        web_server.insert("addr".to_string(), "127.0.0.1".into());
        web_server.insert("port".to_string(), toml::Value::Integer(7400));
        web_server.insert("user".to_string(), "adminhelper".into());
        web_server.insert("password".to_string(), "c0ffee".into());

        for (case, form, values) in [
            ("TLS block and two visitors", SERVER_TOML, SERVER_TOML),
            (
                "without the TLS block",
                without_tls.as_str(),
                without_tls.as_str(),
            ),
            (
                "a visitor without serverUser",
                without_server_user.as_str(),
                without_server_user.as_str(),
            ),
            ("no visitors", no_visitors, no_visitors),
            (
                "other forms of the same values",
                other_forms.as_str(),
                SERVER_TOML,
            ),
        ] {
            let config = frpc_config(form, identity_dir, &head(7400, "c0ffee"))
                .unwrap_or_else(|e| panic!("{case}: {e:?}"));

            assert!(
                every_line_is_complete(&config),
                "{case}: a line is not complete on its own:\n{config}"
            );
            let mut root = parse(&config).as_table().unwrap().clone();
            assert_eq!(
                root.remove("loginFailExit"),
                Some(toml::Value::Boolean(false)),
                "{case}"
            );
            assert_eq!(
                root.remove("webServer"),
                Some(toml::Value::Table(web_server.clone())),
                "{case}"
            );
            assert_eq!(
                toml::Value::Table(root),
                parse(&rewrite_identity_paths(values, identity_dir)),
                "{case}"
            );
        }
    }

    #[test]
    fn visitor_config_refuses_a_value_with_a_line_break() {
        // toml writes a string with a line break over several lines; in the text frpc reads every
        // string stands on one line, so such a value is refused.
        let mut table = toml::Table::new();
        table.insert("user".to_string(), "ops\nadmin".into());
        assert!(toml::to_string(&table).unwrap().contains("\"\"\"\n"));

        for (case, server) in [
            (
                "a string over several lines",
                server_toml_with("\"ops-admin\"", "\"\"\"ops\nadmin\"\"\""),
            ),
            (
                "an escaped line break",
                server_toml_with("\"s3cr3t\"", "\"s3\\ncr3t\""),
            ),
            (
                "a literal string over several lines",
                server_toml_with("\"sekret\"", "'''sek\nret'''"),
            ),
            (
                "a string in an array",
                server_toml_with("serverName = \"db\"", "serverName = [\"d\\nb\"]"),
            ),
            (
                "a string in a table",
                server_toml_with(
                    "serverAddr = \"frps.example.net\"",
                    "serverAddr = { host = \"frps\\nexample.net\" }",
                ),
            ),
        ] {
            // The allow-list itself admits it: only the line break may refuse it.
            assert!(validate_visitor_toml(&server).is_ok(), "allow-list: {case}");
            assert!(
                frpc_config(&server, "/data/app/identity", &head(7400, "c0ffee")).is_err(),
                "accepted a line break in {case}"
            );
        }
    }

    #[tokio::test]
    async fn refresh_bundle_reply_404_is_no_tunnels_200_the_toml() {
        let client = reqwest::Client::builder().no_proxy().build().unwrap();
        let get = |port: u16| client.get(format!("http://127.0.0.1:{port}/")).send();

        let (port, _request) = serve_one(reply("404 Not Found", "")).await;
        let none = bundle_from(get(port).await.unwrap()).await.unwrap();
        assert!(none.is_none());

        let body = r#"{"toml":"serverAddr = \"f\""}"#;
        let (port, _request) = serve_one(reply("200 OK", body)).await;
        let bundle = bundle_from(get(port).await.unwrap()).await.unwrap();
        assert_eq!(bundle.expect("a bundle").toml, "serverAddr = \"f\"");

        let (port, _request) = serve_one(reply("500 Internal Server Error", "")).await;
        assert!(bundle_from(get(port).await.unwrap()).await.is_err());
    }
}
