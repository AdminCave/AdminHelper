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
use crate::models::{RefreshOutcome, TunnelRefresh, TunnelStatus, VisitorBinding};
use crate::port_registry::PortRegistry;
use crate::session::{SessionState, SignedIn};

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
    /// Where the runtime files of the tunnel lie (`run/` of the workspace), from the first
    /// reconciliation of this process on; `None` before it, while nothing of ours lies there.
    run_dir: Option<PathBuf>,
}

/// The config a running frpc applied: the server TOML with its visitors at their local ports,
/// parsed for the next comparison, where each visitor listens, the local head it runs with —
/// a reload keeps the head, frp reads `webServer` only at start — and the sign-in its bundle was
/// fetched for. A bundle of another sign-in never joins it by a reload (see [`reconcile`]).
struct Applied {
    server: toml::Value,
    bindings: Vec<VisitorBinding>,
    head: LocalHead,
    who: SignedIn,
}

/// A server TOML the allow-list admitted, its visitors rewritten to their local ports (see
/// [`remap_visitors`]), and where each went.
struct Remapped {
    server: toml::Value,
    bindings: Vec<VisitorBinding>,
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
            run_dir: None,
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

    /// Where the visitors of the running frpc listen.
    fn bindings(&self) -> Vec<VisitorBinding> {
        self.applied
            .as_ref()
            .map(|applied| applied.bindings.clone())
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

/// A visitor's name and the port the server TOML asked for. The allow-list admits a visitor only
/// with a name and a bindPort from 1 to 65535.
fn visitor_port(visitor: &toml::Table) -> Option<(String, u16)> {
    let name = visitor.get("name")?.as_str()?.to_string();
    let server_port = u16::try_from(visitor.get("bindPort")?.as_integer()?).ok()?;
    Some((name, server_port))
}

/// The name and server port of every visitor [`remap_visitors`] rewrites, in its order.
fn visitor_ports(config: &toml::Value) -> Vec<(String, u16)> {
    config
        .get("visitors")
        .and_then(toml::Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(toml::Value::as_table)
        .filter_map(visitor_port)
        .collect()
}

/// Rewrite every visitor of `config`, a server TOML [`validate_visitor_toml`] admitted, to listen
/// on `127.0.0.1` at the local port `ports` gives for its name and server port. Every other key
/// stays as the server sent it. Returns where each visitor went.
fn remap_visitors(
    config: &mut toml::Value,
    ports: &dyn Fn(&str, u16) -> u16,
) -> Vec<VisitorBinding> {
    let Some(visitors) = config
        .get_mut("visitors")
        .and_then(toml::Value::as_array_mut)
    else {
        return Vec::new();
    };
    visitors
        .iter_mut()
        .filter_map(toml::Value::as_table_mut)
        .filter_map(|visitor| {
            let (name, server_port) = visitor_port(visitor)?;
            let local_port = ports(&name, server_port);
            visitor.insert("bindAddr".to_string(), "127.0.0.1".into());
            visitor.insert("bindPort".to_string(), i64::from(local_port).into());
            Some(VisitorBinding {
                name,
                server_port,
                local_port,
            })
        })
        .collect()
}

#[derive(Deserialize)]
struct VisitorBundle {
    toml: String,
    // The server no longer ships PKI material (F2/F3: D6 — the server holds no
    // signing capability). The visitor presents the desktop's own enrolled
    // identity instead; any `pki` field the server still sends is ignored.
}

/// A visitor-bundle reply: the bundle, `None` for no tunnels (see [`carries_bundle`]), and
/// the HTTP code if the server refused the access (403).
struct BundleReply {
    bundle: Option<VisitorBundle>,
    refused: Option<u16>,
}

/// Fetch the visitor bundle from the server. TOML only — the server no longer
/// ships PKI (D6); the identity comes from enrollment. Comes with the sign-in it was fetched
/// for; a bundle that arrives after that user signed out, or after someone else signed in, is
/// refused, so frpc never takes over the tunnels of a session that is gone.
async fn fetch_visitor_bundle(session: &SessionState) -> Result<(BundleReply, SignedIn), AppError> {
    let path = "/api/frp/generate/visitor-bundle";
    let (response, who) = auth::authenticated_get(session, path).await?;
    let bundle = bundle_from(response).await?;
    session.ensure_signed_in(&who).await?;
    Ok((bundle, who))
}

/// What a visitor-bundle reply carries (see [`carries_bundle`]).
async fn bundle_from(response: reqwest::Response) -> Result<BundleReply, AppError> {
    let status = response.status();
    if !carries_bundle(status)? {
        let refused = (status == reqwest::StatusCode::FORBIDDEN).then_some(status.as_u16());
        return Ok(BundleReply {
            bundle: None,
            refused,
        });
    }

    let bundle: VisitorBundle = response.json().await.map_err(AppError::from)?;
    Ok(BundleReply {
        bundle: Some(bundle),
        refused: None,
    })
}

/// Whether a visitor-bundle reply with this status carries a bundle. 404 is no error but "no
/// tunnels": the server answers it both without an FRP config and when the user sees no usable
/// STCP tunnel (generate_router.py). 403 is "no tunnels" too: the server refuses the device or
/// the user access, say after a revocation, so the tunnels go. Every other non-2xx — a 401 the
/// refresh could not cure included — is an error.
fn carries_bundle(status: reqwest::StatusCode) -> Result<bool, AppError> {
    if status == reqwest::StatusCode::NOT_FOUND || status == reqwest::StatusCode::FORBIDDEN {
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

/// Replace the server's `{{IDENTITY_DIR}}` placeholder in the three file paths of
/// `transport.tls` of a parsed visitor TOML with the absolute identity dir the desktop exported
/// its mTLS material into. Every other value stays as it is, a placeholder in it included.
///
/// In the value, not the text: the serializer then writes the dir as a valid TOML string, the
/// backslashes of a Windows path (`\U` of `C:\Users`, `\A` of `\AppData`) and a `'` of a Windows
/// user name included.
fn rewrite_identity_paths(config: &mut toml::Value, abs_identity_dir: &str) {
    let Some(tls) = config
        .get_mut("transport")
        .and_then(|transport| transport.get_mut("tls"))
        .and_then(toml::Value::as_table_mut)
    else {
        return;
    };
    for key in ["trustedCaFile", "certFile", "keyFile"] {
        if let Some(toml::Value::String(path)) = tls.get_mut(key) {
            *path = path.replace(IDENTITY_DIR_PLACEHOLDER, abs_identity_dir);
        }
    }
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
/// those two emit are allowed, `auth.method` only as `token`. A visitor needs a `name` no other
/// visitor has, its `bindAddr` may only be `127.0.0.1`, and its `bindPort` must be a port from 1
/// to 65535 that no other visitor has.
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
        let mut names = std::collections::HashSet::new();
        let mut ports = std::collections::HashSet::new();
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
            let Some(name) = vt.get("name").and_then(toml::Value::as_str) else {
                return Err(AppError::Validation(
                    "visitor.toml: a visitor needs a name".to_string(),
                ));
            };
            // The name is the visitor's key in the port map.
            if !names.insert(name) {
                return Err(AppError::Validation(
                    "visitor.toml: two visitors have the same name".to_string(),
                ));
            }
            if vt
                .get("bindAddr")
                .is_some_and(|addr| addr.as_str() != Some("127.0.0.1"))
            {
                return Err(AppError::Validation(
                    "visitor.toml: a visitor's bindAddr must be \"127.0.0.1\"".to_string(),
                ));
            }
            let Some(port) = vt
                .get("bindPort")
                .and_then(toml::Value::as_integer)
                .filter(|port| (1..=65535).contains(port))
            else {
                return Err(AppError::Validation(
                    "visitor.toml: a visitor's bindPort must be a port from 1 to 65535".to_string(),
                ));
            };
            // A target on loopback at the port resolves to its visitor (tunnel.rs).
            if !ports.insert(port) {
                return Err(AppError::Validation(
                    "visitor.toml: two visitors have the same bindPort".to_string(),
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

/// How long a frpc an aborted run left behind may take to answer its stop, and then to close its
/// admin port.
const STOP_TIMEOUT: Duration = Duration::from_secs(2);

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
/// [`with_local_head`] generates it. The identity dir goes into the checked value, so the
/// filled-in TOML is checked again, and so is the generated text: its root holds the head exactly
/// as set and otherwise only what the allow-list admits. frp renders the config file as a Go
/// template before it reads the TOML (`pkg/config/load.go`, `RenderWithTemplate`), so neither the
/// server TOML nor the generated text, the identity dir in it, holds `{{` — an escape in the
/// server TOML can spell it in a value.
fn frpc_config(
    server_toml: &str,
    identity_dir: &str,
    head: &LocalHead,
) -> Result<String, AppError> {
    // The placeholder is the one `{{` the server TOML may hold; filled in, it is gone from the TLS
    // paths, and one anywhere else fails the check of the generated text below.
    no_template_delimiter(&server_toml.replace(IDENTITY_DIR_PLACEHOLDER, ""))?;
    let mut server = validate_visitor_toml(server_toml)?;
    rewrite_identity_paths(&mut server, identity_dir);
    let server_toml = toml::to_string(&server)
        .map_err(|e| AppError::Validation(format!("visitor.toml does not serialize: {e}")))?;
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

/// The file frpc reads its config from, in the run dir of the workspace.
const VISITOR_CONFIG: &str = "visitor.toml";

fn app_data_dir(app: &tauri::AppHandle) -> Result<PathBuf, AppError> {
    app.path().app_data_dir().map_err(|e| {
        AppError::Io(std::io::Error::new(
            std::io::ErrorKind::NotFound,
            e.to_string(),
        ))
    })
}

/// Where the runtime files of the tunnel lie in the app data dir `base`: `run/` of the workspace
/// of this process. The launcher has none and starts no tunnel.
fn runtime_dir(base: &Path) -> Result<PathBuf, AppError> {
    Ok(crate::workspace::current()?.run_dir(base))
}

/// Makes `run_dir` and any parent it lacks, 0700 on Unix: what goes into it is the frp token,
/// the admin API password and the private key.
fn make_run_dir(run_dir: &Path) -> std::io::Result<()> {
    let mut builder = std::fs::DirBuilder::new();
    #[cfg(unix)]
    std::os::unix::fs::DirBuilderExt::mode(&mut builder, 0o700);
    builder.recursive(true).create(run_dir)
}

/// Removes everything in `run_dir` and keeps the dir; a missing one holds nothing. A `run_dir`
/// that is no directory itself, a symlink or a junction, is an error: emptying it would empty
/// whatever it points to.
fn empty_run_dir(run_dir: &Path) -> Result<(), AppError> {
    let not_removed = |e: std::io::Error| {
        AppError::Io(std::io::Error::new(
            e.kind(),
            format!(
                "the runtime files of the tunnel in {} were not removed: {e}",
                run_dir.display()
            ),
        ))
    };
    match std::fs::symlink_metadata(run_dir) {
        Ok(meta) if meta.is_dir() => {}
        Ok(_) => {
            return Err(not_removed(std::io::Error::other(
                "it is a symlink, a junction or a file, not a directory",
            )))
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(e) => return Err(not_removed(e)),
    }
    for entry in std::fs::read_dir(run_dir).map_err(not_removed)? {
        let entry = entry.map_err(not_removed)?;
        let removed = if entry.file_type().map_err(not_removed)?.is_dir() {
            std::fs::remove_dir_all(entry.path())
        } else {
            std::fs::remove_file(entry.path())
        };
        removed.map_err(not_removed)?;
    }
    Ok(())
}

/// Removes the runtime files versions before workspaces kept in the app data dir `data_dir`
/// (`visitor.toml`, `identity/`): nothing writes or removes them there any more. One that is
/// gone already is fine, also when another workspace process removed it first; one that cannot
/// go is logged, and the tunnel starts all the same. Such a version writes both again at its
/// next tunnel start, the identity coming from the keyring.
fn remove_legacy_runtime_files(data_dir: &Path) {
    let config = data_dir.join(VISITOR_CONFIG);
    log_unless_gone(&config, std::fs::remove_file(&config));
    // A symlink here goes itself; remove_dir_all does not follow it.
    let identity = data_dir.join("identity");
    log_unless_gone(&identity, std::fs::remove_dir_all(&identity));
}

/// Logs the failed removal of `path` unless `path` is gone all the same.
fn log_unless_gone(path: &Path, removed: std::io::Result<()>) {
    let Err(e) = removed else {
        return;
    };
    let gone = std::fs::symlink_metadata(path)
        .is_err_and(|missing| missing.kind() == std::io::ErrorKind::NotFound);
    if !gone {
        log::warn!(
            "[frpc] runtime files of an earlier version at {} were not removed: {e}",
            path.display()
        );
    }
}

/// Write the config frpc runs to `run_dir` and export the enrolled identity it
/// references (F2). The server ships only the TOML; the desktop supplies its own
/// mTLS identity for the visitor.
fn write_visitor_config(
    run_dir: &Path,
    server_toml: &str,
    head: &LocalHead,
) -> Result<(), AppError> {
    make_run_dir(run_dir)?;

    // Reject a server-supplied config that isn't a plain STCP visitor before writing
    // and executing it (3.59).
    let identity_dir = run_dir.join("identity");
    let config = frpc_config(server_toml, &identity_dir.to_string_lossy(), head)?;
    // The checked table decides, not the text: TOML may write the TLS table as a header, in
    // dotted keys or inline.
    let checked: toml::Value =
        toml::from_str(&config).map_err(|e| parse_error("frpc config", &config, &e))?;
    if checked
        .get("transport")
        .and_then(|transport| transport.get("tls"))
        .is_some()
    {
        export_identity(&identity_dir)?;
    }

    // visitor.toml contains the frp auth token and the admin API password -> 0600 on Unix.
    write_secret(&run_dir.join(VISITOR_CONFIG), config.as_bytes())?;
    Ok(())
}

/// What a reconciliation does to the disk and the sidecar, kept apart from its course so the
/// course is testable without either.
trait Sidecar {
    /// The dir [`Sidecar::write`] writes into. Its files lie only while a frpc runs: the first
    /// reconciliation of a process empties it before anything is written, every one that leaves
    /// no frpc running empties it after, and so does every stop ([`stop_frpc`]).
    fn run_dir(&self) -> &Path;
    /// The app data dir: versions before workspaces kept the runtime files there, and the first
    /// reconciliation of a process removes them ([`remove_legacy_runtime_files`]).
    fn data_dir(&self) -> &Path;
    /// Write the config frpc reads: `server_toml`, the server TOML with its visitors at their local
    /// ports as the serializer writes it, behind `head`.
    fn write(&self, server_toml: &str, head: &LocalHead) -> Result<(), AppError>;
    /// Spawn frpc on the written config into `process`, which is `state` locked by the caller.
    fn spawn(
        &self,
        state: &FrpcState,
        process: &mut FrpcProcess,
        applied: Applied,
    ) -> Result<(), AppError>;
}

/// The real one: `visitor.toml` in `run/` of the workspace, frpc through the shell plugin.
struct AppSidecar<'a> {
    app: &'a tauri::AppHandle,
    run_dir: PathBuf,
    data_dir: PathBuf,
}

impl Sidecar for AppSidecar<'_> {
    fn run_dir(&self) -> &Path {
        &self.run_dir
    }

    fn data_dir(&self) -> &Path {
        &self.data_dir
    }

    fn write(&self, server_toml: &str, head: &LocalHead) -> Result<(), AppError> {
        write_visitor_config(&self.run_dir, server_toml, head)
    }

    fn spawn(
        &self,
        state: &FrpcState,
        process: &mut FrpcProcess,
        applied: Applied,
    ) -> Result<(), AppError> {
        let config_path = self.run_dir.join(VISITOR_CONFIG);
        start_frpc(self.app, &config_path, state, process, applied)
    }
}

/// Start frpc as a sidecar process with the given config path. `guard` is `state`, locked by the
/// caller across the spawn.
fn start_frpc(
    app: &tauri::AppHandle,
    config_path: &std::path::Path,
    state: &FrpcState,
    guard: &mut FrpcProcess,
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

    // `child` holds the process handle of frpc, so its pid names this frpc even if it already
    // ended.
    #[cfg(windows)]
    end_with_this_process(child.pid());

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
    guard.visitor_name = Some(applied.who.username.clone());
    guard.connected_since = Some(chrono::Utc::now().to_rfc3339());
    guard.applied = Some(applied);

    Ok(())
}

/// Puts frpc (`pid`) into the job object of this process, so Windows ends frpc when this process
/// ends, on any path ("End task" and crashes too): frpc does not end with the process that started
/// it, and Windows has no SIGPIPE to end it at its next log line. If that fails, frpc runs on as
/// before and the first reconciliation of the next start stops it.
#[cfg(windows)]
fn end_with_this_process(pid: u32) {
    // A static is never dropped: the handle stays open while this process lives, only this
    // process holds it, and Windows closes it when the process ends.
    static JOB: std::sync::OnceLock<std::io::Result<std::os::windows::io::OwnedHandle>> =
        std::sync::OnceLock::new();
    let assigned = match JOB.get_or_init(kill_on_close_job) {
        Ok(job) => assign_to_job(job, pid).map_err(|e| format!("not assigned to the job: {e}")),
        Err(e) => Err(format!("no job object: {e}")),
    };
    if let Err(e) = assigned {
        log::warn!("[frpc] frpc (pid {pid}) does not end with this process, {e}");
    }
}

/// A new job object whose processes Windows ends when its last handle closes. The handle is not
/// inheritable: a child of this process holding it would keep the job, and frpc, alive.
#[cfg(windows)]
fn kill_on_close_job() -> std::io::Result<std::os::windows::io::OwnedHandle> {
    use std::os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle};
    use windows::core::PCWSTR;
    use windows::Win32::Foundation::HANDLE;
    use windows::Win32::System::JobObjects::{
        CreateJobObjectW, JobObjectExtendedLimitInformation, SetInformationJobObject,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    // SAFETY: no security attributes (the handle is not inheritable) and no name; the call reads
    // nothing else.
    let job = unsafe { CreateJobObjectW(None, PCWSTR::null()) }?;
    // SAFETY: CreateJobObjectW succeeded, so the handle is open, and nothing else owns it.
    let job = unsafe { OwnedHandle::from_raw_handle(job.0) };
    let mut limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    // SAFETY: `job` is open, `limits` is the struct the class names, lives across the call, and
    // the length is its size.
    unsafe {
        SetInformationJobObject(
            HANDLE(job.as_raw_handle()),
            JobObjectExtendedLimitInformation,
            std::ptr::from_ref(&limits).cast(),
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        )
    }?;
    Ok(job)
}

/// Puts the process `pid` into `job`.
#[cfg(windows)]
fn assign_to_job(job: &std::os::windows::io::OwnedHandle, pid: u32) -> std::io::Result<()> {
    use std::os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle};
    use windows::Win32::Foundation::HANDLE;
    use windows::Win32::System::JobObjects::AssignProcessToJobObject;
    use windows::Win32::System::Threading::{OpenProcess, PROCESS_SET_QUOTA, PROCESS_TERMINATE};

    // SAFETY: the call takes plain values and returns a new handle or an error.
    let process = unsafe { OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, false, pid) }?;
    // SAFETY: OpenProcess succeeded, so the handle is open, and nothing else owns it; dropping it
    // closes it.
    let process = unsafe { OwnedHandle::from_raw_handle(process.0) };
    // SAFETY: both handles are open across the call.
    unsafe {
        AssignProcessToJobObject(HANDLE(job.as_raw_handle()), HANDLE(process.as_raw_handle()))
    }?;
    Ok(())
}

/// Stop the running frpc process and remove its runtime files: they lie only while it runs. The
/// process stops even if they cannot go; the error then says so, and the log too, as the stops on
/// a sign-in change and at exit drop the error.
pub fn stop_frpc(state: &FrpcState) -> Result<(), AppError> {
    let mut guard = state.lock().unwrap_or_else(|e| e.into_inner()); // recover poison (2.84)
    if let Some(child) = guard.retire() {
        let _ = child.kill();
    }
    match &guard.run_dir {
        Some(run_dir) => empty_run_dir(run_dir).inspect_err(|e| log::warn!("[frpc] {e}")),
        None => Ok(()),
    }
}

/// Get current tunnel status.
pub fn tunnel_status(state: &FrpcState) -> TunnelStatus {
    let guard = state.lock().unwrap_or_else(|e| e.into_inner());
    TunnelStatus {
        running: guard.child.is_some(),
        visitor_name: guard.visitor_name.clone(),
        connected_since: guard.connected_since.clone(),
        visitors: guard.visitors(),
        bindings: guard.bindings(),
    }
}

/// Where the visitors of the running frpc listen, if it runs for `who`: the bindings a stored
/// password and the tunnel resolution may use. Empty while none runs and while it runs for
/// another sign-in.
pub fn bindings_for(state: &FrpcState, who: &SignedIn) -> Vec<VisitorBinding> {
    let guard = state.lock().unwrap_or_else(|e| e.into_inner()); // recover poison (2.84)
    guard
        .applied
        .as_ref()
        .filter(|applied| same_sign_in(&applied.who, who))
        .map(|applied| applied.bindings.clone())
        .unwrap_or_default()
}

/// Whether `a` and `b` are the same user on the same server, as
/// [`SessionState::ensure_signed_in`] compares them.
fn same_sign_in(a: &SignedIn, b: &SignedIn) -> bool {
    a.server_url == b.server_url && a.username == b.username
}

/// A client for frpc's admin API on loopback. An own one: no proxy may see the password, it
/// follows no redirect, and a call that hangs past `timeout` counts as failed.
fn admin_api_client(timeout: Duration) -> Result<reqwest::Client, AppError> {
    let client = crate::http_client::with_timeouts(reqwest::Client::builder())
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(timeout)
        .build()?;
    Ok(client)
}

/// Ask the running frpc to reload its config file through its admin API on loopback.
async fn request_reload(head: &LocalHead) -> Result<(), AppError> {
    let response = admin_api_client(RELOAD_TIMEOUT)?
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

/// Ask the frpc behind `head` to stop through its admin API on loopback.
async fn request_stop(head: &LocalHead) -> Result<(), AppError> {
    let response = admin_api_client(STOP_TIMEOUT)?
        .post(format!("http://127.0.0.1:{}/api/stop", head.port))
        .basic_auth(ADMIN_API_USER, Some(&head.password))
        .send()
        .await?;
    if !response.status().is_success() {
        return Err(AppError::Connection(format!(
            "frpc stop answered {}",
            response.status()
        )));
    }
    Ok(())
}

/// The local head in `config`, the text of a frpc config: `webServer` exactly as
/// [`with_local_head`] writes it, on 127.0.0.1 for [`ADMIN_API_USER`] with a port from 1 to 65535
/// and a hex password, and nothing else in it. The error never holds the password.
fn local_head_in(config: &str) -> Result<LocalHead, AppError> {
    let parsed: toml::Value =
        toml::from_str(config).map_err(|e| parse_error("frpc config", config, &e))?;
    let web_server = parsed.get("webServer").and_then(toml::Value::as_table);
    let port = web_server
        .and_then(|table| table.get("port"))
        .and_then(toml::Value::as_integer)
        .and_then(|port| u16::try_from(port).ok())
        .filter(|&port| port != 0);
    let password = web_server
        .and_then(|table| table.get("password"))
        .and_then(toml::Value::as_str)
        .filter(|password| !password.is_empty() && password.bytes().all(|b| b.is_ascii_hexdigit()));
    match (web_server, port, password) {
        (Some(web_server), Some(port), Some(password))
            if *web_server == admin_api(port, password) =>
        {
            Ok(LocalHead {
                port,
                password: password.to_string(),
            })
        }
        _ => Err(AppError::Validation(
            "frpc config: webServer is not the desktop's local head".to_string(),
        )),
    }
}

/// The local head in the `visitor.toml` an earlier process of this workspace left in `run_dir`;
/// `None`, logged without the password, if there is none or it is not the desktop's.
fn head_left_behind(run_dir: &Path) -> Option<LocalHead> {
    // Like `empty_run_dir`, before anything is read: a symlink or a junction is no run dir of ours.
    if let Ok(meta) = std::fs::symlink_metadata(run_dir) {
        if !meta.is_dir() {
            log::warn!(
                "[frpc] {} is a symlink, a junction or a file, not a run dir: no frpc left behind to stop",
                run_dir.display()
            );
            return None;
        }
    }
    let path = run_dir.join(VISITOR_CONFIG);
    let head = match std::fs::read_to_string(&path) {
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            log::info!("[frpc] no frpc config left behind in {}", run_dir.display());
            return None;
        }
        read => read
            .map_err(AppError::from)
            .and_then(|config| local_head_in(&config)),
    };
    head.inspect_err(|e| {
        log::warn!(
            "[frpc] {} names no frpc left behind to stop: {e}",
            path.display()
        )
    })
    .ok()
}

/// Stop the frpc an aborted earlier process of this workspace left running behind `head`, and
/// wait up to [`STOP_TIMEOUT`] for its admin port to close: then it has ended and let go of the
/// visitors' ports too. A failure is logged only; there is no frpc any more, or the one there is
/// not ours.
async fn stop_left_behind(head: &LocalHead) {
    if let Err(e) = request_stop(head).await {
        log::warn!(
            "[frpc] the frpc left behind on admin port {} was not stopped: {e}",
            head.port
        );
        return;
    }
    let closed = async {
        let admin_port = (std::net::Ipv4Addr::LOCALHOST, head.port);
        while tokio::net::TcpStream::connect(admin_port).await.is_ok() {
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
    };
    match tokio::time::timeout(STOP_TIMEOUT, closed).await {
        Ok(()) => log::info!(
            "[frpc] stopped the frpc left behind on admin port {}",
            head.port
        ),
        Err(_) => log::warn!(
            "[frpc] the admin port {} of the stopped frpc left behind did not close within {}s",
            head.port,
            STOP_TIMEOUT.as_secs()
        ),
    }
}

/// Give every visitor of `config` its local port from `ports` and rewrite it to listen there (see
/// [`remap_visitors`]). The port map's file lock and bind tests run on a blocking thread;
/// `recheck` as [`PortRegistry::assign`] takes it.
async fn assign_ports(
    ports: &PortRegistry,
    config: &mut toml::Value,
    recheck: bool,
) -> Result<Vec<VisitorBinding>, AppError> {
    let wanted = visitor_ports(config);
    // The ports belong to the workspace of this process; the launcher has none and gets none.
    // Read here, not on the blocking thread: the workspace of a test lives on its own thread.
    let workspace_id = crate::workspace::current()?.id.to_string();
    let registry = ports.clone();
    let assigned = tauri::async_runtime::spawn_blocking(move || {
        registry.assign(&workspace_id, &wanted, recheck)
    })
    .await
    .map_err(|e| AppError::Io(std::io::Error::other(format!("port map: {e}"))))??;
    // assign answers for every visitor visitor_ports lists, and remap_visitors asks for exactly
    // those, so the server port below never stands in for a local one.
    Ok(remap_visitors(config, &|name, server_port| {
        assigned
            .iter()
            .find(|(assigned, _)| assigned == name)
            .map_or(server_port, |&(_, local_port)| local_port)
    }))
}

/// Bring frpc in line with `server_toml`, the user's visitor TOML as fetched; `None` means no
/// tunnels and stops frpc. `since` is the generation before the fetch: a stop since then wins and
/// nothing starts. A TOML the allow-list rejects leaves the running frpc alone. frpc gets the
/// visitors at their local ports from `ports`, and the comparison with the running frpc is on
/// that rewritten TOML. `who` is the sign-in the TOML was fetched for: a frpc that runs for
/// another one restarts, whatever the TOML. The runtime files in the sidecar's run dir lie only
/// while a frpc runs (see [`Sidecar::run_dir`]).
async fn reconcile(
    state: &FrpcState,
    sidecar: &impl Sidecar,
    ports: &PortRegistry,
    server_toml: Option<&str>,
    who: SignedIn,
    since: u64,
) -> Result<RefreshOutcome, AppError> {
    // Before the first reconciliation of this process clears the run dir, the frpc of the one that
    // wrote it goes, should it still run: frpc does not end with the process that started it, and
    // it keeps the tunnels of its sign-in open and the visitors' ports taken. The head in its
    // visitor.toml reaches exactly that frpc, the password is its own. No guard across the await.
    let left_behind = {
        let guard = state.lock().unwrap_or_else(|e| e.into_inner()); // recover poison (2.84)
        if guard.run_dir.is_none() {
            head_left_behind(sidecar.run_dir())
        } else {
            None
        }
    };
    if let Some(head) = left_behind {
        stop_left_behind(&head).await;
    }
    {
        let mut guard = state.lock().unwrap_or_else(|e| e.into_inner()); // recover poison (2.84)
        if guard.run_dir.is_none() {
            // No frpc of this process ran yet, so what lies there is left from one that ended
            // without a stop (a crash, a kill).
            empty_run_dir(sidecar.run_dir())?;
            remove_legacy_runtime_files(sidecar.data_dir());
            guard.run_dir = Some(sidecar.run_dir().to_path_buf());
        }
    }
    let outcome = bring_in_line(state, sidecar, ports, server_toml, who, since).await;
    // A stop meanwhile, a failed write or spawn: the files of a frpc that does not run go. Not
    // while one runs: a reload has it read its config again.
    let guard = state.lock().unwrap_or_else(|e| e.into_inner()); // recover poison (2.84)
    let emptied = match (&guard.applied, &guard.run_dir) {
        (None, Some(run_dir)) => empty_run_dir(run_dir),
        _ => Ok(()),
    };
    let outcome = outcome?;
    emptied?;
    Ok(outcome)
}

/// [`reconcile`] without the runtime files.
async fn bring_in_line(
    state: &FrpcState,
    sidecar: &impl Sidecar,
    ports: &PortRegistry,
    server_toml: Option<&str>,
    who: SignedIn,
    since: u64,
) -> Result<RefreshOutcome, AppError> {
    let Some(server_toml) = server_toml else {
        stop_frpc(state)?;
        return Ok(RefreshOutcome::Stopped);
    };
    let mut server = validate_visitor_toml(server_toml)?;

    let frpc_runs = {
        let guard = state.lock().unwrap_or_else(|e| e.into_inner()); // recover poison (2.84)
        if guard.generation != since {
            return Ok(RefreshOutcome::Stopped);
        }
        guard.applied.is_some()
    };
    // While no frpc of ours runs, nothing of ours holds the visitors' ports: one that does not
    // bind now went to someone else and moves.
    let bindings = assign_ports(ports, &mut server, !frpc_runs).await?;
    let config = toml::to_string(&server)
        .map_err(|e| AppError::Validation(format!("visitor.toml does not serialize: {e}")))?;
    let next = Remapped { server, bindings };

    let (plan, head) = {
        let mut guard = state.lock().unwrap_or_else(|e| e.into_inner()); // recover poison (2.84)
        if guard.generation != since {
            return Ok(RefreshOutcome::Stopped);
        }
        let plan = match guard.applied.as_ref() {
            // A frpc of another sign-in neither reloads nor stays as it is: `Applied` would then
            // hold the visitors of `who` under that other sign-in.
            Some(applied) if !same_sign_in(&applied.who, &who) => RefreshPlan::Restart,
            applied => plan_refresh(applied.map(|applied| &applied.server), &next.server),
        };
        if let (RefreshPlan::Unchanged, Some(applied)) = (&plan, guard.applied.as_mut()) {
            // frpc keeps its ports; a server port may have moved behind one.
            applied.bindings = next.bindings;
            return Ok(RefreshOutcome::Unchanged);
        }
        (
            plan,
            guard.applied.as_ref().map(|applied| applied.head.clone()),
        )
    };

    match (plan, head) {
        (RefreshPlan::Unchanged, _) => Ok(RefreshOutcome::Unchanged),
        (RefreshPlan::Reload, Some(head)) => {
            reload(state, sidecar, &config, next, who, head, since).await
        }
        (RefreshPlan::Start, _) => start_fresh(
            state,
            sidecar,
            &config,
            next,
            who,
            since,
            RefreshOutcome::Started,
        ),
        (RefreshPlan::Restart | RefreshPlan::Reload, _) => start_fresh(
            state,
            sidecar,
            &config,
            next,
            who,
            since,
            RefreshOutcome::Restarted,
        ),
    }
}

/// Write `config`, the rewritten server TOML, behind the running frpc's own head and have it
/// reload; it takes the visitors from the file. A failed reload restarts frpc with a new head.
/// The running frpc runs for `who` already ([`reconcile`]).
async fn reload(
    state: &FrpcState,
    sidecar: &impl Sidecar,
    config: &str,
    next: Remapped,
    who: SignedIn,
    head: LocalHead,
    since: u64,
) -> Result<RefreshOutcome, AppError> {
    sidecar.write(config, &head)?;
    if let Err(e) = request_reload(&head).await {
        log::warn!("[frpc] reload failed, restarting: {e}");
        return start_fresh(
            state,
            sidecar,
            config,
            next,
            who,
            since,
            RefreshOutcome::Restarted,
        );
    }

    let mut guard = state.lock().unwrap_or_else(|e| e.into_inner()); // recover poison (2.84)
    if guard.generation != since {
        return Ok(RefreshOutcome::Stopped);
    }
    if let Some(applied) = guard.applied.as_mut() {
        applied.server = next.server;
        applied.bindings = next.bindings;
    }
    Ok(RefreshOutcome::Reloaded)
}

/// Stop whatever frpc runs and start one for `who` on `config`, the rewritten server TOML, with a
/// new head, reporting `outcome` — unless a stop came in since `since`, then nothing starts.
fn start_fresh(
    state: &FrpcState,
    sidecar: &impl Sidecar,
    config: &str,
    next: Remapped,
    who: SignedIn,
    since: u64,
    outcome: RefreshOutcome,
) -> Result<RefreshOutcome, AppError> {
    let head = LocalHead::fresh()?;
    sidecar.write(config, &head)?;

    let mut guard = state.lock().unwrap_or_else(|e| e.into_inner()); // recover poison (2.84)
    if guard.generation != since {
        return Ok(RefreshOutcome::Stopped);
    }
    if let Some(child) = guard.retire() {
        let _ = child.kill();
    }
    let applied = Applied {
        server: next.server,
        bindings: next.bindings,
        head,
        who,
    };
    sidecar.spawn(state, &mut guard, applied)?;
    Ok(outcome)
}

/// One reconciliation: fetch the visitor bundle and bring frpc in line with it — start, restart,
/// reload or leave it; no tunnels (404, or 403: access refused, then named in `refused`) stop
/// it. A failure before that (network, 5xx, a 401 the refresh could not cure, a session that
/// changed meanwhile) leaves the running frpc alone. The fetch goes to the signed-in server
/// with the session's current access token (see [`auth::authenticated_get`]).
pub async fn refresh_tunnel(
    app: tauri::AppHandle,
    state: FrpcState,
    lock: &RefreshLock,
    session: &SessionState,
) -> Result<TunnelRefresh, AppError> {
    let _serial = lock.0.lock().await;
    let since = state.lock().unwrap_or_else(|e| e.into_inner()).generation;
    let data_dir = app_data_dir(&app)?;
    let run_dir = runtime_dir(&data_dir)?;
    let (reply, who) = fetch_visitor_bundle(session).await?;
    let ports = PortRegistry::new(&data_dir);
    let sidecar = AppSidecar {
        app: &app,
        run_dir,
        data_dir,
    };
    let server_toml = reply.bundle.as_ref().map(|bundle| bundle.toml.as_str());
    let outcome = reconcile(&state, &sidecar, &ports, server_toml, who, since).await?;
    Ok(TunnelRefresh {
        status: tunnel_status(&state),
        outcome,
        refused: reply.refused,
    })
}

#[cfg(test)]
mod tests {
    use std::cell::{Cell, RefCell};
    use std::net::{Ipv4Addr, TcpListener};
    use std::path::{Path, PathBuf};
    use std::sync::atomic::{AtomicU32, Ordering};
    use std::sync::{Arc, Mutex, MutexGuard};
    use std::time::Duration;

    use super::{
        bindings_for, bundle_from, carries_bundle, fetch_visitor_bundle, frpc_config, plan_refresh,
        reconcile, remap_visitors, request_reload, rewrite_identity_paths, runtime_dir, stop_frpc,
        stop_left_behind, tunnel_status, validate_visitor_toml, visitor_names, with_local_head,
        write_visitor_config, Applied, FrpcProcess, FrpcState, LocalHead, RefreshPlan, Sidecar,
        VisitorBinding, NO_IDENTITY_HINT, VISITOR_CONFIG,
    };
    use crate::error::AppError;
    use crate::keyring_store;
    use crate::models::RefreshOutcome;
    use crate::port_registry::{PortRegistry, FALLBACK_PORTS};
    use crate::session::{SessionState, SignedIn};

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
        let mut config = parse(
            "[transport.tls]\n\
             certFile = \"{{IDENTITY_DIR}}/cert.pem\"\n\
             keyFile = \"{{IDENTITY_DIR}}/key.pem\"\n\
             trustedCaFile = \"{{IDENTITY_DIR}}/ca.crt\"\n\
             [[visitors]]\n\
             serverName = \"{{IDENTITY_DIR}}/in-an-array\"\n",
        );
        rewrite_identity_paths(&mut config, "/data/app/identity");
        assert_eq!(
            tls_paths(&config),
            [
                Some("/data/app/identity/cert.pem"),
                Some("/data/app/identity/key.pem"),
                Some("/data/app/identity/ca.crt"),
            ]
        );
        // Only the three TLS paths take the identity dir; anywhere else the placeholder stays.
        assert_eq!(
            config["visitors"][0]["serverName"].as_str(),
            Some("{{IDENTITY_DIR}}/in-an-array")
        );

        // A placeholder that stays is a `{{` frp would render as a template: frpc never runs it.
        for (from, to) in [
            (
                "serverName = \"db\"",
                "serverName = \"{{IDENTITY_DIR}}/db\"",
            ),
            (
                "auth.token = \"sekret\"",
                "auth.token = \"{{IDENTITY_DIR}}\"",
            ),
        ] {
            let elsewhere = server_toml_with(from, to);
            assert!(validate_visitor_toml(&elsewhere).is_ok(), "{to}");
            assert!(
                frpc_config(&elsewhere, "/data/app/identity", &head(7400, "c0ffee")).is_err(),
                "frpc_config accepted {to}"
            );
        }
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

        let mut rewritten = parse(SERVER_TOML);
        rewrite_identity_paths(&mut rewritten, identity_dir);
        let rewritten = toml::to_string(&rewritten).unwrap();
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
    fn remap_visitors_binds_every_visitor_on_loopback_at_the_local_port() {
        // The second visitor without bindAddr: frp binds it on 127.0.0.1 too, the rewrite says so.
        let loopback = "bindAddr = \"127.0.0.1\"\n";
        let last = SERVER_TOML.rfind(loopback).unwrap();
        let mut server = SERVER_TOML.to_string();
        server.replace_range(last..last + loopback.len(), "");
        let mut config = validate_visitor_toml(&server).unwrap();
        let asked = RefCell::new(Vec::new());

        let bindings = remap_visitors(&mut config, &|name, server_port| {
            asked.borrow_mut().push((name.to_string(), server_port));
            if name == "db-visitor" {
                23005
            } else {
                23000
            }
        });

        assert_eq!(
            *asked.borrow(),
            [
                ("db-visitor".to_string(), 6000),
                ("web-visitor".to_string(), 6001)
            ]
        );
        assert_eq!(
            bindings,
            [
                VisitorBinding {
                    name: "db-visitor".to_string(),
                    server_port: 6000,
                    local_port: 23005,
                },
                VisitorBinding {
                    name: "web-visitor".to_string(),
                    server_port: 6001,
                    local_port: 23000,
                },
            ]
        );
        // Names and every other key as the server sent them; only the ports moved.
        let expected = SERVER_TOML
            .replacen("bindPort = 6000", "bindPort = 23005", 1)
            .replacen("bindPort = 6001", "bindPort = 23000", 1);
        assert_eq!(config, parse(&expected));

        let no_visitors = &SERVER_TOML[..SERVER_TOML.find("\n[[visitors]]").unwrap()];
        let mut config = validate_visitor_toml(no_visitors).unwrap();
        assert!(remap_visitors(&mut config, &|_, _| 23000).is_empty());
        assert_eq!(config, parse(no_visitors));
    }

    #[test]
    fn remap_visitors_gets_only_visitors_with_a_name_and_a_port_from_1_to_65535() {
        for port in ["1", "65535"] {
            let edge = server_toml_with("bindPort = 6000", &format!("bindPort = {port}"));
            assert!(validate_visitor_toml(&edge).is_ok(), "rejected {port}");
        }

        let mut evil = Vec::new();
        for other in [
            "bindPort = 0",
            "bindPort = -1",
            "bindPort = 65536",
            "bindPort = \"6000\"",
            "bindPort = 6000.0",
            "",
        ] {
            for (visitor, port) in [("first", "bindPort = 6000"), ("second", "bindPort = 6001")] {
                evil.push((
                    format!("{other:?} in the {visitor} visitor"),
                    server_toml_with(port, other),
                ));
            }
        }
        for (case, other) in [("no name", ""), ("a name that is no string", "name = 1\n")] {
            evil.push((
                case.to_string(),
                server_toml_with("name = \"db-visitor\"\n", other),
            ));
        }
        for (case, evil) in evil {
            // The TOML itself is valid: only the allow-list may refuse it.
            parse(&evil);
            assert!(validate_visitor_toml(&evil).is_err(), "accepted {case}");
            assert!(
                frpc_config(&evil, "/data/app/identity", &head(7400, "c0ffee")).is_err(),
                "frpc_config accepted {case}"
            );
        }
    }

    #[test]
    fn remap_visitors_config_with_a_windows_identity_path_is_valid_toml() {
        // The rewritten value goes to frpc as text: serialized, then the identity dir filled in.
        let identity_dir =
            r"C:\Users\O'Brien Test\AppData\Roaming\com.admincave.adminhelper\identity";
        let mut config = validate_visitor_toml(SERVER_TOML).unwrap();
        remap_visitors(&mut config, &|_, server_port| server_port + 17000);
        let rewritten = toml::to_string(&config).unwrap();

        let frpc = frpc_config(&rewritten, identity_dir, &head(7400, "c0ffee"))
            .unwrap_or_else(|e| panic!("frpc_config refused: {e}"));

        let frpc = parse(&frpc);
        let expected =
            ["cert.pem", "key.pem", "ca.crt"].map(|file| format!("{identity_dir}/{file}"));
        assert_eq!(
            tls_paths(&frpc),
            expected.each_ref().map(|path| Some(path.as_str()))
        );
        let ports: Vec<_> = frpc["visitors"]
            .as_array()
            .unwrap()
            .iter()
            .map(|visitor| visitor["bindPort"].as_integer())
            .collect();
        assert_eq!(ports, [Some(23000), Some(23001)]);
    }

    /// A fresh directory for one test case under the system temp dir.
    fn scratch_dir(case: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!("ah-frpc-{case}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        dir
    }

    #[test]
    fn remap_visitors_config_exports_the_identity_whenever_the_checked_table_has_tls() {
        let dotted = server_toml_with(
            TLS_BLOCK,
            "transport.tls.enable = true\n\
             transport.tls.trustedCaFile = \"{{IDENTITY_DIR}}/ca.crt\"\n\
             transport.tls.certFile = \"{{IDENTITY_DIR}}/cert.pem\"\n\
             transport.tls.keyFile = \"{{IDENTITY_DIR}}/key.pem\"\n",
        );
        let inline = server_toml_with(
            TLS_BLOCK,
            "transport = { tls = { enable = true, certFile = \"{{IDENTITY_DIR}}/cert.pem\" } }\n",
        );
        let without_tls = server_toml_with(TLS_BLOCK, "");
        // A value that spells the header does not make a TLS table.
        let header_in_a_value = without_tls.replacen(
            "secretKey = \"s3cr3t\"",
            "secretKey = \"[transport.tls]\"",
            1,
        );
        assert_ne!(
            header_in_a_value, without_tls,
            "fixture lacks the secretKey"
        );
        assert_eq!(
            parse(&dotted)["transport"],
            parse(SERVER_TOML)["transport"],
            "the dotted keys are the same table"
        );

        let _keyring = keyring_store::memory();
        let _standard = crate::workspace::enter(crate::workspace::Workspace {
            id: crate::workspace::WorkspaceId::parse("standard").unwrap(),
            name: "Standard".to_string(),
            legacy_keys: true,
        });
        for (key, value) in [
            ("enroll|key", "the key"),
            ("enroll|cert", "the cert"),
            ("enroll|ca", "the ca"),
        ] {
            keyring_store::set(key, value).unwrap();
        }
        for (case, server, exports) in [
            ("header", SERVER_TOML, true),
            ("dotted", dotted.as_str(), true),
            ("inline", inline.as_str(), true),
            ("without-tls", without_tls.as_str(), false),
            ("header-in-a-value", header_in_a_value.as_str(), false),
        ] {
            let dir = scratch_dir(&format!("identity-{case}"));

            write_visitor_config(&dir, server, &head(7400, "c0ffee"))
                .unwrap_or_else(|e| panic!("{case}: {e}"));

            assert!(dir.join(VISITOR_CONFIG).is_file(), "{case}");
            let key = std::fs::read_to_string(dir.join("identity").join("key.pem")).ok();
            assert_eq!(key.as_deref(), exports.then_some("the key"), "{case}");
            std::fs::remove_dir_all(&dir).unwrap();
        }

        // Without an enrolled identity a TLS table in dotted keys stops the start with the hint.
        keyring_store::delete("enroll|key").unwrap();
        // Deleted past enrollment, which holds what it read: read the keyring again.
        crate::enrollment::reload_identity();
        let dir = scratch_dir("identity-missing");
        let error = write_visitor_config(&dir, &dotted, &head(7400, "c0ffee")).unwrap_err();
        assert!(
            matches!(&error, AppError::Validation(hint) if hint == NO_IDENTITY_HINT),
            "{error}"
        );
        assert!(!dir.join(VISITOR_CONFIG).exists());
        let _ = std::fs::remove_dir_all(&dir);
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
    fn refresh_403_means_no_tunnels() {
        assert!(!carries_bundle(reqwest::StatusCode::FORBIDDEN).unwrap());
    }

    #[test]
    fn refresh_500_and_every_other_failure_is_an_error() {
        for code in [500, 502, 503, 401] {
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
    struct FakeSidecar {
        /// Every write: the server TOML and the head it went behind.
        writes: RefCell<Vec<(String, LocalHead)>>,
        spawns: Cell<u32>,
        /// Dirs of its own that nobody makes: the fake writes nothing to disk.
        run_dir: PathBuf,
        data_dir: PathBuf,
    }

    impl Default for FakeSidecar {
        fn default() -> Self {
            static NEXT: AtomicU32 = AtomicU32::new(0);
            let n = NEXT.fetch_add(1, Ordering::Relaxed);
            Self {
                writes: RefCell::default(),
                spawns: Cell::default(),
                run_dir: scratch_dir(&format!("run-{n}")),
                data_dir: scratch_dir(&format!("data-{n}")),
            }
        }
    }

    impl Sidecar for FakeSidecar {
        fn run_dir(&self) -> &Path {
            &self.run_dir
        }

        fn data_dir(&self) -> &Path {
            &self.data_dir
        }

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

    /// The workspace of the tests' reconciliations, so the owner of their visitors' ports.
    const OWNER: &str = "test";

    /// A port map in a fresh directory of its own, removed again on drop, and the workspace
    /// [`OWNER`] on this thread for as long: a reconciliation needs one.
    struct TempPorts {
        dir: std::path::PathBuf,
        registry: PortRegistry,
        _workspace: crate::workspace::EnteredWorkspace,
    }

    impl TempPorts {
        fn new() -> Self {
            static NEXT: AtomicU32 = AtomicU32::new(0);
            let dir = scratch_dir(&format!("ports-{}", NEXT.fetch_add(1, Ordering::Relaxed)));
            let registry = PortRegistry::new(&dir);
            Self {
                dir,
                registry,
                _workspace: entered(OWNER),
            }
        }
    }

    impl Drop for TempPorts {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.dir);
        }
    }

    /// The workspace `id` on this thread while the guard lives.
    fn entered(id: &str) -> crate::workspace::EnteredWorkspace {
        crate::workspace::enter(crate::workspace::Workspace {
            id: crate::workspace::WorkspaceId::parse(id).unwrap(),
            name: id.to_string(),
            legacy_keys: false,
        })
    }

    /// A port someone else listens on while the listener lives.
    fn taken_port() -> (TcpListener, u16) {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        (listener, port)
    }

    /// `server`, SERVER_TOML or a variant, with db-visitor at `db` and web-visitor at `web`
    /// instead of 6000 and 6001.
    fn at_ports(server: &str, [db, web]: [u16; 2]) -> String {
        for port in ["bindPort = 6000\n", "bindPort = 6001\n"] {
            assert!(server.contains(port), "fixture lacks {port:?}");
        }
        server
            .replacen("bindPort = 6000\n", &format!("bindPort = {db}\n"), 1)
            .replacen("bindPort = 6001\n", &format!("bindPort = {web}\n"), 1)
    }

    /// What frpc gets for `server`, SERVER_TOML or a variant, with its visitors at `locals`: the
    /// text the serializer writes.
    fn written_at(server: &str, locals: [u16; 2]) -> String {
        toml::to_string(&parse(&at_ports(server, locals))).unwrap()
    }

    fn binding(name: &str, server_port: u16, local_port: u16) -> VisitorBinding {
        VisitorBinding {
            name: name.to_string(),
            server_port,
            local_port,
        }
    }

    /// The bindings of SERVER_TOML's visitors at `locals`.
    fn bindings_at([db, web]: [u16; 2]) -> Vec<VisitorBinding> {
        vec![
            binding("db-visitor", 6000, db),
            binding("web-visitor", 6001, web),
        ]
    }

    const SERVER_URL: &str = "https://ah.example.net";

    fn signed_in(server_url: &str, username: &str) -> SignedIn {
        SignedIn {
            server_url: server_url.to_string(),
            username: username.to_string(),
            allow_self_signed: false,
        }
    }

    /// The sign-in the bundles of the tests are fetched for, unless one says otherwise.
    fn ops_admin() -> SignedIn {
        signed_in(SERVER_URL, "ops-admin")
    }

    /// A frpc of the tests that runs: the state, the port map that gave its visitors their local
    /// ports, and the listeners it holds on them, as a real frpc would.
    struct Running {
        state: FrpcState,
        ports: TempPorts,
        /// The local ports of db-visitor and web-visitor, never their server ports.
        locals: [u16; 2],
        _listeners: [TcpListener; 2],
    }

    /// A state whose frpc, generation 1, applied `server`, SERVER_TOML or a variant, behind `head`,
    /// with its visitors at local ports of their own, for [`ops_admin`].
    fn running(server: &str, head: LocalHead) -> Running {
        let listeners = [taken_port(), taken_port()];
        let locals = [listeners[0].1, listeners[1].1];
        let ports = TempPorts::new();
        ports.registry.seed(
            OWNER,
            &[
                ("db-visitor", 6000, locals[0]),
                ("web-visitor", 6001, locals[1]),
            ],
        );
        let mut process = FrpcProcess::new();
        process.generation = 1;
        process.connected_since = Some("spawn 1".to_string());
        process.applied = Some(Applied {
            server: parse(&at_ports(server, locals)),
            bindings: bindings_at(locals),
            head,
            who: ops_admin(),
        });
        Running {
            state: Arc::new(Mutex::new(process)),
            ports,
            locals,
            _listeners: listeners.map(|(listener, _)| listener),
        }
    }

    fn idle() -> FrpcState {
        Arc::new(Mutex::new(FrpcProcess::new()))
    }

    fn lock(state: &FrpcState) -> MutexGuard<'_, FrpcProcess> {
        state.lock().unwrap()
    }

    /// SERVER_TOML with one visitor's secret changed: a reload. A moved server port is none: the
    /// visitor keeps its local port.
    fn changed_visitor() -> String {
        server_toml_with("secretKey = \"s3cr3t\"", "secretKey = \"n3w\"")
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
        let running = running(SERVER_TOML, head(port, "c0ffee"));
        let state = &running.state;
        let sidecar = FakeSidecar::default();
        let next = changed_visitor();

        let outcome = reconcile(
            state,
            &sidecar,
            &running.ports.registry,
            Some(&next),
            ops_admin(),
            1,
        )
        .await
        .unwrap();

        assert_eq!(outcome, RefreshOutcome::Reloaded);
        assert!(request.await.unwrap().starts_with("GET /api/reload "));
        let writes = sidecar.writes.borrow();
        assert_eq!(writes.len(), 1);
        // frpc reads the server TOML with the visitors at their local ports.
        assert_eq!(writes[0].0, written_at(&next, running.locals));
        assert_eq!(
            (writes[0].1.port, writes[0].1.password.as_str()),
            (port, "c0ffee")
        );
        assert_eq!(sidecar.spawns.get(), 0);
        let process = lock(state);
        assert_eq!(process.generation, 1);
        assert_eq!(process.connected_since.as_deref(), Some("spawn 1"));
        let applied = process.applied.as_ref().unwrap();
        assert_eq!(applied.server, parse(&at_ports(&next, running.locals)));
        assert_eq!(applied.bindings, bindings_at(running.locals));
    }

    #[tokio::test]
    async fn refresh_reload_failure_restarts_with_a_new_head() {
        // Nothing answers on the admin API port the running frpc was given.
        let (_reserved, port) = crate::test_tls::refused_port();
        let running = running(SERVER_TOML, head(port, "c0ffee"));
        let state = &running.state;
        let sidecar = FakeSidecar::default();
        let next = changed_visitor();

        let outcome = reconcile(
            state,
            &sidecar,
            &running.ports.registry,
            Some(&next),
            ops_admin(),
            1,
        )
        .await
        .unwrap();

        assert_eq!(outcome, RefreshOutcome::Restarted);
        let writes = sidecar.writes.borrow();
        assert_eq!(writes.len(), 2, "the reload's write, then the restart's");
        let (old, new) = (&writes[0].1, &writes[1].1);
        assert_eq!((old.port, old.password.as_str()), (port, "c0ffee"));
        assert_ne!(new.port, port, "a restart takes a new port");
        assert_ne!(new.password, old.password, "a restart takes a new password");
        assert_eq!(writes[1].0, written_at(&next, running.locals));
        assert_eq!(sidecar.spawns.get(), 1);
        let process = lock(state);
        assert_eq!(process.generation, 3, "retired to 2, spawned as 3");
        let applied = process.applied.as_ref().unwrap();
        assert_eq!(applied.server, parse(&at_ports(&next, running.locals)));
        assert_eq!(applied.bindings, bindings_at(running.locals));
    }

    #[tokio::test]
    async fn refresh_starts_and_restarts_behind_a_new_head_each() {
        let state = idle();
        let ports = TempPorts::new();
        // The port map of an earlier run; nothing listens on its ports now.
        let locals = {
            let free = [taken_port(), taken_port()];
            [free[0].1, free[1].1]
        };
        ports.registry.seed(
            OWNER,
            &[
                ("db-visitor", 6000, locals[0]),
                ("web-visitor", 6001, locals[1]),
            ],
        );
        let sidecar = FakeSidecar::default();

        let outcome = reconcile(
            &state,
            &sidecar,
            &ports.registry,
            Some(SERVER_TOML),
            ops_admin(),
            0,
        )
        .await
        .unwrap();
        assert_eq!(outcome, RefreshOutcome::Started);

        let rotated =
            SERVER_TOML.replacen("auth.token = \"sekret\"", "auth.token = \"rotated\"", 1);
        let since = lock(&state).generation;
        let outcome = reconcile(
            &state,
            &sidecar,
            &ports.registry,
            Some(&rotated),
            ops_admin(),
            since,
        )
        .await
        .unwrap();
        assert_eq!(outcome, RefreshOutcome::Restarted);

        assert_eq!(sidecar.spawns.get(), 2);
        let writes = sidecar.writes.borrow();
        assert_eq!(writes.len(), 2);
        assert_ne!(writes[0].1.password, writes[1].1.password);
        assert_eq!(writes[0].0, written_at(SERVER_TOML, locals));
        assert_eq!(writes[1].0, written_at(&rotated, locals));
        assert_eq!(
            lock(&state).applied.as_ref().unwrap().server,
            parse(&at_ports(&rotated, locals))
        );
    }

    #[tokio::test]
    async fn refresh_leaves_an_unchanged_config_alone() {
        // The running frpc holds its visitors' ports: they must not read as taken.
        let running = running(SERVER_TOML, head(1, "c0ffee"));
        let state = &running.state;
        let sidecar = FakeSidecar::default();

        let outcome = reconcile(
            state,
            &sidecar,
            &running.ports.registry,
            Some(SERVER_TOML),
            ops_admin(),
            1,
        )
        .await
        .unwrap();

        assert_eq!(outcome, RefreshOutcome::Unchanged);
        assert!(sidecar.writes.borrow().is_empty());
        assert_eq!(sidecar.spawns.get(), 0);
        assert_eq!(lock(state).generation, 1);
        assert_eq!(tunnel_status(state).bindings, bindings_at(running.locals));
    }

    #[tokio::test]
    async fn refresh_gives_frpc_a_fallback_port_for_a_taken_server_port_and_keeps_it() {
        let state = idle();
        let ports = TempPorts::new();
        let sidecar = FakeSidecar::default();
        // Someone else listens on both server ports.
        let (db_holder, db) = taken_port();
        let (web_holder, web) = taken_port();
        let server = at_ports(SERVER_TOML, [db, web]);

        let outcome = reconcile(
            &state,
            &sidecar,
            &ports.registry,
            Some(&server),
            ops_admin(),
            0,
        )
        .await
        .unwrap();

        assert_eq!(outcome, RefreshOutcome::Started);
        let bindings = tunnel_status(&state).bindings;
        assert_eq!(bindings.len(), 2, "{bindings:?}");
        let locals = [bindings[0].local_port, bindings[1].local_port];
        for local in locals {
            assert!(FALLBACK_PORTS.contains(&local), "{bindings:?}");
        }
        assert_ne!(locals[0], locals[1]);
        assert_eq!(
            bindings,
            [
                binding("db-visitor", db, locals[0]),
                binding("web-visitor", web, locals[1]),
            ]
        );
        assert_eq!(
            sidecar.writes.borrow()[0].0,
            written_at(SERVER_TOML, locals)
        );

        // The server ports are free again; the visitors keep their ports all the same, so the
        // same server TOML changes nothing.
        drop((db_holder, web_holder));
        let since = lock(&state).generation;
        let outcome = reconcile(
            &state,
            &sidecar,
            &ports.registry,
            Some(&server),
            ops_admin(),
            since,
        )
        .await
        .unwrap();

        assert_eq!(outcome, RefreshOutcome::Unchanged);
        assert_eq!(sidecar.writes.borrow().len(), 1);
        assert_eq!(sidecar.spawns.get(), 1);
        assert_eq!(tunnel_status(&state).bindings, bindings);
    }

    #[tokio::test]
    async fn refresh_moves_an_own_port_someone_took_while_no_frpc_ran() {
        // An earlier run gave db-visitor its server port; then someone else took it.
        let (_holder, port) = taken_port();
        let second = SERVER_TOML
            .find("[[visitors]]\nname = \"web-visitor\"")
            .unwrap();
        let server =
            SERVER_TOML[..second].replacen("bindPort = 6000\n", &format!("bindPort = {port}\n"), 1);
        let ports = TempPorts::new();
        ports.registry.seed(OWNER, &[("db-visitor", port, port)]);
        let state = idle();
        let sidecar = FakeSidecar::default();

        let outcome = reconcile(
            &state,
            &sidecar,
            &ports.registry,
            Some(&server),
            ops_admin(),
            0,
        )
        .await
        .unwrap();

        assert_eq!(outcome, RefreshOutcome::Started);
        let bindings = tunnel_status(&state).bindings;
        assert_eq!(bindings.len(), 1, "{bindings:?}");
        let local = bindings[0].local_port;
        assert_ne!(local, port);
        assert!(FALLBACK_PORTS.contains(&local), "{bindings:?}");
        let written = parse(&sidecar.writes.borrow()[0].0);
        assert_eq!(
            written["visitors"][0]["bindPort"].as_integer(),
            Some(i64::from(local))
        );
    }

    #[tokio::test]
    async fn refresh_takes_the_port_registry_owner_from_the_workspace() {
        // Two workspaces with the same visitors on one port map, as two processes run them.
        let ports = TempPorts::new();
        let server_ports = {
            let free = [taken_port(), taken_port()];
            [free[0].1, free[1].1]
        };
        let server = at_ports(SERVER_TOML, server_ports);
        let mut locals = Vec::new();
        for id in ["w-0000000a", "w-0000000b"] {
            let _workspace = entered(id);
            let state = idle();
            let sidecar = FakeSidecar::default();

            let outcome = reconcile(
                &state,
                &sidecar,
                &ports.registry,
                Some(&server),
                ops_admin(),
                0,
            )
            .await
            .unwrap();

            assert_eq!(outcome, RefreshOutcome::Started, "{id}");
            let bindings = tunnel_status(&state).bindings;
            locals.push([bindings[0].local_port, bindings[1].local_port]);
        }

        assert_eq!(locals[0], server_ports);
        for local in locals[1] {
            assert!(FALLBACK_PORTS.contains(&local), "{locals:?}");
        }
        let mut others = ports.registry.local_ports_of_others("w-0000000b").unwrap();
        others.sort_unstable();
        let mut first = locals[0];
        first.sort_unstable();
        assert_eq!(others, first);
    }

    #[tokio::test]
    async fn refresh_without_a_workspace_starts_nothing_and_leaves_the_port_registry_alone() {
        // The launcher has no workspace, so nothing owns the visitors' ports.
        let dir = scratch_dir("no-workspace");
        let registry = PortRegistry::new(&dir);
        let state = idle();
        let sidecar = FakeSidecar::default();

        let result = reconcile(
            &state,
            &sidecar,
            &registry,
            Some(SERVER_TOML),
            ops_admin(),
            0,
        )
        .await;

        let no_workspace = crate::workspace::current().unwrap_err().to_string();
        assert_eq!(result.unwrap_err().to_string(), no_workspace);
        assert!(sidecar.writes.borrow().is_empty());
        assert_eq!(sidecar.spawns.get(), 0);
        assert!(lock(&state).applied.is_none());
        // No entry, for no owner.
        assert!(registry.local_ports_of_others("").unwrap().is_empty());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[tokio::test]
    async fn refresh_keeps_the_local_port_when_the_server_port_moves() {
        let running = running(SERVER_TOML, head(1, "c0ffee"));
        let state = &running.state;
        let sidecar = FakeSidecar::default();
        let moved = server_toml_with("bindPort = 6000", "bindPort = 6100");

        let outcome = reconcile(
            state,
            &sidecar,
            &running.ports.registry,
            Some(&moved),
            ops_admin(),
            1,
        )
        .await
        .unwrap();

        // frpc's config stays as it is; only the binding learns the new server port.
        assert_eq!(outcome, RefreshOutcome::Unchanged);
        assert!(sidecar.writes.borrow().is_empty());
        assert_eq!(sidecar.spawns.get(), 0);
        let [db, web] = running.locals;
        assert_eq!(
            tunnel_status(state).bindings,
            [
                binding("db-visitor", 6100, db),
                binding("web-visitor", 6001, web)
            ]
        );
    }

    #[tokio::test]
    async fn refresh_rejects_two_visitors_with_one_name() {
        // The name is the visitor's key in the port map.
        let twins = server_toml_with("name = \"web-visitor\"", "name = \"db-visitor\"");
        parse(&twins);
        let message = validate_visitor_toml(&twins).unwrap_err().to_string();
        assert!(!message.contains("db-visitor"), "{message}");
        assert!(frpc_config(&twins, "/data/app/identity", &head(7400, "c0ffee")).is_err());

        let running = running(SERVER_TOML, head(1, "c0ffee"));
        let state = &running.state;
        let sidecar = FakeSidecar::default();
        assert!(reconcile(
            state,
            &sidecar,
            &running.ports.registry,
            Some(&twins),
            ops_admin(),
            1
        )
        .await
        .is_err());
        assert!(sidecar.writes.borrow().is_empty());
        let process = lock(state);
        assert_eq!(
            process.applied.as_ref().unwrap().server,
            parse(&at_ports(SERVER_TOML, running.locals))
        );
    }

    #[tokio::test]
    async fn refresh_rejects_two_visitors_with_one_server_port() {
        // A target on loopback at that port would name two visitors at once.
        let twins = server_toml_with("bindPort = 6001", "bindPort = 6000");
        parse(&twins);
        let message = validate_visitor_toml(&twins).unwrap_err().to_string();
        assert!(!message.contains("6000"), "{message}");
        assert!(frpc_config(&twins, "/data/app/identity", &head(7400, "c0ffee")).is_err());

        let running = running(SERVER_TOML, head(1, "c0ffee"));
        let state = &running.state;
        let sidecar = FakeSidecar::default();
        assert!(reconcile(
            state,
            &sidecar,
            &running.ports.registry,
            Some(&twins),
            ops_admin(),
            1
        )
        .await
        .is_err());
        assert!(sidecar.writes.borrow().is_empty());
        let process = lock(state);
        assert_eq!(
            process.applied.as_ref().unwrap().server,
            parse(&at_ports(SERVER_TOML, running.locals))
        );
        assert_eq!(process.bindings(), bindings_at(running.locals));
    }

    #[test]
    fn refresh_writes_a_windows_identity_path_through_the_serializer() {
        // `\U` and `\A` are an invalid and a reserved escape in a basic string; the `'` rules out
        // a literal string. On Windows the backslashes separate directories, elsewhere they are
        // part of a name: the identity path holds them either way.
        let root = scratch_dir("windows-path");
        let data_dir = root.join(r"x\Users\O'Brien Test\AppData\Roaming\com.admincave.adminhelper");
        let _keyring = keyring_store::memory();
        let _standard = crate::workspace::enter(crate::workspace::Workspace {
            id: crate::workspace::WorkspaceId::parse("standard").unwrap(),
            name: "Standard".to_string(),
            legacy_keys: true,
        });
        for (key, value) in [
            ("enroll|key", "the key"),
            ("enroll|cert", "the cert"),
            ("enroll|ca", "the ca"),
        ] {
            keyring_store::set(key, value).unwrap();
        }

        write_visitor_config(
            &data_dir,
            &written_at(SERVER_TOML, [23000, 23001]),
            &head(7400, "c0ffee"),
        )
        .unwrap();

        let written = std::fs::read_to_string(data_dir.join(VISITOR_CONFIG)).unwrap();
        let written = parse(&written);
        let identity_dir = data_dir.join("identity").to_string_lossy().into_owned();
        assert!(
            identity_dir.contains(r"\Users\O'Brien Test\AppData"),
            "{identity_dir}"
        );
        let expected =
            ["cert.pem", "key.pem", "ca.crt"].map(|file| format!("{identity_dir}/{file}"));
        assert_eq!(
            tls_paths(&written),
            expected.each_ref().map(|path| Some(path.as_str()))
        );
        assert_eq!(written["visitors"][1]["bindPort"].as_integer(), Some(23001));
        std::fs::remove_dir_all(&root).unwrap();
    }

    #[tokio::test]
    async fn refresh_without_tunnels_stops_and_makes_the_old_process_stale() {
        let running = running(SERVER_TOML, head(1, "c0ffee"));
        let state = &running.state;
        let sidecar = FakeSidecar::default();

        let outcome = reconcile(
            state,
            &sidecar,
            &running.ports.registry,
            None,
            ops_admin(),
            1,
        )
        .await
        .unwrap();

        assert_eq!(outcome, RefreshOutcome::Stopped);
        assert!(sidecar.writes.borrow().is_empty());
        assert_eq!(sidecar.spawns.get(), 0);
        let mut process = lock(state);
        assert!(process.applied.is_none());
        assert!(
            !process.reconcile_terminated(1),
            "the stopped frpc's Terminated must be stale"
        );
    }

    #[tokio::test]
    async fn refresh_rejected_toml_leaves_the_running_frpc_alone() {
        let running = running(SERVER_TOML, head(1, "c0ffee"));
        let state = &running.state;
        let sidecar = FakeSidecar::default();
        let rejected = format!("{SERVER_TOML}\n[[proxies]]\nname = \"x\"\ntype = \"tcp\"\n");

        assert!(reconcile(
            state,
            &sidecar,
            &running.ports.registry,
            Some(&rejected),
            ops_admin(),
            1
        )
        .await
        .is_err());

        assert!(sidecar.writes.borrow().is_empty());
        assert_eq!(sidecar.spawns.get(), 0);
        let process = lock(state);
        assert_eq!(process.generation, 1);
        assert_eq!(
            process.applied.as_ref().unwrap().server,
            parse(&at_ports(SERVER_TOML, running.locals))
        );
    }

    #[tokio::test]
    async fn refresh_starts_nothing_after_a_stop_during_the_fetch() {
        let state = idle();
        let since = lock(&state).generation;
        // The user stops the tunnel while the bundle is on its way.
        lock(&state).retire();
        let ports = TempPorts::new();
        let sidecar = FakeSidecar::default();

        let outcome = reconcile(
            &state,
            &sidecar,
            &ports.registry,
            Some(SERVER_TOML),
            ops_admin(),
            since,
        )
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
        fn run_dir(&self) -> &Path {
            self.inner.run_dir()
        }

        fn data_dir(&self) -> &Path {
            self.inner.data_dir()
        }

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
            let running = running(SERVER_TOML, head(port, "c0ffee"));
            let state = &running.state;
            let sidecar = StopOnWrite {
                state: state.clone(),
                inner: FakeSidecar::default(),
            };

            let outcome = reconcile(
                state,
                &sidecar,
                &running.ports.registry,
                Some(&changed_visitor()),
                ops_admin(),
                1,
            )
            .await
            .unwrap();

            assert_eq!(outcome, RefreshOutcome::Stopped, "admin API port {port}");
            assert_eq!(sidecar.inner.spawns.get(), 0);
            assert!(lock(state).applied.is_none());
        }
    }

    /// The in-memory keyring on this thread with an identity enrolled for the workspace on it.
    fn enrolled() -> keyring_store::MemoryKeyring {
        let keyring = keyring_store::memory();
        let prefix = crate::workspace::current().unwrap().keyring_prefix();
        for (key, value) in [
            ("enroll|key", "the key"),
            ("enroll|cert", "the cert"),
            ("enroll|ca", "the ca"),
        ] {
            keyring_store::set(&format!("{prefix}{key}"), value).unwrap();
        }
        keyring
    }

    /// The names in `dir`, sorted; none in a dir that is not there.
    fn names_in(dir: &Path) -> Vec<String> {
        let entries = match std::fs::read_dir(dir) {
            Ok(entries) => entries,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Vec::new(),
            Err(e) => panic!("{}: {e}", dir.display()),
        };
        let mut names: Vec<String> = entries
            .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
            .collect();
        names.sort();
        names
    }

    /// Writes what frpc reads into `run/` of the workspace on this thread as the real sidecar
    /// does ([`write_visitor_config`]) and spawns as [`FakeSidecar`] does. With `stop` it stops
    /// the tunnel as its first write begins, with `fail_spawn` no frpc starts.
    struct DiskSidecar {
        inner: FakeSidecar,
        stop: Option<FrpcState>,
        fail_spawn: bool,
        /// What lay in the run dir as each write began.
        found: RefCell<Vec<Vec<String>>>,
    }

    impl DiskSidecar {
        /// Writes into `run/` of the workspace on this thread in the app data dir `base`.
        fn new(base: &Path) -> Self {
            Self {
                inner: FakeSidecar {
                    run_dir: runtime_dir(base).unwrap(),
                    data_dir: base.to_path_buf(),
                    ..FakeSidecar::default()
                },
                stop: None,
                fail_spawn: false,
                found: RefCell::default(),
            }
        }
    }

    impl Sidecar for DiskSidecar {
        fn run_dir(&self) -> &Path {
            self.inner.run_dir()
        }

        fn data_dir(&self) -> &Path {
            self.inner.data_dir()
        }

        fn write(&self, server_toml: &str, head: &LocalHead) -> Result<(), AppError> {
            let first = self.inner.writes.borrow().is_empty();
            if let Some(state) = self.stop.as_ref().filter(|_| first) {
                lock(state).retire();
            }
            self.found.borrow_mut().push(names_in(self.run_dir()));
            write_visitor_config(self.run_dir(), server_toml, head)?;
            self.inner.write(server_toml, head)
        }

        fn spawn(
            &self,
            state: &FrpcState,
            process: &mut FrpcProcess,
            applied: Applied,
        ) -> Result<(), AppError> {
            if self.fail_spawn {
                return Err(AppError::Connection("frpc did not start".to_string()));
            }
            self.inner.spawn(state, process, applied)
        }
    }

    #[test]
    fn runtime_files_lie_in_the_run_dir_of_the_workspace() {
        let base = scratch_dir("run-of-the-workspace");
        // The launcher has no workspace, so no run dir and no tunnel.
        let no_workspace = crate::workspace::current().unwrap_err().to_string();
        assert_eq!(runtime_dir(&base).unwrap_err().to_string(), no_workspace);

        let _workspace = entered("w-0000000c");
        let _keyring = enrolled();
        let run = runtime_dir(&base).unwrap();
        assert_eq!(run, base.join("workspaces").join("w-0000000c").join("run"));

        write_visitor_config(
            &run,
            &written_at(SERVER_TOML, [23000, 23001]),
            &head(7400, "c0ffee"),
        )
        .unwrap();

        assert_eq!(names_in(&run), ["identity", VISITOR_CONFIG]);
        let key = std::fs::read_to_string(run.join("identity").join("key.pem")).unwrap();
        assert_eq!(key, "the key");
        // Nothing of the tunnel lies in the app data dir itself.
        assert_eq!(names_in(&base), ["workspaces"]);
        let written = parse(&std::fs::read_to_string(run.join(VISITOR_CONFIG)).unwrap());
        let identity_dir = run.join("identity").to_string_lossy().into_owned();
        let expected =
            ["cert.pem", "key.pem", "ca.crt"].map(|file| format!("{identity_dir}/{file}"));
        assert_eq!(
            tls_paths(&written),
            expected.each_ref().map(|path| Some(path.as_str()))
        );
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = std::fs::metadata(&run).unwrap().permissions().mode() & 0o777;
            assert_eq!(mode, 0o700, "{}", run.display());
        }
        std::fs::remove_dir_all(&base).unwrap();
    }

    #[tokio::test]
    async fn a_stop_empties_the_run_dir() {
        // The stop button, a sign-in change and the end of the app stop through stop_frpc; a
        // bundle without tunnels stops through the reconciliation.
        for case in ["stop", "no tunnels"] {
            let ports = TempPorts::new();
            let _keyring = enrolled();
            let state = idle();
            let sidecar = DiskSidecar::new(&ports.dir);
            let started = reconcile(
                &state,
                &sidecar,
                &ports.registry,
                Some(SERVER_TOML),
                ops_admin(),
                0,
            )
            .await
            .unwrap();
            assert_eq!(started, RefreshOutcome::Started, "{case}");
            let run = sidecar.run_dir();
            assert_eq!(names_in(run), ["identity", VISITOR_CONFIG], "{case}");

            if case == "stop" {
                stop_frpc(&state).unwrap();
            } else {
                let since = lock(&state).generation;
                let outcome =
                    reconcile(&state, &sidecar, &ports.registry, None, ops_admin(), since)
                        .await
                        .unwrap();
                assert_eq!(outcome, RefreshOutcome::Stopped, "{case}");
            }

            assert!(lock(&state).applied.is_none(), "{case}");
            assert!(run.is_dir(), "{case}");
            assert!(names_in(run).is_empty(), "{case}: {:?}", names_in(run));
        }
    }

    #[tokio::test]
    async fn a_reconciliation_that_leaves_no_frpc_running_leaves_no_runtime_files() {
        for case in ["a stop during the start", "a failed spawn"] {
            let ports = TempPorts::new();
            let _keyring = enrolled();
            let state = idle();
            let mut sidecar = DiskSidecar::new(&ports.dir);
            if case == "a stop during the start" {
                sidecar.stop = Some(state.clone());
            } else {
                sidecar.fail_spawn = true;
            }

            let outcome = reconcile(
                &state,
                &sidecar,
                &ports.registry,
                Some(SERVER_TOML),
                ops_admin(),
                0,
            )
            .await;

            if case == "a stop during the start" {
                assert_eq!(outcome.unwrap(), RefreshOutcome::Stopped, "{case}");
            } else {
                assert!(outcome.is_err(), "{case}");
            }
            assert_eq!(sidecar.inner.writes.borrow().len(), 1, "{case}");
            assert!(lock(&state).applied.is_none(), "{case}");
            let left = names_in(sidecar.run_dir());
            assert!(left.is_empty(), "{case}: {left:?}");
        }
    }

    #[tokio::test]
    async fn leftovers_of_a_run_that_ended_without_a_stop_are_gone_before_the_first_write() {
        let ports = TempPorts::new();
        let _keyring = enrolled();
        let state = idle();
        let sidecar = DiskSidecar::new(&ports.dir);
        let run = sidecar.run_dir();
        // What a process that crashed while its frpc ran leaves behind.
        std::fs::create_dir_all(run.join("identity")).unwrap();
        std::fs::write(run.join(VISITOR_CONFIG), "the old config").unwrap();
        std::fs::write(run.join("identity").join("key.pem"), "the old key").unwrap();
        std::fs::write(run.join("visitor.toml.old"), "an old copy").unwrap();

        let outcome = reconcile(
            &state,
            &sidecar,
            &ports.registry,
            Some(SERVER_TOML),
            ops_admin(),
            0,
        )
        .await
        .unwrap();

        assert_eq!(outcome, RefreshOutcome::Started);
        assert_eq!(*sidecar.found.borrow(), [Vec::<String>::new()]);
        assert_eq!(names_in(run), ["identity", VISITOR_CONFIG]);
        let config = std::fs::read_to_string(run.join(VISITOR_CONFIG)).unwrap();
        assert_ne!(config, "the old config");

        // Only the first reconciliation of a process clears: from then on what lies there is of
        // its own frpc.
        std::fs::write(run.join("kept"), "").unwrap();
        let since = lock(&state).generation;
        let outcome = reconcile(
            &state,
            &sidecar,
            &ports.registry,
            Some(SERVER_TOML),
            ops_admin(),
            since,
        )
        .await
        .unwrap();

        assert_eq!(outcome, RefreshOutcome::Unchanged);
        assert_eq!(names_in(run), ["identity", "kept", VISITOR_CONFIG]);
    }

    /// Writes into the run dir of `sidecar` what a process killed while its frpc ran leaves
    /// there: that frpc's config, behind the head at `port` with the password c0ffee, as `edit`
    /// changes it.
    fn left_behind(sidecar: &DiskSidecar, port: u16, edit: fn(&mut toml::Table)) {
        let mut config = parse(&with_local_head(SERVER_TOML, port, "c0ffee").unwrap());
        edit(config.as_table_mut().unwrap());
        std::fs::create_dir_all(sidecar.run_dir()).unwrap();
        let text = toml::to_string(&config).unwrap();
        std::fs::write(sidecar.run_dir().join(VISITOR_CONFIG), text).unwrap();
    }

    /// The `webServer` table of a frpc config.
    fn web_server(config: &mut toml::Table) -> &mut toml::Table {
        config
            .get_mut("webServer")
            .and_then(toml::Value::as_table_mut)
            .unwrap()
    }

    /// The value of the Authorization header in the request head `request`.
    fn authorization(request: &str) -> Option<&str> {
        request.lines().find_map(|line| {
            let (name, value) = line.split_once(':')?;
            name.eq_ignore_ascii_case("authorization")
                .then_some(value.trim())
        })
    }

    /// How long a test waits for a stop that must not come. The reconciliation awaits the reply
    /// to a stop, so one it sent has reached its fake by the time it returns.
    const NO_STOP_WITHIN: Duration = Duration::from_secs(1);

    #[tokio::test]
    async fn the_first_reconciliation_stops_the_frpc_an_aborted_run_left_behind() {
        let ports = TempPorts::new();
        let _keyring = enrolled();
        let state = idle();
        let sidecar = DiskSidecar::new(&ports.dir);
        let (port, request) = serve_one(reply("200 OK", "")).await;
        left_behind(&sidecar, port, |_| {});

        let outcome = reconcile(
            &state,
            &sidecar,
            &ports.registry,
            Some(SERVER_TOML),
            ops_admin(),
            0,
        )
        .await
        .unwrap();

        let request = tokio::time::timeout(Duration::from_secs(5), request)
            .await
            .expect("no stop reached the frpc left behind")
            .unwrap();
        assert!(
            request.starts_with("POST /api/stop HTTP/1.1\r\n"),
            "{request}"
        );
        // base64("adminhelper:c0ffee")
        assert_eq!(
            authorization(&request),
            Some("Basic YWRtaW5oZWxwZXI6YzBmZmVl")
        );
        assert_eq!(outcome, RefreshOutcome::Started);
        // The old config went before the first write; what lies there is the new one.
        let run = sidecar.run_dir();
        assert_eq!(*sidecar.found.borrow(), [Vec::<String>::new()]);
        assert_eq!(names_in(run), ["identity", VISITOR_CONFIG]);
        let written = parse(&std::fs::read_to_string(run.join(VISITOR_CONFIG)).unwrap());
        let new_head = sidecar.inner.writes.borrow()[0].1.clone();
        assert_eq!(
            written["webServer"]["password"].as_str(),
            Some(new_head.password.as_str())
        );

        // Only the first reconciliation of a process stops: from then on the frpc behind the
        // head in the run dir is its own.
        let (port, request) = serve_one(reply("200 OK", "")).await;
        left_behind(&sidecar, port, |_| {});
        let since = lock(&state).generation;
        let outcome = reconcile(
            &state,
            &sidecar,
            &ports.registry,
            Some(SERVER_TOML),
            ops_admin(),
            since,
        )
        .await
        .unwrap();

        assert_eq!(outcome, RefreshOutcome::Unchanged);
        assert!(
            tokio::time::timeout(NO_STOP_WITHIN, request).await.is_err(),
            "a later reconciliation stopped a frpc"
        );
    }

    #[tokio::test]
    async fn the_first_reconciliation_stops_nothing_behind_a_head_that_is_not_the_desktops() {
        type Edit = fn(&mut toml::Table);
        let cases: [(&str, Edit); 3] = [
            ("webServer.addr 0.0.0.0", |config| {
                web_server(config).insert("addr".to_string(), "0.0.0.0".into());
            }),
            ("a password that is not hex", |config| {
                web_server(config).insert("password".to_string(), "not hex".into());
            }),
            ("no webServer", |config| {
                config.remove("webServer");
            }),
        ];
        for (case, edit) in cases {
            let ports = TempPorts::new();
            let _keyring = enrolled();
            let sidecar = DiskSidecar::new(&ports.dir);
            let (port, request) = serve_one(reply("200 OK", "")).await;
            left_behind(&sidecar, port, edit);

            let outcome = reconcile(
                &idle(),
                &sidecar,
                &ports.registry,
                Some(SERVER_TOML),
                ops_admin(),
                0,
            )
            .await
            .unwrap();

            assert_eq!(outcome, RefreshOutcome::Started, "{case}");
            assert_eq!(*sidecar.found.borrow(), [Vec::<String>::new()], "{case}");
            assert!(
                tokio::time::timeout(NO_STOP_WITHIN, request).await.is_err(),
                "{case}: a stop went out"
            );
        }
    }

    #[cfg(unix)]
    #[test]
    fn no_head_is_read_from_a_run_dir_that_is_a_symlink() {
        let ports = TempPorts::new();
        let sidecar = DiskSidecar::new(&ports.dir);
        left_behind(&sidecar, 4000, |_| {});
        assert!(super::head_left_behind(sidecar.run_dir()).is_some());

        let link = ports.dir.join("linked-run");
        std::os::unix::fs::symlink(sidecar.run_dir(), &link).unwrap();
        assert!(super::head_left_behind(&link).is_none());
    }

    #[tokio::test]
    async fn the_first_reconciliation_starts_when_the_frpc_left_behind_is_gone_or_refuses() {
        for case in ["no listener", "401"] {
            let ports = TempPorts::new();
            let _keyring = enrolled();
            let sidecar = DiskSidecar::new(&ports.dir);
            let (_reserved, port, served) = if case == "no listener" {
                let (reserved, port) = crate::test_tls::refused_port();
                (Some(reserved), port, None)
            } else {
                let (port, served) = serve_one(reply("401 Unauthorized", "")).await;
                (None, port, Some(served))
            };
            left_behind(&sidecar, port, |_| {});

            let outcome = reconcile(
                &idle(),
                &sidecar,
                &ports.registry,
                Some(SERVER_TOML),
                ops_admin(),
                0,
            )
            .await
            .unwrap();

            assert_eq!(outcome, RefreshOutcome::Started, "{case}");
            assert_eq!(*sidecar.found.borrow(), [Vec::<String>::new()], "{case}");
            assert_eq!(
                names_in(sidecar.run_dir()),
                ["identity", VISITOR_CONFIG],
                "{case}"
            );
            // The stop went out and was answered; a failure inside the server task shows here.
            if let Some(served) = served {
                tokio::time::timeout(Duration::from_secs(5), served)
                    .await
                    .expect("the 401 server task did not end")
                    .unwrap();
            }
        }
    }

    #[tokio::test]
    async fn stop_left_behind_returns_only_once_the_admin_port_is_closed() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let (close, closing) = tokio::sync::oneshot::channel::<()>();
        // Answers the stop, then keeps its port open like an frpc still shutting down, until the
        // test says it is gone; the listener drops with the task and frees the port.
        let server = tokio::spawn(async move {
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
            tcp.write_all(reply("200 OK", "").as_bytes()).await.unwrap();
            let _ = tcp.shutdown().await;
            tokio::select! {
                _ = async { loop { let _ = listener.accept().await; } } => {}
                _ = closing => {}
            }
        });

        let left = head(port, "c0ffee");
        let stopping = tokio::spawn(async move { stop_left_behind(&left).await });
        tokio::time::sleep(Duration::from_millis(500)).await;
        assert!(
            !stopping.is_finished(),
            "returned while the admin port still answered"
        );
        close.send(()).unwrap();
        tokio::time::timeout(Duration::from_secs(5), stopping)
            .await
            .expect("did not return after the admin port closed")
            .unwrap();
        server.await.unwrap();
    }

    #[tokio::test]
    async fn the_first_reconciliation_removes_the_runtime_files_of_versions_before_workspaces() {
        for case in ["removable", "visitor.toml that cannot go"] {
            let ports = TempPorts::new();
            let _keyring = enrolled();
            let base = &ports.dir;
            let sidecar = DiskSidecar::new(base);
            // What a version before workspaces left in the app data dir.
            let identity = base.join("identity");
            std::fs::create_dir_all(&identity).unwrap();
            for file in ["key.pem", "cert.pem", "ca.crt"] {
                std::fs::write(identity.join(file), "of an earlier version").unwrap();
            }
            if case == "removable" {
                std::fs::write(base.join(VISITOR_CONFIG), "of an earlier version").unwrap();
            } else {
                // No file to remove under that name: the removal fails on every platform.
                std::fs::create_dir_all(base.join(VISITOR_CONFIG).join("inside")).unwrap();
            }

            let outcome = reconcile(
                &idle(),
                &sidecar,
                &ports.registry,
                Some(SERVER_TOML),
                ops_admin(),
                0,
            )
            .await
            .unwrap();

            // The tunnel starts either way, from its own run dir.
            assert_eq!(outcome, RefreshOutcome::Started, "{case}");
            assert_eq!(
                names_in(sidecar.run_dir()),
                ["identity", VISITOR_CONFIG],
                "{case}"
            );
            let left = names_in(base);
            assert!(
                !left.iter().any(|name| name == "identity"),
                "{case}: {left:?}"
            );
            assert_eq!(
                left.iter().any(|name| name == VISITOR_CONFIG),
                case != "removable",
                "{case}: {left:?}"
            );
            assert!(left.iter().any(|name| name == "workspaces"), "{case}");
        }
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn a_run_dir_that_is_a_symlink_is_never_emptied() {
        let ports = TempPorts::new();
        let _keyring = enrolled();
        let sidecar = DiskSidecar::new(&ports.dir);
        let run = sidecar.run_dir();
        let elsewhere = ports.dir.join("elsewhere");
        std::fs::create_dir_all(&elsewhere).unwrap();
        std::fs::write(elsewhere.join("precious"), "").unwrap();
        std::fs::create_dir_all(run.parent().unwrap()).unwrap();
        std::os::unix::fs::symlink(&elsewhere, run).unwrap();

        let error = super::empty_run_dir(run).unwrap_err().to_string();
        assert!(error.contains(&run.display().to_string()), "{error}");
        // The first reconciliation does not start on it, and a stop leaves it be.
        let state = idle();
        assert!(reconcile(
            &state,
            &sidecar,
            &ports.registry,
            Some(SERVER_TOML),
            ops_admin(),
            0
        )
        .await
        .is_err());
        assert!(sidecar.inner.writes.borrow().is_empty());
        lock(&state).run_dir = Some(run.to_path_buf());
        assert!(stop_frpc(&state).is_err());

        assert_eq!(names_in(&elsewhere), ["precious"]);
    }

    /// Sign-ins other than [`ops_admin`]: the case, the server URL and the user.
    const OTHER_SIGN_INS: [(&str, &str, &str); 2] = [
        ("another user", SERVER_URL, "someone-else"),
        ("another server", "https://other.example.net", "ops-admin"),
    ];

    #[test]
    fn bindings_for_only_the_sign_in_frpc_runs_for() {
        let running = running(SERVER_TOML, head(1, "c0ffee"));
        let state = &running.state;

        assert_eq!(
            bindings_for(state, &ops_admin()),
            bindings_at(running.locals)
        );
        // The certificate choice is no part of who is signed in where.
        let self_signed = SignedIn {
            allow_self_signed: true,
            ..ops_admin()
        };
        assert_eq!(
            bindings_for(state, &self_signed),
            bindings_at(running.locals)
        );
        for (case, server_url, username) in OTHER_SIGN_INS {
            let other = signed_in(server_url, username);
            assert!(bindings_for(state, &other).is_empty(), "{case}");
        }
        // The status shows the running frpc all the same.
        assert_eq!(tunnel_status(state).bindings, bindings_at(running.locals));

        assert!(bindings_for(&idle(), &ops_admin()).is_empty());
        lock(state).retire();
        assert!(bindings_for(state, &ops_admin()).is_empty());
    }

    #[tokio::test]
    async fn refresh_restarts_for_a_bundle_of_another_sign_in() {
        for (case, server_url, username) in OTHER_SIGN_INS {
            // For the sign-in frpc runs for, the first reloads and the second changes nothing.
            for next in [changed_visitor(), SERVER_TOML.to_string()] {
                // A reload would get through: only the other sign-in makes it a restart.
                let (port, _request) = serve_one(reply("200 OK", "")).await;
                let running = running(SERVER_TOML, head(port, "c0ffee"));
                let state = &running.state;
                let sidecar = FakeSidecar::default();

                let outcome = reconcile(
                    state,
                    &sidecar,
                    &running.ports.registry,
                    Some(&next),
                    signed_in(server_url, username),
                    1,
                )
                .await
                .unwrap();

                assert_eq!(outcome, RefreshOutcome::Restarted, "{case}");
                let writes = sidecar.writes.borrow();
                assert_eq!(writes.len(), 1, "{case}: the restart's write, no reload's");
                assert_ne!(writes[0].1.password, "c0ffee", "{case}: a new head");
                assert_eq!(writes[0].0, written_at(&next, running.locals), "{case}");
                assert_eq!(sidecar.spawns.get(), 1, "{case}");
                assert_eq!(
                    lock(state).generation,
                    3,
                    "{case}: retired to 2, spawned as 3"
                );
                assert!(bindings_for(state, &ops_admin()).is_empty(), "{case}");
                assert_eq!(
                    bindings_for(state, &signed_in(server_url, username)),
                    bindings_at(running.locals),
                    "{case}"
                );
            }
        }
    }

    #[test]
    fn refresh_status_lists_the_applied_visitors() {
        assert_eq!(
            visitor_names(&parse(SERVER_TOML)),
            ["db-visitor", "web-visitor"]
        );
        assert!(visitor_names(&parse("serverAddr = \"f\"\n")).is_empty());

        let running = running(SERVER_TOML, head(1, "c0ffee"));
        let status = tunnel_status(&running.state);
        assert_eq!(status.visitors, ["db-visitor", "web-visitor"]);
        assert_eq!(status.bindings, bindings_at(running.locals));
        let idle = idle();
        assert!(tunnel_status(&idle).visitors.is_empty());
        assert!(tunnel_status(&idle).bindings.is_empty());
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
                {
                    let mut values = parse(values);
                    rewrite_identity_paths(&mut values, identity_dir);
                    values
                },
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
        assert!(none.bundle.is_none());
        assert_eq!(none.refused, None);

        let body = r#"{"toml":"serverAddr = \"f\""}"#;
        let (port, _request) = serve_one(reply("200 OK", body)).await;
        let bundle = bundle_from(get(port).await.unwrap()).await.unwrap();
        assert_eq!(bundle.refused, None);
        assert_eq!(bundle.bundle.expect("a bundle").toml, "serverAddr = \"f\"");

        let (port, _request) = serve_one(reply("500 Internal Server Error", "")).await;
        assert!(bundle_from(get(port).await.unwrap()).await.is_err());
    }

    #[tokio::test]
    async fn refresh_bundle_reply_403_is_no_tunnels_and_names_the_refusal() {
        let client = reqwest::Client::builder().no_proxy().build().unwrap();
        let (port, _request) = serve_one(reply("403 Forbidden", "")).await;
        let response = client
            .get(format!("http://127.0.0.1:{port}/"))
            .send()
            .await
            .unwrap();
        let refused = bundle_from(response).await.unwrap();
        assert!(refused.bundle.is_none());
        assert_eq!(refused.refused, Some(403));
    }

    #[tokio::test]
    async fn refresh_bundle_of_a_session_gone_meanwhile_is_refused() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};

        // Who signs in while the bundle is on its way; `None` signs out.
        for next in [Some("ops-admin"), Some("someone-else"), None] {
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let server = format!("http://127.0.0.1:{}", listener.local_addr().unwrap().port());
            let session = SessionState::default();
            session
                .set(
                    server.clone(),
                    "access".to_string(),
                    "refresh".to_string(),
                    "ops-admin".to_string(),
                    false,
                )
                .await;

            let serve = async {
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
                match next {
                    Some(user) => {
                        session
                            .set(
                                server.clone(),
                                "next".to_string(),
                                "next-refresh".to_string(),
                                user.to_string(),
                                false,
                            )
                            .await
                    }
                    None => drop(session.take().await),
                }
                let body = r#"{"toml":"serverAddr = \"f\""}"#;
                tcp.write_all(reply("200 OK", body).as_bytes())
                    .await
                    .unwrap();
                let _ = tcp.shutdown().await;
            };
            let (fetched, ()) = tokio::join!(fetch_visitor_bundle(&session), serve);

            match next {
                // The same user signed in again: the tunnels are still theirs.
                Some("ops-admin") => {
                    let (reply, who) = fetched.expect("the bundle");
                    assert_eq!(reply.bundle.expect("a bundle").toml, "serverAddr = \"f\"");
                    assert_eq!(
                        (who.server_url.as_str(), who.username.as_str()),
                        (server.as_str(), "ops-admin")
                    );
                }
                _ => assert!(fetched.is_err(), "{next:?}"),
            }
        }
    }

    #[cfg(windows)]
    #[test]
    fn closing_the_job_ends_the_process_in_it_and_no_other() {
        use std::process::{Command, Stdio};
        use std::time::Instant;

        let ping = || {
            Command::new("ping")
                .args(["-n", "30", "127.0.0.1"])
                .stdout(Stdio::null())
                .spawn()
                .expect("ping starts")
        };
        let job = super::kill_on_close_job().expect("job object");
        // Both start after the job exists: one that inherited its handle would keep it open.
        let mut assigned = ping();
        let mut other = ping();
        super::assign_to_job(&job, assigned.id()).expect("assigned to the job");
        drop(job);

        let deadline = Instant::now() + Duration::from_secs(5);
        let ended = loop {
            if assigned.try_wait().expect("try_wait").is_some() {
                break true;
            }
            if Instant::now() >= deadline {
                break false;
            }
            std::thread::sleep(Duration::from_millis(50));
        };
        // Counter-check: closing the job ends nothing outside it.
        let other_runs = other.try_wait().expect("try_wait").is_none();
        for child in [&mut assigned, &mut other] {
            let _ = child.kill();
            let _ = child.wait();
        }
        assert!(
            ended,
            "the process in the job still ran 5 s after the job closed"
        );
        assert!(other_runs, "a process outside the job ended with it");
    }
}
