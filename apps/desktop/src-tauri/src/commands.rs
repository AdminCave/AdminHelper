// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::path::Path;
use std::time::Duration;

use tauri::State;

use crate::ansible;
use crate::auth;
use crate::connection;
use crate::enrollment;
use crate::error::AppError;
use crate::frpc;
use crate::models::{
    AuthSession, ClientInfo, Connection, DeviceIdentity, PasswordState, RdpOptions, Settings,
    TunnelRefresh, TunnelStatus, VisitorBinding,
};
use crate::password;
use crate::port_registry::PortRegistry;
use crate::proxy;
use crate::session::SessionState;
use crate::storage;
use crate::sync;
use crate::tofu;
use crate::tunnel;

/// Resolve the "allow self-signed certs" flag: an explicit per-call override, else
/// the persisted setting (default false on a missing/corrupt settings.json). The
/// single source so the default semantics can't drift across the commands. Only for
/// the calls without a session (login, enrollment with a one-time token, sync from a
/// URL); every call through the session takes the choice its sign-in made.
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

/// Checks whether the server certificate is valid. Returns true only if the
/// server is reachable with a publicly-trusted cert; any error (self-signed/
/// invalid cert, but also DNS/timeout/connection failures) returns false.
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

/// SHA-256 fingerprint of the CA pinned at enrollment (the access
/// intermediate). The provisioning tab embeds it as the agent's `--ca-fp`, so
/// the agent's first contact is verified instead of TOFU. None until enrolled.
#[tauri::command]
pub fn pinned_ca_fingerprint() -> Option<String> {
    enrollment::pinned_ca_fingerprint()
}

