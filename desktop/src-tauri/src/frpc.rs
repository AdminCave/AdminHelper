use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use serde::Deserialize;
use tauri::{Emitter, Manager};
use tauri_plugin_shell::ShellExt;

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
struct VisitorInfo {
    id: String,
    name: String,
}

struct FoundVisitor {
    id: String,
    name: String,
}

/// Fetch list of visitors from the server and find the one matching the user.
async fn find_visitor(server_url: &str, token: &str, username: &str) -> Result<FoundVisitor, AppError> {
    let response = auth::authenticated_get(server_url, token, "/api/frp/visitors").await?;

    if !response.status().is_success() {
        return Err(AppError::Validation(
            "Visitor-Liste konnte nicht geladen werden".to_string(),
        ));
    }

    let visitors: Vec<VisitorInfo> = response.json().await?;

    // Match by convention: visitor name is "tech-<username>"
    let expected = format!("tech-{username}");
    if let Some(v) = visitors.iter().find(|v| v.name == expected) {
        return Ok(FoundVisitor { id: v.id.clone(), name: v.name.clone() });
    }

    // Fallback: first visitor (single-user setups)
    visitors
        .into_iter()
        .next()
        .map(|v| FoundVisitor { id: v.id, name: v.name })
        .ok_or_else(|| AppError::Validation("Kein Visitor fuer diesen Benutzer gefunden".to_string()))
}

/// Fetch the visitor TOML configuration from the server.
async fn fetch_visitor_config(
    server_url: &str,
    token: &str,
    visitor_id: &str,
) -> Result<String, AppError> {
    let path = format!("/api/frp/generate/visitor-toml?visitor_id={}", visitor_id);
    let response = auth::authenticated_get(server_url, token, &path).await?;

    if !response.status().is_success() {
        return Err(AppError::Validation(
            "Visitor-Konfiguration konnte nicht geladen werden".to_string(),
        ));
    }

    // API returns raw TOML text, not JSON
    let toml_text = response.text().await.map_err(|e| AppError::Network(e))?;
    Ok(toml_text)
}

/// Write visitor.toml to the app data directory.
fn write_visitor_config(app: &tauri::AppHandle, toml_content: &str) -> Result<PathBuf, AppError> {
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| AppError::Io(std::io::Error::new(std::io::ErrorKind::NotFound, e.to_string())))?;
    std::fs::create_dir_all(&data_dir)?;

    let config_path = data_dir.join("visitor.toml");
    std::fs::write(&config_path, toml_content)?;
    Ok(config_path)
}

/// Start frpc as a sidecar process with the given config path.
pub fn start_frpc(
    app: &tauri::AppHandle,
    config_path: &std::path::Path,
    state: &FrpcState,
    visitor_name: String,
) -> Result<(), AppError> {
    let mut guard = state.lock().map_err(|e| AppError::Connection(e.to_string()))?;

    if guard.child.is_some() {
        return Err(AppError::Validation("frpc laeuft bereits".to_string()));
    }

    let config_str = config_path
        .to_str()
        .ok_or_else(|| AppError::Validation("Ungültiger Konfigurationspfad".to_string()))?;

    let shell = app.shell();
    let command = shell.sidecar("frpc").map_err(|e| {
        AppError::Connection(format!("frpc-Sidecar nicht gefunden: {e}"))
    })?;

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
    let mut guard = state.lock().map_err(|e| AppError::Connection(e.to_string()))?;
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

/// Full tunnel start flow: find visitor, fetch config, write it, start frpc.
pub async fn start_tunnel(
    app: tauri::AppHandle,
    state: FrpcState,
    server_url: &str,
    token: &str,
    username: &str,
) -> Result<TunnelStatus, AppError> {
    let visitor = find_visitor(server_url, token, username).await?;
    let toml_content = fetch_visitor_config(server_url, token, &visitor.id).await?;
    let visitor_name = visitor.name;
    let config_path = write_visitor_config(&app, &toml_content)?;
    start_frpc(&app, &config_path, &state, visitor_name)?;
    Ok(tunnel_status(&state))
}
