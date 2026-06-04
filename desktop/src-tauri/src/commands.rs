// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use tauri::State;

use crate::ansible;
use crate::auth;
use crate::connection;
use crate::error::AppError;
use crate::frpc;
use crate::models::{
    AuthSession, ClientInfo, Connection, PasswordState, RdpOptions, Settings, TunnelStatus,
};
use crate::password;
use crate::storage;
use crate::sync;
use crate::tunnel;

/// Checks whether the server certificate is valid. Returns true if valid,
/// false if self-signed/invalid.
#[tauri::command]
pub async fn check_server_cert(server_url: String) -> Result<bool, AppError> {
    let client = reqwest::Client::builder()
        .danger_accept_invalid_certs(false)
        .build()
        .map_err(AppError::from)?;

    let url = format!("{}/api/auth/me", server_url.trim_end_matches('/'));
    match client.get(&url).send().await {
        Ok(_) => Ok(true),
        Err(e) if e.is_connect() => Ok(false), // TLS/connection error
        Err(_) => Ok(false),
    }
}

/// Generic API proxy: forwards requests to the server via reqwest.
/// Works around WebView TLS restrictions for self-signed certs.
#[tauri::command]
pub async fn api_proxy(
    app: tauri::AppHandle,
    server_url: String,
    token: String,
    method: String,
    path: String,
    body: Option<String>,
    allow_self_signed: Option<bool>,
) -> Result<serde_json::Value, AppError> {
    let self_signed = allow_self_signed.unwrap_or_else(|| {
        storage::load_settings(&app)
            .map(|s| s.allow_self_signed_certs)
            .unwrap_or(false)
    });
    let client = auth::build_client(&server_url, self_signed)?;
    let url = format!("{}{}", server_url.trim_end_matches('/'), path);

    let mut req = match method.as_str() {
        "POST" => client.post(&url),
        "PUT" => client.put(&url),
        "DELETE" => client.delete(&url),
        _ => client.get(&url),
    };

    req = req.header("Authorization", format!("Bearer {token}"));

    if let Some(b) = body {
        req = req.header("Content-Type", "application/json").body(b);
    }

    let response = req.send().await?;
    let status = response.status();

    if status == reqwest::StatusCode::NO_CONTENT {
        return Ok(serde_json::Value::Null);
    }

    if !status.is_success() {
        let text = response.text().await.unwrap_or_default();
        return Err(AppError::Validation(format!(
            "HTTP {}: {}",
            status.as_u16(),
            text
        )));
    }

    let value: serde_json::Value = response.json().await.unwrap_or(serde_json::Value::Null);
    Ok(value)
}

#[tauri::command]
pub fn load_connections(app: tauri::AppHandle) -> Result<Vec<Connection>, AppError> {
    storage::load_connections(&app)
}

#[tauri::command]
pub fn load_settings(app: tauri::AppHandle) -> Result<Settings, AppError> {
    storage::load_settings(&app)
}

#[tauri::command]
pub fn save_settings(app: tauri::AppHandle, settings: Settings) -> Result<(), AppError> {
    storage::save_settings(&app, &settings)
}

#[tauri::command]
pub async fn sync_connections(
    app: tauri::AppHandle,
    url: String,
) -> Result<Vec<Connection>, AppError> {
    let allow_self_signed = storage::load_settings(&app)
        .map(|s| s.allow_self_signed_certs)
        .unwrap_or(false);
    sync::sync_connections(app, url, allow_self_signed).await
}

#[tauri::command]
pub fn save_connections(
    app: tauri::AppHandle,
    connections: Vec<Connection>,
) -> Result<(), AppError> {
    storage::save_connections(&app, &connections)
}

#[tauri::command]
pub fn open_connection(
    app: tauri::AppHandle,
    connection: Connection,
    password: Option<String>,
    client: Option<ClientInfo>,
    correlation_id: Option<String>,
) -> Result<(), AppError> {
    let settings = storage::load_settings(&app)?;
    let cid = correlation_id.unwrap_or_default();
    let rdp = RdpOptions {
        scaling_mode: settings.rdp_scaling_mode,
        window_mode: settings.rdp_window_mode,
        custom_size: settings.rdp_custom_size.as_deref(),
        performance_profile: settings.rdp_performance_profile,
    };
    connection::open_connection(
        &connection,
        password.as_deref(),
        client.as_ref(),
        rdp,
        settings.language.as_deref(),
        &cid,
        &app,
    )
}

