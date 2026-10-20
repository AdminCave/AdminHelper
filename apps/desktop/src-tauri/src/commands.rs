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
use crate::launcher::{self, Spawner};
use crate::models::{
    AuthSession, ClientInfo, Connection, DeviceIdentity, PasswordState, RdpOptions, Settings,
    TunnelRefresh, TunnelStatus, VisitorBinding, WorkspaceContext, WorkspaceDraft, WorkspaceList,
};
use crate::password;
use crate::port_registry::PortRegistry;
use crate::proxy;
use crate::session::SessionState;
use crate::storage;
use crate::sync;
use crate::tofu;
use crate::tunnel;
use crate::workspace::{self, Side, WorkspaceId};

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

/// The URL a sign-in or an enrollment of the workspace of this process goes to, in the app data
/// dir `base`, `sent` being the one the webview names ([`workspace::sign_in_url`]); for a
/// sign-in as `username`, only while no other workspace signs in to that server as that user
/// ([`workspace::check_sign_in_once`]). The launcher signs in nowhere.
fn sign_in_target(base: &Path, sent: &str, username: Option<&str>) -> Result<String, AppError> {
    let ws = workspace::current()?;
    let meta = workspace::load_meta(&ws.id, &ws.data_dir(base))?;
    let url = workspace::sign_in_url(&meta, sent)?;
    if let Some(username) = username {
        workspace::check_sign_in_once(&ws.id, &url, username, &workspace::metas(base)?)?;
    }
    Ok(url)
}

