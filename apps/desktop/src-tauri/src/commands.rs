// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use tauri::State;

use crate::ansible;
use crate::auth;
use crate::connection;
use crate::enrollment;
use crate::error::AppError;
use crate::frpc;
use crate::models::{
    AuthSession, ClientInfo, Connection, PasswordState, RdpOptions, Settings, TunnelStatus,
};
use crate::password;
use crate::proxy;
use crate::storage;
use crate::sync;
use crate::tofu;
use crate::tunnel;

/// Resolve the "allow self-signed certs" flag: an explicit per-call override, else
/// the persisted setting (default false on a missing/corrupt settings.json). The
/// single source so the default semantics can't drift across the many commands.
fn self_signed_setting(app: &tauri::AppHandle, explicit: Option<bool>) -> bool {
    explicit.unwrap_or_else(|| {
        storage::load_settings(app)
            .map(|s| s.allow_self_signed_certs)
            .unwrap_or(false)
    })
}

/// Build the RDP launch options from the persisted settings — the borrow of
/// custom_size ties the returned RdpOptions to `settings`.
fn rdp_options(settings: &Settings) -> RdpOptions<'_> {
    RdpOptions {
        scaling_mode: settings.rdp_scaling_mode,
        window_mode: settings.rdp_window_mode,
        custom_size: settings.rdp_custom_size.as_deref(),
        performance_profile: settings.rdp_performance_profile,
    }
}

/// Checks whether the server certificate is valid. Returns true if valid,
/// false if self-signed/invalid.
#[tauri::command]
pub async fn check_server_cert(server_url: String) -> Result<bool, AppError> {
    proxy::check_server_cert(&server_url).await
}

/// Build a redacted diagnostics report (version, OS, recent log tail) for a bug
/// report and return the path of the written file.
#[tauri::command]
pub fn generate_diagnostics(app: tauri::AppHandle) -> Result<String, AppError> {
    crate::diagnostics::generate(&app)
}

/// Forget the pinned (TOFU) certificate for a server, so the next connection
/// re-pins on first use. For recovering from a legitimate certificate rotation
/// after the pin-mismatch error.
#[tauri::command]
pub fn reset_server_cert_pin(server_url: String) -> Result<(), AppError> {
    tofu::forget_pin(&server_url);
    Ok(())
}

/// Whether this device currently holds an enrolled mTLS identity. Drives the
/// visibility of the "reset device identity" action in the settings UI.
#[tauri::command]
pub fn is_device_enrolled() -> bool {
    enrollment::is_enrolled()
}

/// Reset this device's enrolled mTLS identity AND forget the TOFU pin for the
/// given server — the recovery path after a server reinstall / PKI re-creation.
/// Both are stale at once: while enrolled, `build_client` always uses the mTLS
/// `enrolled_client` (CA-pin), so dropping the identity makes the next connection
/// fall back to the self-signed/TOFU (or public-CA) path; clearing the stale leaf
/// pin in the same step lets that fallback re-pin instead of being rejected by
/// the old pin. The user must log in / re-enroll afterwards.
#[tauri::command]
pub fn reset_device_identity(server_url: String) -> Result<(), AppError> {
    enrollment::clear_identity();
    tofu::forget_pin(&server_url);
    Ok(())
}

/// Enroll this device for mTLS: mint an access-scoped token (using the session
/// JWT), generate an on-device key + CSR, and fetch + store the client cert from
/// the ca-issuer (A5). The cert is presented on later requests by build_client
/// (next increment). Idempotent from the user's view — re-running re-enrolls.
#[tauri::command]
pub async fn enroll_device(
    app: tauri::AppHandle,
    server_url: String,
    token: String,
    allow_self_signed: Option<bool>,
) -> Result<(), AppError> {
    let self_signed = self_signed_setting(&app, allow_self_signed);
    enrollment::enroll(&server_url, &token, self_signed).await
}

/// Decoupled enrollment (ADR 0003): enroll using a one-time token an admin minted
/// out-of-band and handed over, WITHOUT a prior login. Lets a brand-new client
/// obtain its cert under enforced mTLS, where it cannot reach the login on :443.
#[tauri::command]
pub async fn enroll_with_token(
    app: tauri::AppHandle,
    server_url: String,
    token: String,
    allow_self_signed: Option<bool>,
) -> Result<(), AppError> {
    let self_signed = self_signed_setting(&app, allow_self_signed);
    enrollment::enroll_with_token(&server_url, &token, self_signed).await
}

/// Enroll a long-lived browser cert (A5c), write it as a password-protected
/// PKCS12 (.p12) to the `dest_path` the user picked in the frontend's save
/// dialog, and return the path for them to import into their browser's cert
/// store. Does not affect the desktop's own enrolled identity.
#[tauri::command]
pub async fn export_browser_p12(
    app: tauri::AppHandle,
    server_url: String,
    token: String,
    password: String,
    dest_path: String,
    allow_self_signed: Option<bool>,
) -> Result<String, AppError> {
    let self_signed = self_signed_setting(&app, allow_self_signed);
    let der = enrollment::export_browser_p12(&server_url, &token, &password, self_signed).await?;
    storage::write_browser_p12(&dest_path, &der)
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
    let self_signed = self_signed_setting(&app, allow_self_signed);
    proxy::forward(&server_url, &token, &method, &path, body, self_signed).await
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
    let allow_self_signed = self_signed_setting(&app, None);
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
    let rdp = rdp_options(&settings);
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
    let rdp = rdp_options(&settings);
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
    let self_signed = self_signed_setting(&app, allow_self_signed);
    auth::login(&server_url, &username, &password, self_signed).await
}

#[tauri::command]
pub async fn logout(app: tauri::AppHandle) -> Result<(), AppError> {
    let allow_self_signed = self_signed_setting(&app, None);
    auth::logout(allow_self_signed).await
}

#[tauri::command]
pub async fn fetch_connections_jwt(
    app: tauri::AppHandle,
    server_url: String,
    token: String,
) -> Result<Vec<Connection>, AppError> {
    let allow_self_signed = self_signed_setting(&app, None);
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
    let allow_self_signed = self_signed_setting(&app, None);
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
pub async fn start_notification_stream(
    app: tauri::AppHandle,
    state: State<'_, crate::notifications::StreamState>,
    server_url: String,
    token: String,
) -> Result<(), AppError> {
    let allow_self_signed = self_signed_setting(&app, None);
    let stream_state = state.inner().clone();
    crate::notifications::start(app, stream_state, server_url, token, allow_self_signed).await
}

#[tauri::command]
pub fn stop_notification_stream(state: State<'_, crate::notifications::StreamState>) {
    crate::notifications::stop(state.inner());
}

#[tauri::command]
pub async fn fetch_tunnels(
    app: tauri::AppHandle,
    server_url: String,
    token: String,
) -> Result<Vec<tunnel::TunnelMapping>, AppError> {
    let allow_self_signed = self_signed_setting(&app, None);
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