/// Name (CN) and expiry of this device's enrolled certificate, for the identity
/// line in the settings. None until enrolled; an error when the stored
/// certificate is unreadable — the UI then shows a fixed text, never the error.
#[tauri::command]
pub fn device_identity() -> Result<Option<DeviceIdentity>, AppError> {
    enrollment::device_identity()
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
/// the old pin. The user must log in / re-enroll afterwards. The identity is
/// revoked at the server first, where it can be (R-0224); the outcome tells the
/// UI whether that happened.
#[tauri::command]
pub async fn reset_device_identity(
    server_url: String,
) -> Result<enrollment::ResetOutcome, AppError> {
    let outcome = enrollment::reset_identity(&server_url).await;
    tofu::forget_pin(&server_url);
    Ok(outcome)
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

/// Enroll a long-lived browser cert (A5c) at the signed-in server, write it as a
/// password-protected PKCS12 (.p12) to the `dest_path` the user picked in the
/// frontend's save dialog, and return the path for them to import into their
/// browser's cert store. Does not affect the desktop's own enrolled identity.
#[tauri::command]
pub async fn export_browser_p12(
    session: State<'_, SessionState>,
    password: String,
    dest_path: String,
) -> Result<String, AppError> {
    let der = enrollment::export_browser_p12(session.inner(), &password).await?;
    storage::write_browser_p12(&dest_path, &der)
}

/// Generic API proxy: forwards requests to the signed-in server via reqwest.
/// Works around WebView TLS restrictions for self-signed certs.
#[tauri::command]
pub async fn api_proxy(
    session: State<'_, SessionState>,
    method: String,
    path: String,
    body: Option<String>,
) -> Result<serde_json::Value, AppError> {
    proxy::forward(session.inner(), &method, &path, body).await
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
    let server_url = storage::load_settings(&app).ok().and_then(|s| s.server_url);
    sync::sync_connections(app, url, allow_self_signed, server_url).await
}

#[tauri::command]
pub fn save_connections(
    app: tauri::AppHandle,
    connections: Vec<Connection>,
) -> Result<(), AppError> {
    storage::save_connections(&app, &connections)
}

/// Deadline around the blocking connect work. open_connection runs the RDP auth check
/// (xfreerdp +auth-only) and preflight synchronously; a hung NLA handshake after TCP accept
/// could otherwise block the whole webview forever. spawn_blocking moves it off the async
/// thread so the UI stays responsive, and the timeout turns an eternal freeze into an error
/// the user can act on (4.3). tauri::async_runtime::spawn_blocking — the crate's tokio only
/// enables the "time" feature, not "rt", so tokio::task::spawn_blocking isn't available.
const OPEN_CONNECTION_TIMEOUT: Duration = Duration::from_secs(30);

async fn run_with_deadline<F>(timeout: Duration, work: F) -> Result<(), AppError>
where
    F: FnOnce() -> Result<(), AppError> + Send + 'static,
{
    let handle = tauri::async_runtime::spawn_blocking(work);
    match tokio::time::timeout(timeout, handle).await {
        Ok(joined) => joined
            .map_err(|e| AppError::Connection(format!("Verbindungsaufbau abgebrochen: {e}")))?,
        Err(_) => Err(AppError::Connection(
            "Verbindungsaufbau: Zeitueberschreitung (Server nicht erreichbar oder haengt)".into(),
        )),
    }
}

/// Rejects `connection` if it goes to a loopback port of another workspace's tunnel
/// ([`tunnel::reject_foreign_port`]), by the port map in the app data dir `base` and the
/// workspace of this process; the launcher has none and opens nothing. The map's file lock may
/// wait: on a blocking thread only.
fn reject_foreign_port(
    base: &Path,
    connection: &Connection,
    bindings: &[VisitorBinding],
) -> Result<(), AppError> {
    let owner = crate::workspace::current()?.id.to_string();
    let others = PortRegistry::new(base).local_ports_of_others(&owner)?;
    tunnel::reject_foreign_port(connection, &others, bindings)
}

/// Opens nothing at a loopback port of another workspace's tunnel; one a visitor of the frpc that
/// runs for the current sign-in listens on is this workspace's own.
#[tauri::command]
pub async fn open_connection(
    app: tauri::AppHandle,
    state: State<'_, frpc::FrpcState>,
    session: State<'_, SessionState>,
    connection: Connection,
    password: Option<String>,
    client: Option<ClientInfo>,
    correlation_id: Option<String>,
) -> Result<(), AppError> {
    let bindings = match session.current().await {
        Some(now) => frpc::bindings_for(state.inner(), &now.signed_in()),
        None => Vec::new(),
    };
    run_with_deadline(OPEN_CONNECTION_TIMEOUT, move || {
        reject_foreign_port(&storage::app_data_dir(&app)?, &connection, &bindings)?;
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
    })
    .await
}

/// A stored password opens only the target Rust resolves the credential connection (without one,
/// the opened connection) to, with the tunnel mappings and server connections the session fetched
/// (not ones the webview sends) and the bindings of the frpc that runs for that sign-in, all read
/// at one moment as the connection opens. Without a session there are none of them. A target at
/// a loopback port of another workspace's tunnel is refused before the password loads.
#[tauri::command]
pub async fn open_connection_stored(
    app: tauri::AppHandle,
    state: State<'_, frpc::FrpcState>,
    session: State<'_, SessionState>,
    connection: Connection,
    credential_connection: Option<Connection>,
    client: Option<ClientInfo>,
    correlation_id: Option<String>,
) -> Result<(), AppError> {
    let (tunnels, connections, bindings) = match session.current().await {
        Some(now) => {
            let bindings = frpc::bindings_for(state.inner(), &now.signed_in());
            (now.tunnels, now.connections, bindings)
        }
        None => Default::default(),
    };
    run_with_deadline(OPEN_CONNECTION_TIMEOUT, move || {
        reject_foreign_port(&storage::app_data_dir(&app)?, &connection, &bindings)?;
        let settings = storage::load_settings(&app)?;
        let cid = correlation_id.unwrap_or_default();
        let rdp = rdp_options(&settings);
        let credential = connection::CredentialConnection {
            connection: credential_connection.as_ref(),
            tunnels: &tunnels,
            connections: &connections,
            bindings: &bindings,
        };
        connection::open_connection_stored(
            &app,
            &connection,
            credential,
            client.as_ref(),
            rdp,
            settings.language.as_deref(),
            &cid,
        )
    })
    .await
}

#[tauri::command]
pub fn password_state(connection: Connection) -> Result<PasswordState, AppError> {
    password::password_state(&connection)
}

#[tauri::command]
pub fn save_password(
    app: tauri::AppHandle,
    connection: Connection,
    password: String,
) -> Result<(), AppError> {
    password::save_password(&storage::app_data_dir(&app)?, &connection, &password)
}

#[tauri::command]
pub fn delete_password(app: tauri::AppHandle, connection: Connection) -> Result<(), AppError> {
    password::delete_password(&storage::app_data_dir(&app)?, &connection)
}

#[tauri::command]
pub async fn login(
    app: tauri::AppHandle,
    session: State<'_, SessionState>,
    server_url: String,
    username: String,
    password: String,
    allow_self_signed: Option<bool>,
) -> Result<AuthSession, AppError> {
    let self_signed = self_signed_setting(&app, allow_self_signed);
    auth::login(
        session.inner(),
        &server_url,
        &username,
        &password,
        self_signed,
    )
    .await
}

#[tauri::command]
pub async fn logout(session: State<'_, SessionState>) -> Result<(), AppError> {
    auth::logout(session.inner()).await
}

#[tauri::command]
pub async fn fetch_connections_jwt(
    app: tauri::AppHandle,
    session: State<'_, SessionState>,
) -> Result<Vec<Connection>, AppError> {
    sync::fetch_connections_jwt(app, session.inner()).await
}

/// The reconciliation of `refresh_tunnel`, reporting only the status.
#[tauri::command]
pub async fn start_tunnel(
    app: tauri::AppHandle,
    state: State<'_, frpc::FrpcState>,
    lock: State<'_, frpc::RefreshLock>,
    session: State<'_, SessionState>,
) -> Result<TunnelStatus, AppError> {
    let refresh = refresh_tunnel(app, state, lock, session).await?;
    Ok(refresh.status)
}

#[tauri::command]
pub async fn refresh_tunnel(
    app: tauri::AppHandle,
    state: State<'_, frpc::FrpcState>,
    lock: State<'_, frpc::RefreshLock>,
    session: State<'_, SessionState>,
) -> Result<TunnelRefresh, AppError> {
    let frpc_state = state.inner().clone();
    frpc::refresh_tunnel(app, frpc_state, lock.inner(), session.inner()).await
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
    session: State<'_, SessionState>,
) -> Result<(), AppError> {
    let stream_state = state.inner().clone();
    crate::notifications::start(app, stream_state, session.inner()).await
}

#[tauri::command]
pub fn stop_notification_stream(state: State<'_, crate::notifications::StreamState>) {
    crate::notifications::stop(state.inner());
}

#[tauri::command]
pub async fn fetch_tunnels(
    session: State<'_, SessionState>,
) -> Result<Vec<tunnel::TunnelMapping>, AppError> {
    tunnel::fetch_tunnels(session.inner()).await
}

/// Resolves against where the visitors of the frpc that runs for the current sign-in listen;
/// while none runs for it, and without a session, a tunnel target stays as it is. A target that
/// ends at a loopback port of another workspace's tunnel is an error.
#[tauri::command]
pub async fn resolve_connection(
    app: tauri::AppHandle,
    state: State<'_, frpc::FrpcState>,
    session: State<'_, SessionState>,
    connection: Connection,
    tunnels: Vec<tunnel::TunnelMapping>,
) -> Result<tunnel::ResolvedConnection, AppError> {
    let bindings = match session.current().await {
        Some(now) => frpc::bindings_for(state.inner(), &now.signed_in()),
        None => Vec::new(),
    };
    let resolved = tunnel::resolve_connection(&connection, &tunnels, &bindings);
    let target = resolved.connection.clone();
    run_with_deadline(OPEN_CONNECTION_TIMEOUT, move || {
        reject_foreign_port(&storage::app_data_dir(&app)?, &target, &bindings)
    })
    .await?;
    Ok(resolved)
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

#[cfg(test)]
mod tests {
    use super::{reject_foreign_port, run_with_deadline};
    use crate::error::AppError;
    use crate::models::{Connection, ConnectionKind};
    use crate::port_registry::PortRegistry;
    use crate::workspace;
    use std::time::Duration;

    #[tokio::test]
    async fn run_with_deadline_returns_ok_for_fast_work() {
        assert!(run_with_deadline(Duration::from_secs(5), || Ok(()))
            .await
            .is_ok());
    }

    #[tokio::test]
    async fn run_with_deadline_maps_a_hung_task_to_a_timeout_error() {
        // 4.3: a blocking task that overruns the deadline surfaces a Connection error (the
        // user gets a message, not a frozen webview) instead of hanging.
        let r = run_with_deadline(Duration::from_millis(50), || {
            std::thread::sleep(Duration::from_millis(500));
            Ok(())
        })
        .await;
        assert!(matches!(r, Err(AppError::Connection(_))));
    }

    #[tokio::test]
    async fn run_with_deadline_passes_through_work_errors() {
        let r = run_with_deadline(Duration::from_secs(5), || {
            Err(AppError::Connection("boom".into()))
        })
        .await;
        assert!(matches!(r, Err(AppError::Connection(_))));
    }

    /// `127.0.0.1`:`port` over SSH.
    fn loopback(port: u16) -> Connection {
        Connection {
            id: "c1".to_string(),
            name: "Test".to_string(),
            kind: ConnectionKind::Ssh,
            host: Some("127.0.0.1".to_string()),
            port: Some(port),
            username: None,
            domain: None,
            key_path: None,
            url: None,
            notes: None,
            tags: Vec::new(),
            trust_cert: false,
            last_used: None,
            server_id: None,
        }
    }

    /// The workspace `id` on this thread while the guard lives.
    fn entered(id: &str) -> workspace::EnteredWorkspace {
        workspace::enter(workspace::Workspace {
            id: workspace::WorkspaceId::parse(id).unwrap(),
            name: id.to_string(),
            legacy_keys: false,
        })
    }

    #[test]
    fn foreign_port_check_reads_the_port_map_as_the_workspace_of_this_process() {
        let dir =
            std::env::temp_dir().join(format!("ah-commands-foreign-port-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        PortRegistry::new(&dir).seed("w-0000000b", &[("db-visitor", 6000, 23005)]);

        // The launcher has no workspace and so opens nothing.
        let no_workspace = workspace::current().unwrap_err().to_string();
        let refused = reject_foreign_port(&dir, &loopback(23005), &[]);
        assert_eq!(refused.unwrap_err().to_string(), no_workspace);
        {
            let _other = entered("w-0000000a");
            let refused = reject_foreign_port(&dir, &loopback(23005), &[]).unwrap_err();
            assert!(
                refused
                    .to_string()
                    .starts_with("port 23005 on this machine"),
                "{refused}"
            );
            assert!(reject_foreign_port(&dir, &loopback(23006), &[]).is_ok());
        }
        {
            let _owner = entered("w-0000000b");
            assert!(reject_foreign_port(&dir, &loopback(23005), &[]).is_ok());
        }
        let _ = std::fs::remove_dir_all(&dir);
    }
}
