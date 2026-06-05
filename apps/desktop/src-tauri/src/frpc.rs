// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::collections::HashMap;
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
    pki: HashMap<String, String>,
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

/// Write visitor bundle (TOML + PKI files) to the app data directory.
/// Rewrites relative PKI paths in the TOML to absolute paths.
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

    // Write PKI files if present
    let pki_dir = data_dir.join("pki");
    if !bundle.pki.is_empty() {
        std::fs::create_dir_all(&pki_dir)?;
        for (filename, content) in &bundle.pki {
            // The server controls these filenames; reject anything that is not a
            // plain file name before joining, or it could escape pki_dir (zip-slip).
            crate::validation::validate_pki_filename(filename)?;
            let file_path = pki_dir.join(filename);
            // Write private keys (.key) restrictively; certs may stay 0644.
            if filename.ends_with(".key") {
                write_secret(&file_path, content.as_bytes())?;
            } else {
                std::fs::write(&file_path, content)?;
            }
        }
    }

    // Fail early if TOML references TLS certs but server sent no PKI bundle
    if bundle.pki.is_empty() && bundle.toml.contains("[transport.tls]") {
        return Err(AppError::Validation(
            "Server hat kein PKI-Bundle geliefert. Bitte CA auf dem Server generieren (FRP → PKI → CA generieren).".to_string(),
        ));
    }

    // Always rewrite relative pki/ paths to absolute paths in the TOML
    let abs_pki = pki_dir.to_string_lossy();
    let toml_content = bundle.toml.replace("\"pki/", &format!("\"{abs_pki}/"));
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
    tauri::async_runtime::spawn(async move {
        use tauri_plugin_shell::process::CommandEvent;
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    eprintln!("[frpc stdout] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Stderr(line) => {
                    eprintln!("[frpc stderr] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Terminated(payload) => {
                    eprintln!("[frpc] Prozess beendet: {:?}", payload);
                    let _ = app_handle.emit("frpc-terminated", payload.code);
                }
                CommandEvent::Error(err) => {
                    eprintln!("[frpc error] {}", err);
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

/// Full tunnel start flow: fetch bundle, write config + PKI, start frpc.
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