#[tauri::command]
pub fn open_connection_stored(
    app: tauri::AppHandle,
    connection: Connection,
    client: Option<ClientInfo>,
    correlation_id: Option<String>,
) -> Result<(), AppError> {
    let settings = storage::load_settings(&app)?;
    let cid = correlation_id.unwrap_or_default();
    let rdp = RdpOptions {
        scaling_mode: settings.rdp_scaling_mode,
        window_mode: settings.rdp_window_mode,
        custom_size: settings.rdp_custom_size.as_deref(),
        performance_profile: settings.rdp_performance_profile,
    };
    connection::open_connection_stored(
        &app,
        &connection,
        client.as_ref(),
        rdp,
        settings.language.as_deref(),
        &cid,
    )
}

#[tauri::command]
pub fn password_state(connection: Connection) -> Result<PasswordState, AppError> {
    password::password_state(&connection)
}

#[tauri::command]
pub fn save_password(connection: Connection, password: String) -> Result<(), AppError> {
    password::save_password(&connection, &password)
}

#[tauri::command]
pub fn delete_password(connection: Connection) -> Result<(), AppError> {
    password::delete_password(&connection)
}

#[tauri::command]
pub async fn login(
    app: tauri::AppHandle,
    server_url: String,
    username: String,
    password: String,
    allow_self_signed: Option<bool>,
) -> Result<AuthSession, AppError> {
    let self_signed = allow_self_signed.unwrap_or_else(|| {
        storage::load_settings(&app)
            .map(|s| s.allow_self_signed_certs)
            .unwrap_or(false)
    });
    auth::login(&server_url, &username, &password, self_signed).await
}

#[tauri::command]
pub async fn check_session(app: tauri::AppHandle) -> Result<Option<AuthSession>, AppError> {
    let allow_self_signed = storage::load_settings(&app)
        .map(|s| s.allow_self_signed_certs)
        .unwrap_or(false);
    auth::check_session(allow_self_signed).await
}

#[tauri::command]
pub async fn logout(app: tauri::AppHandle) -> Result<(), AppError> {
    let allow_self_signed = storage::load_settings(&app)
        .map(|s| s.allow_self_signed_certs)
        .unwrap_or(false);
    auth::logout(allow_self_signed).await
}

#[tauri::command]
pub async fn fetch_connections_jwt(
    app: tauri::AppHandle,
    server_url: String,
    token: String,
) -> Result<Vec<Connection>, AppError> {
    let allow_self_signed = storage::load_settings(&app)
        .map(|s| s.allow_self_signed_certs)
        .unwrap_or(false);
    sync::fetch_connections_jwt(app, &server_url, &token, allow_self_signed).await
}

#[tauri::command]
pub async fn start_tunnel(
    app: tauri::AppHandle,
    state: State<'_, frpc::FrpcState>,
    server_url: String,
    token: String,
    username: String,
) -> Result<TunnelStatus, AppError> {
    let allow_self_signed = storage::load_settings(&app)
        .map(|s| s.allow_self_signed_certs)
        .unwrap_or(false);
    let frpc_state = state.inner().clone();
    frpc::start_tunnel(
        app,
        frpc_state,
        &server_url,
        &token,
        &username,
        allow_self_signed,
    )
    .await
}

#[tauri::command]
pub fn stop_tunnel(state: State<'_, frpc::FrpcState>) -> Result<(), AppError> {
    frpc::stop_frpc(state.inner())
}

#[tauri::command]
pub fn tunnel_status(state: State<'_, frpc::FrpcState>) -> TunnelStatus {
    frpc::tunnel_status(state.inner())
}

#[tauri::command]
pub async fn fetch_tunnels(
    app: tauri::AppHandle,
    server_url: String,
    token: String,
) -> Result<Vec<tunnel::TunnelMapping>, AppError> {
    let allow_self_signed = storage::load_settings(&app)
        .map(|s| s.allow_self_signed_certs)
        .unwrap_or(false);
    tunnel::fetch_tunnels(&server_url, &token, allow_self_signed).await
}

#[tauri::command]
pub fn resolve_connection(
    connection: Connection,
    tunnels: Vec<tunnel::TunnelMapping>,
) -> tunnel::ResolvedConnection {
    tunnel::resolve_connection(&connection, &tunnels)
}

#[tauri::command]
pub fn ansible_generate_inventory(
    servers: Vec<ansible::AnsibleTarget>,
) -> Result<String, AppError> {
    ansible::generate_inventory(&servers)
}

#[tauri::command]
pub fn ansible_write_playbook(filename: String, content: String) -> Result<String, AppError> {
    ansible::write_playbook_temp(&filename, &content)
}

#[tauri::command]
pub fn ansible_launch(inventory_path: String, playbook_path: String) -> Result<(), AppError> {
    ansible::launch_ansible(&inventory_path, &playbook_path)
}
