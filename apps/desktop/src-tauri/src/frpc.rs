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
}

impl FrpcProcess {
    pub fn new() -> Self {
        Self {
            child: None,
            visitor_name: None,
            connected_since: None,
        }
    }
}

#[derive(Deserialize)]
struct VisitorBundle {
    toml: String,
    // The server no longer ships PKI material (F2/F3: D6 — the server holds no
    // signing capability). The visitor presents the desktop's own enrolled
    // identity instead; any `pki` field the server still sends is ignored.
}

/// Fetch the visitor bundle (TOML + PKI) from the server.
async fn fetch_visitor_bundle(
    server_url: &str,
    token: &str,
    allow_self_signed: bool,
) -> Result<VisitorBundle, AppError> {
    let path = "/api/frp/generate/visitor-bundle";
    let response = auth::authenticated_get(server_url, token, path, allow_self_signed).await?;

    if !response.status().is_success() {
        return Err(AppError::Validation(
            "Visitor-Bundle konnte nicht geladen werden".to_string(),
        ));
    }

    let bundle: VisitorBundle = response.json().await.map_err(AppError::Network)?;
    Ok(bundle)
}

/// The placeholder the server's visitor generator emits in place of the identity
/// dir; `write_visitor_bundle` swaps it for the absolute on-disk path. Must stay
/// in lockstep with `_VISITOR_IDENTITY_DIR` in the server's config_generator.py —
/// an explicit token instead of a fragile `"identity/` substring rewrite.
const IDENTITY_DIR_PLACEHOLDER: &str = "{{IDENTITY_DIR}}";

/// Replace the server's `{{IDENTITY_DIR}}` placeholder in a visitor TOML with the
/// absolute identity dir the desktop exported its mTLS material into.
fn rewrite_identity_paths(toml: &str, abs_identity_dir: &str) -> String {
    toml.replace(IDENTITY_DIR_PLACEHOLDER, abs_identity_dir)
}

/// Export the enrolled identity (key 0600 + cert + CA) into `identity_dir` so the
/// frpc sidecar can read it as files. The visitor presents the desktop's own
/// access cert (F2); the server no longer mints one.
fn export_identity(identity_dir: &Path) -> Result<(), AppError> {
    let (key_pem, cert_pem, ca_pem) = crate::enrollment::identity_pems().ok_or_else(|| {
        AppError::Validation(
            "Kein mTLS-Zertifikat vorhanden — bitte zuerst am Server anmelden (Enrollment), \
             dann den Tunnel starten."
                .to_string(),
        )
    })?;
    std::fs::create_dir_all(identity_dir)?;
    write_secret(&identity_dir.join("key.pem"), key_pem.as_bytes())?;
    std::fs::write(identity_dir.join("cert.pem"), cert_pem.as_bytes())?;
    std::fs::write(identity_dir.join("ca.crt"), ca_pem.as_bytes())?;
    Ok(())
}

/// Write the visitor TOML to the app data dir and export the enrolled identity it
/// references (F2). The server ships only the TOML; the desktop supplies its own
/// mTLS identity for the visitor.
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
    let mut guard = state
        .lock()
        .map_err(|e| AppError::Connection(e.to_string()))?;

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
                    if let Ok(mut guard) = state_for_task.lock() {
                        guard.child = None;
                        guard.visitor_name = None;
                        guard.connected_since = None;
                    }
                    let _ = app_handle.emit("frpc-terminated", payload.code);
                }
                CommandEvent::Error(err) => {
                    log::error!("[frpc error] {}", err);
                    let _ = app_handle.emit("frpc-error", err);
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
    let mut guard = state
        .lock()
        .map_err(|e| AppError::Connection(e.to_string()))?;
    if let Some(child) = guard.child.take() {
        let _ = child.kill();
    }
    guard.visitor_name = None;
    guard.connected_since = None;
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
    let bundle = fetch_visitor_bundle(server_url, token, allow_self_signed).await?;
    let config_path = write_visitor_bundle(&app, &bundle)?;
    start_frpc(&app, &config_path, &state, username.to_string())?;
    Ok(tunnel_status(&state))
}

#[cfg(test)]
mod tests {
    use super::rewrite_identity_paths;

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
}
