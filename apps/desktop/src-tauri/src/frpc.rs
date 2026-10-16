// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

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
use crate::models::TunnelStatus;

pub type FrpcState = Arc<Mutex<FrpcProcess>>;

pub fn new_frpc_state() -> FrpcState {
    Arc::new(Mutex::new(FrpcProcess::new()))
}

pub struct FrpcProcess {
    child: Option<tauri_plugin_shell::process::CommandChild>,
    visitor_name: Option<String>,
    connected_since: Option<String>,
    // Bumped on every spawn and every stop so a log task's Terminated handler only reconciles
    // state if it is still the current process (4.29, R-0389).
    generation: u64,
}

impl FrpcProcess {
    pub fn new() -> Self {
        Self {
            child: None,
            visitor_name: None,
            connected_since: None,
            generation: 0,
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
        self.child.take()
    }
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
/// dir; `write_visitor_bundle` swaps it for the absolute on-disk path. Must stay
/// in lockstep with `_VISITOR_IDENTITY_DIR` in the server's config_generator.py —
/// an explicit token instead of a fragile `"identity/` substring rewrite.
const IDENTITY_DIR_PLACEHOLDER: &str = "{{IDENTITY_DIR}}";

/// What a tunnel start says without an enrolled identity. The login does not enroll
/// (ADR 0003): the device needs a one-time token from an admin first.
const NO_IDENTITY_HINT: &str = "No mTLS certificate on this device — enroll it with a one-time \
     enrollment token from your administrator first, then start the tunnel.";

/// Replace the server's `{{IDENTITY_DIR}}` placeholder in a visitor TOML with the
/// absolute identity dir the desktop exported its mTLS material into.
fn rewrite_identity_paths(toml: &str, abs_identity_dir: &str) -> String {
    toml.replace(IDENTITY_DIR_PLACEHOLDER, abs_identity_dir)
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

/// Write the visitor TOML to the app data dir and export the enrolled identity it
/// references (F2). The server ships only the TOML; the desktop supplies its own
/// mTLS identity for the visitor.
/// Allow-list the server-supplied visitor TOML before frpc executes it. Only the keys
/// our own server-side generate_visitor_toml emits are permitted, so a compromised or
/// malicious server cannot inject arbitrary frpc config — notably a `[[proxies]]` block
/// or a visitor plugin (static_file/http_proxy) that would expose local files/network
/// through the frpc process (3.59).
///
/// Keep TOP_KEYS/VISITOR_KEYS in sync with the server's `generate_visitor_toml`
/// (apps/server/app/modules/frp/config_generator.py): adding a server-side key without
/// listing it here would reject real tunnels. auth/transport sub-keys are intentionally
/// not deep-validated — they configure TLS/token, not a resource-exposing plugin.
fn validate_visitor_toml(toml_str: &str) -> Result<(), AppError> {
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

    let value: toml::Value = toml::from_str(toml_str)
        .map_err(|e| AppError::Validation(format!("visitor.toml nicht parsebar: {e}")))?;
    let table = value
        .as_table()
        .ok_or_else(|| AppError::Validation("visitor.toml: kein TOML-Table".to_string()))?;

    for key in table.keys() {
        if !TOP_KEYS.contains(&key.as_str()) {
            return Err(AppError::Validation(format!(
                "visitor.toml: unerlaubter Top-Level-Key '{key}'"
            )));
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
        }
    }
    Ok(())
}

// Not called outside the tests yet: the reconciliation (refresh_tunnel) takes these over.
/// User of frpc's local admin API; the generated password is the secret.
#[cfg_attr(not(test), allow(dead_code))]
const ADMIN_API_USER: &str = "adminhelper";

/// The config frpc runs: the allow-listed server TOML behind the desktop's local head.
/// `loginFailExit = false` keeps frpc retrying while frps is unreachable (frp's default ends it
/// after the first failed login); `webServer.*` opens frpc's admin API on loopback for the
/// reload. The head goes on only after `validate_visitor_toml`, so the allow-list stays as it is
/// and still rejects a server that sends `webServer` or `loginFailExit` itself. It stands before
/// every table header, so its keys land in the root. The password is never optional — without
/// user and password frp serves the admin API, `GET /api/config` with the frps token and every
/// `secretKey` included, to every local process. `password` goes in unescaped, so it is hex.
#[cfg_attr(not(test), allow(dead_code))]
fn with_local_head(server_toml: &str, port: u16, password: &str) -> Result<String, AppError> {
    validate_visitor_toml(server_toml)?;
    Ok(format!(
        "loginFailExit = false\n\
         webServer.addr = \"127.0.0.1\"\n\
         webServer.port = {port}\n\
         webServer.user = \"{ADMIN_API_USER}\"\n\
         webServer.password = \"{password}\"\n\
         \n\
         {server_toml}"
    ))
}

/// What a reconciliation does with the server TOML it fetched.
#[cfg_attr(not(test), allow(dead_code))]
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
#[cfg_attr(not(test), allow(dead_code))]
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
#[cfg_attr(not(test), allow(dead_code))]
fn common_part(config: &toml::Value) -> Option<toml::Table> {
    let mut root = config.as_table()?.clone();
    root.remove("visitors");
    Some(root)
}

fn write_visitor_bundle(
    app: &tauri::AppHandle,
    bundle: &VisitorBundle,
) -> Result<PathBuf, AppError> {
    let data_dir = app.path().app_data_dir().map_err(|e| {
        AppError::Io(std::io::Error::new(
            std::io::ErrorKind::NotFound,
            e.to_string(),
        ))
    })?;
    std::fs::create_dir_all(&data_dir)?;

    // Reject a server-supplied config that isn't a plain STCP visitor before writing
    // and executing it (3.59).
    validate_visitor_toml(&bundle.toml)?;

    let identity_dir = data_dir.join("identity");
    if bundle.toml.contains("[transport.tls]") {
        export_identity(&identity_dir)?;
    }

    let abs_identity = identity_dir.to_string_lossy();
    let toml_content = rewrite_identity_paths(&bundle.toml, &abs_identity);
    let config_path = data_dir.join("visitor.toml");
    // visitor.toml contains the frp auth token -> 0600 on Unix.
    write_secret(&config_path, toml_content.as_bytes())?;
    Ok(config_path)
}

/// Start frpc as a sidecar process with the given config path.
pub fn start_frpc(
    app: &tauri::AppHandle,
    config_path: &std::path::Path,
    state: &FrpcState,
    visitor_name: String,
) -> Result<(), AppError> {
    // Recover a poisoned lock: the guarded state is a small Option triple a panic
    // leaves consistent, and mapping poison to an error would wedge the tunnel
    // (start/stop fail forever) while tunnel_status already recovers (2.84).
    let mut guard = state.lock().unwrap_or_else(|e| e.into_inner());

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
    }
}

/// Full tunnel start flow: fetch bundle, write config + identity, start frpc.
pub async fn start_tunnel(
    app: tauri::AppHandle,
    state: FrpcState,
    server_url: &str,
    token: &str,
    username: &str,
    allow_self_signed: bool,
) -> Result<TunnelStatus, AppError> {
    // No tunnels still fails the start as before; the reconciliation will stop instead.
    let bundle = fetch_visitor_bundle(server_url, token, allow_self_signed)
        .await?
        .ok_or_else(|| {
            AppError::Validation("Visitor-Bundle konnte nicht geladen werden".to_string())
        })?;
    let config_path = write_visitor_bundle(&app, &bundle)?;
    start_frpc(&app, &config_path, &state, username.to_string())?;
    Ok(tunnel_status(&state))
}

#[cfg(test)]
mod tests {
    use super::{
        carries_bundle, plan_refresh, rewrite_identity_paths, validate_visitor_toml,
        with_local_head, FrpcProcess, RefreshPlan, NO_IDENTITY_HINT,
    };

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

    /// SERVER_TOML with the first `from` replaced; a fixture without `from` fails the test
    /// instead of silently comparing two equal configs.
    fn changed(from: &str, to: &str) -> toml::Value {
        assert!(SERVER_TOML.contains(from), "fixture lacks {from:?}");
        parse(&SERVER_TOML.replacen(from, to, 1))
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
}