/// Decoupled enrollment (ADR 0003): enroll using a one-time token an admin minted
/// out-of-band and handed over, WITHOUT a prior login. Lets a brand-new client
/// obtain its cert under enforced mTLS, where it cannot reach the login on :443.
/// Only at the server of this workspace ([`sign_in_target`]).
#[tauri::command]
pub async fn enroll_with_token(
    app: tauri::AppHandle,
    server_url: String,
    token: String,
    allow_self_signed: Option<bool>,
) -> Result<(), AppError> {
    let server_url = sign_in_target(&storage::app_data_dir(&app)?, &server_url, None)?;
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

/// What the webview reads is the base against which `save_settings` tells what it changed.
#[tauri::command]
pub fn load_settings(app: tauri::AppHandle) -> Result<Settings, AppError> {
    storage::load_settings_for_webview(&app)
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

/// Signs in at the server of this workspace, as a user no other workspace signs in to it as
/// ([`sign_in_target`]); both are checked before the password leaves.
#[tauri::command]
pub async fn login(
    app: tauri::AppHandle,
    session: State<'_, SessionState>,
    server_url: String,
    username: String,
    password: String,
    allow_self_signed: Option<bool>,
) -> Result<AuthSession, AppError> {
    let server_url = sign_in_target(&storage::app_data_dir(&app)?, &server_url, Some(&username))?;
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

// ── Workspaces (R-0431): the launcher manages them, a workspace brings the launcher up ──

/// Fails unless this process is the one `side` names ([`workspace::check_side`]).
fn only(side: Side) -> Result<(), AppError> {
    workspace::check_side(side, workspace::current().ok().as_ref())
}

/// Runs `work`, which may wait (for the lock of a workspace, the registry, a process it
/// started), on a blocking thread: neither the main thread, where a command without `async`
/// runs, nor an async worker waits with it.
async fn blocking<T, F>(work: F) -> Result<T, AppError>
where
    T: Send + 'static,
    F: FnOnce() -> Result<T, AppError> + Send + 'static,
{
    tauri::async_runtime::spawn_blocking(work)
        .await
        .map_err(|e| {
            AppError::Io(std::io::Error::other(format!(
                "the command did not finish: {e}"
            )))
        })?
}

/// Which process the webview talks to: the launcher, or the workspace this process serves.
#[tauri::command]
pub fn workspace_context(app: tauri::AppHandle) -> Result<WorkspaceContext, AppError> {
    workspace::context(&storage::app_data_dir(&app)?)
}

fn list_workspaces_in(base: &Path) -> Result<WorkspaceList, AppError> {
    only(Side::Launcher)?;
    launcher::list(base)
}

/// Launcher only: the workspaces the picker lists ([`launcher::list`]).
#[tauri::command]
pub async fn list_workspaces(app: tauri::AppHandle) -> Result<WorkspaceList, AppError> {
    let base = storage::app_data_dir(&app)?;
    blocking(move || list_workspaces_in(&base)).await
}

fn save_workspace_in(base: &Path, draft: &WorkspaceDraft) -> Result<WorkspaceId, AppError> {
    only(Side::Launcher)?;
    launcher::save(base, draft)
}

/// Launcher only: makes the workspace `draft` describes, or edits the closed one it names, and
/// gives its id ([`launcher::save`]; an edit waits up to 2 s for the lock of the workspace).
#[tauri::command]
pub async fn save_workspace(
    app: tauri::AppHandle,
    draft: WorkspaceDraft,
) -> Result<WorkspaceId, AppError> {
    let base = storage::app_data_dir(&app)?;
    blocking(move || save_workspace_in(&base, &draft)).await
}

fn delete_workspace_in(
    base: &Path,
    id: &str,
    spawner: &impl Spawner,
) -> Result<enrollment::ResetOutcome, AppError> {
    only(Side::Launcher)?;
    launcher::delete(base, &WorkspaceId::parse(id)?, spawner)
}

/// Launcher only: deletes the closed workspace `id` through its purge and gives how its device
/// identity went ([`launcher::delete`]; waits up to 120 s for the purge).
#[tauri::command]
pub async fn delete_workspace(
    app: tauri::AppHandle,
    id: String,
) -> Result<enrollment::ResetOutcome, AppError> {
    let base = storage::app_data_dir(&app)?;
    blocking(move || delete_workspace_in(&base, &id, &launcher::AppSpawner::new()?)).await
}

fn open_workspace_in(base: &Path, id: &str, spawner: &impl Spawner) -> Result<(), AppError> {
    only(Side::Launcher)?;
    launcher::open(base, &WorkspaceId::parse(id)?, spawner)
}

/// Launcher only: opens the workspace `id` in a process of its own and waits up to 10 s until
/// that process holds it ([`launcher::open`]); then the launcher ends.
#[tauri::command]
pub async fn open_workspace(app: tauri::AppHandle, id: String) -> Result<(), AppError> {
    let base = storage::app_data_dir(&app)?;
    blocking(move || open_workspace_in(&base, &id, &launcher::AppSpawner::new()?)).await?;
    app.exit(0);
    Ok(())
}

fn open_launcher_with(spawner: &impl Spawner) -> Result<(), AppError> {
    only(Side::Workspace)?;
    launcher::open_launcher(spawner)
}

/// Workspace only: "Workspaces…" starts the launcher, or brings up the one that runs
/// ([`launcher::open_launcher`]).
#[tauri::command]
pub fn open_launcher() -> Result<(), AppError> {
    open_launcher_with(&launcher::AppSpawner::new()?)
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
    use super::{
        delete_workspace_in, list_workspaces_in, open_launcher_with, open_workspace_in,
        reject_foreign_port, run_with_deadline, save_workspace_in, sign_in_target,
    };
    use crate::error::AppError;
    use crate::launcher::{Spawned, Spawner};
    use crate::models::{Connection, ConnectionKind, SyncMode, WorkspaceDraft};
    use crate::port_registry::PortRegistry;
    use crate::workspace::{self, Meta, Registry, RegistryEntry, PALETTE};
    use std::cell::RefCell;
    use std::path::{Path, PathBuf};
    use std::process::ExitStatus;
    use std::time::Duration;
    use std::{fs, io};

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

    // ── Workspaces: which process a command runs in ──

    /// A directory of its own for one test case under the system temp dir, gone with the guard.
    struct Scratch(PathBuf);

    impl Scratch {
        fn new(case: &str) -> Self {
            let dir =
                std::env::temp_dir().join(format!("ah-commands-{case}-{}", std::process::id()));
            let _ = fs::remove_dir_all(&dir);
            fs::create_dir_all(&dir).unwrap();
            Self(dir)
        }
    }

    impl Drop for Scratch {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    /// A program that runs on and holds no lock.
    struct Running;

    impl Spawned for Running {
        fn try_wait(&mut self) -> io::Result<Option<ExitStatus>> {
            Ok(None)
        }
    }

    /// Notes the arguments of every start.
    #[derive(Default)]
    struct Starts(RefCell<Vec<Vec<String>>>);

    impl Spawner for Starts {
        type Child = Running;

        fn spawn(&self, args: &[&str]) -> io::Result<Running> {
            self.0
                .borrow_mut()
                .push(args.iter().map(|arg| arg.to_string()).collect());
            Ok(Running)
        }
    }

    /// Lays out `base` with the closed server workspace `w-0a1b2c3d`, as the launcher lists it.
    fn one_workspace(base: &Path) {
        Meta {
            kind: SyncMode::Server,
            name: "Kunde A".to_string(),
            color: PALETTE[0].to_string(),
            url: Some("https://ah.example.com".to_string()),
            interval_minutes: 1,
            allow_self_signed_certs: false,
            last_username: None,
            legacy_keys: false,
        }
        .store(&base.join("workspaces").join("w-0a1b2c3d"))
        .unwrap();
        Registry {
            workspaces: vec![RegistryEntry {
                id: workspace::WorkspaceId::parse("w-0a1b2c3d").unwrap(),
            }],
            last_used: None,
            migrated_notice: false,
        }
        .store(base)
        .unwrap();
    }

    fn new_draft() -> WorkspaceDraft {
        WorkspaceDraft {
            id: None,
            kind: SyncMode::Local,
            name: "Lokal".to_string(),
            color: PALETTE[1].to_string(),
            url: None,
        }
    }

    /// The names in `base/workspaces`, sorted.
    fn workspace_dirs(base: &Path) -> Vec<String> {
        let mut names: Vec<String> = fs::read_dir(base.join("workspaces"))
            .unwrap()
            .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
            .collect();
        names.sort();
        names
    }

    fn assert_refused<T: std::fmt::Debug>(result: Result<T, AppError>, says: &str, case: &str) {
        assert!(
            matches!(&result, Err(AppError::Validation(msg)) if msg.contains(says)),
            "{case}: {result:?}"
        );
    }

    #[test]
    fn the_commands_of_the_launcher_refuse_to_run_in_a_workspace() {
        let scratch = Scratch::new("launcher-only");
        let base = &scratch.0;
        one_workspace(base);
        let registry = fs::read(base.join("workspaces.json")).unwrap();
        let starts = Starts::default();
        {
            let _in_a_workspace = entered("standard");
            let only = "only the launcher";
            assert_refused(list_workspaces_in(base), only, "list");
            assert_refused(save_workspace_in(base, &new_draft()), only, "save");
            assert_refused(
                delete_workspace_in(base, "w-0a1b2c3d", &starts),
                only,
                "delete",
            );
            assert_refused(open_workspace_in(base, "w-0a1b2c3d", &starts), only, "open");
        }
        assert_eq!(
            starts.0.borrow().len(),
            0,
            "a refused command started a process"
        );
        assert_eq!(fs::read(base.join("workspaces.json")).unwrap(), registry);
        assert_eq!(workspace_dirs(base), ["w-0a1b2c3d"]);

        // The same commands in the launcher.
        let list = list_workspaces_in(base).unwrap();
        assert_eq!(list.workspaces.len(), 1);
        assert_eq!(list.workspaces[0].id.to_string(), "w-0a1b2c3d");
        let made = save_workspace_in(base, &new_draft()).unwrap().to_string();
        let mut dirs = vec![made, "w-0a1b2c3d".to_string()];
        dirs.sort();
        assert_eq!(workspace_dirs(base), dirs);
    }

    #[test]
    fn open_launcher_refuses_to_run_in_the_launcher() {
        let starts = Starts::default();
        assert_refused(
            open_launcher_with(&starts),
            "only the process of a workspace",
            "open_launcher",
        );
        assert_eq!(
            starts.0.borrow().len(),
            0,
            "the launcher started a launcher"
        );

        let _in_a_workspace = entered("standard");
        open_launcher_with(&starts).unwrap();
        assert_eq!(*starts.0.borrow(), [Vec::<String>::new()]);
    }

    #[test]
    fn the_commands_of_the_launcher_refuse_a_bad_workspace_id_and_start_nothing() {
        let scratch = Scratch::new("bad-id");
        let base = &scratch.0;
        one_workspace(base);
        let registry = fs::read(base.join("workspaces.json")).unwrap();
        let starts = Starts::default();
        for id in ["", "../w-0a1b2c3d", "W-0A1B2C3D", "w-0a1b2c3d/..", "äöü"] {
            assert_refused(
                delete_workspace_in(base, id, &starts),
                "invalid workspace id",
                id,
            );
            assert_refused(
                open_workspace_in(base, id, &starts),
                "invalid workspace id",
                id,
            );
        }
        assert_eq!(starts.0.borrow().len(), 0);
        assert_eq!(fs::read(base.join("workspaces.json")).unwrap(), registry);
        assert_eq!(workspace_dirs(base), ["w-0a1b2c3d"]);
    }

    #[test]
    fn a_workspace_draft_crosses_the_bridge_under_its_wire_names_and_with_a_valid_id_only() {
        let draft: WorkspaceDraft = serde_json::from_value(serde_json::json!({
            "kind": "server",
            "name": "Kunde A",
            "color": PALETTE[2],
            "url": "https://ah.example.com",
        }))
        .unwrap();
        assert!(draft.id.is_none());
        assert_eq!(draft.kind, SyncMode::Server);
        assert_eq!(draft.url.as_deref(), Some("https://ah.example.com"));

        let edit: WorkspaceDraft = serde_json::from_value(serde_json::json!({
            "id": "w-0a1b2c3d",
            "kind": "local",
            "name": "Lokal",
            "color": PALETTE[2],
            "url": null,
        }))
        .unwrap();
        assert_eq!(
            edit.id.map(|id| id.to_string()).as_deref(),
            Some("w-0a1b2c3d")
        );

        let bad = serde_json::from_value::<WorkspaceDraft>(serde_json::json!({
            "id": "../standard",
            "kind": "local",
            "name": "Lokal",
            "color": PALETTE[2],
        }));
        assert!(bad.is_err(), "{bad:?}");
    }

    // ── Where the workspace of this process signs in ──

    /// Lays out `base` with the server workspaces `workspaces`: id, name, URL and the user it
    /// last signed in as.
    fn server_workspaces(base: &Path, workspaces: &[(&str, &str, Option<&str>, Option<&str>)]) {
        for (id, name, url, user) in workspaces {
            Meta {
                kind: SyncMode::Server,
                name: name.to_string(),
                color: PALETTE[0].to_string(),
                url: url.map(String::from),
                interval_minutes: 1,
                allow_self_signed_certs: false,
                last_username: user.map(String::from),
                legacy_keys: false,
            }
            .store(&base.join("workspaces").join(id))
            .unwrap();
        }
        Registry {
            workspaces: workspaces
                .iter()
                .map(|(id, ..)| RegistryEntry {
                    id: workspace::WorkspaceId::parse(id).unwrap(),
                })
                .collect(),
            last_used: None,
            migrated_notice: false,
        }
        .store(base)
        .unwrap();
    }

    #[test]
    fn login_binding_signs_in_at_the_server_of_the_workspace_once_per_user() {
        let scratch = Scratch::new("sign-in");
        let base = &scratch.0;
        server_workspaces(
            base,
            &[
                (
                    "w-0000000a",
                    "Kunde A",
                    Some("https://ah.example.com"),
                    Some("admin"),
                ),
                (
                    "w-0000000b",
                    "Kunde B",
                    Some("https://ah.example.com/"),
                    None,
                ),
                ("w-0000000c", "Neu", None, None),
            ],
        );

        // The launcher signs in nowhere.
        let no_workspace = workspace::current().unwrap_err().to_string();
        for username in [Some("ops"), None] {
            let refused = sign_in_target(base, "https://ah.example.com", username).unwrap_err();
            assert_eq!(refused.to_string(), no_workspace);
        }
        {
            let _b = entered("w-0000000b");
            // Its own server, at the URL it keeps.
            for username in [Some("ops"), None] {
                assert_eq!(
                    sign_in_target(base, "https://AH.example.com:443", username).unwrap(),
                    "https://ah.example.com/"
                );
            }
            // Another server, for a sign-in and an enrollment alike.
            for username in [Some("ops"), None] {
                assert_refused(
                    sign_in_target(base, "https://other.example.com", username),
                    "this workspace belongs to the server https://ah.example.com/",
                    &format!("{username:?}"),
                );
            }
            // The user another workspace signs in to that server as: refused for a sign-in.
            assert_refused(
                sign_in_target(base, "https://ah.example.com", Some("Admin")),
                "the workspace \"Kunde A\" signs in to this server as this user",
                "same user",
            );
        }
        {
            let _a = entered("w-0000000a");
            assert_eq!(
                sign_in_target(base, "https://ah.example.com", Some("admin")).unwrap(),
                "https://ah.example.com"
            );
        }
        {
            // Without a URL of its own, the one sent; but not as that user at that server.
            let _c = entered("w-0000000c");
            assert_eq!(
                sign_in_target(base, " https://other.example.com ", Some("admin")).unwrap(),
                "https://other.example.com"
            );
            assert_refused(
                sign_in_target(base, "https://ah.example.com:443/", Some("admin")),
                "\"Kunde A\"",
                "first URL",
            );
        }
    }
}
