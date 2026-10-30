// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::future::Future;
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
use crate::workspace::{self, Meta, Side, WorkspaceId};

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
/// Only the server of this workspace ([`sign_in_target`]).
#[tauri::command]
pub async fn check_server_cert(
    app: tauri::AppHandle,
    server_url: String,
) -> Result<bool, AppError> {
    check_server_cert_in(&storage::app_data_dir(&app)?, &server_url).await
}

/// [`check_server_cert`] in the app data dir `base`.
async fn check_server_cert_in(base: &Path, sent: &str) -> Result<bool, AppError> {
    proxy::check_server_cert(&sign_in_target(base, sent, None)?).await
}

/// Build a redacted diagnostics report (version, OS, recent log tail) for a bug
/// report and return the path of the written file.
#[tauri::command]
pub fn generate_diagnostics(app: tauri::AppHandle) -> Result<String, AppError> {
    crate::diagnostics::generate(&app)
}

/// Forget the pinned (TOFU) certificate for a server, so the next connection
/// re-pins on first use. For recovering from a legitimate certificate rotation
/// after the pin-mismatch error. The pins belong to the device, not to a
/// workspace: only the server or sync source of this workspace
/// ([`workspace::own_url`]), never that of another one.
#[tauri::command]
pub async fn reset_server_cert_pin(
    app: tauri::AppHandle,
    server_url: String,
) -> Result<(), AppError> {
    let base = storage::app_data_dir(&app)?;
    blocking(move || reset_server_cert_pin_in(&base, &server_url)).await
}

/// [`reset_server_cert_pin`] in the app data dir `base`.
fn reset_server_cert_pin_in(base: &Path, sent: &str) -> Result<(), AppError> {
    let (_, meta) = own_meta(base)?;
    tofu::forget_pin(&workspace::own_url(&meta, sent)?)?;
    Ok(())
}

/// SHA-256 fingerprint of the CA pinned at enrollment (the access
/// intermediate). The provisioning tab embeds it as the agent's `--ca-fp`, so
/// the agent's first contact is verified instead of TOFU. None until enrolled.
#[tauri::command]
pub async fn pinned_ca_fingerprint() -> Result<Option<String>, AppError> {
    blocking(|| Ok(enrollment::pinned_ca_fingerprint())).await
}

/// Name (CN) and expiry of this device's enrolled certificate, for the identity
/// line in the settings. None until enrolled; an error when the stored
/// certificate is unreadable — the UI then shows a fixed text, never the error.
#[tauri::command]
pub async fn device_identity() -> Result<Option<DeviceIdentity>, AppError> {
    blocking(enrollment::device_identity).await
}

/// Whether this device currently holds an enrolled mTLS identity. Drives the
/// visibility of the "reset device identity" action in the settings UI.
#[tauri::command]
pub async fn is_device_enrolled() -> Result<bool, AppError> {
    blocking(|| Ok(enrollment::is_enrolled())).await
}

/// Reset this device's enrolled mTLS identity AND forget the TOFU pin for the
/// given server — the recovery path after a server reinstall / PKI re-creation.
/// Both are stale at once: while enrolled, `build_client` always uses the mTLS
/// `enrolled_client` (CA-pin), so dropping the identity makes the next connection
/// fall back to the self-signed/TOFU (or public-CA) path; clearing the stale leaf
/// pin in the same step lets that fallback re-pin instead of being rejected by
/// the old pin. The user must log in / re-enroll afterwards. The identity is
/// revoked at the server first, where it can be (R-0224); the outcome tells the
/// UI whether that happened. Only at the server of this workspace
/// ([`sign_in_target`]), where its purge would revoke it too. An `Err` when the
/// identity could not be deleted on this device (the message names a revoke that
/// happened; the pin then stays) or the pin could not be forgotten. The reset can be
/// repeated (without an identity it ends as `NotEnrolled` and forgets the pin again).
#[tauri::command]
pub async fn reset_device_identity(
    app: tauri::AppHandle,
    server_url: String,
) -> Result<enrollment::ResetOutcome, AppError> {
    let base = storage::app_data_dir(&app)?;
    reset_device_identity_in(&base, &server_url, |url| {
        blocking(move || tofu::forget_pin(&url))
    })
    .await
}

/// [`reset_device_identity`] in the app data dir `base`, `forget` forgetting the pin of the
/// server it is given.
async fn reset_device_identity_in<F, Fut>(
    base: &Path,
    sent: &str,
    forget: F,
) -> Result<enrollment::ResetOutcome, AppError>
where
    F: FnOnce(String) -> Fut,
    Fut: Future<Output = Result<(), AppError>>,
{
    let server_url = sign_in_target(base, sent, None)?;
    let outcome = enrollment::reset_identity(&server_url).await?;
    forget(server_url).await.map_err(|err| {
        AppError::Keyring(match outcome {
            enrollment::ResetOutcome::LocalOnly => format!(
                "resetting the device identity: it was deleted on this device only, the server \
                 could not be asked to revoke it; {err}"
            ),
            _ => format!("resetting the device identity: {err}"),
        })
    })?;
    Ok(outcome)
}

/// The workspace of this process and its `workspace.json`, in the app data dir `base`. The
/// launcher has none.
fn own_meta(base: &Path) -> Result<(WorkspaceId, Meta), AppError> {
    let ws = workspace::current()?;
    let meta = workspace::load_meta(&ws.id, &ws.data_dir(base))?;
    Ok((ws.id, meta))
}

/// The URL a sign-in, an enrollment or a reset of the device identity of the workspace of this
/// process goes to, in the app data dir `base`, `sent` being the one the webview names
/// ([`workspace::sign_in_url`]); for a sign-in as `username`, only while no other workspace
/// signs in to that server as that user ([`workspace::check_sign_in_once`]). The launcher signs
/// in nowhere.
fn sign_in_target(base: &Path, sent: &str, username: Option<&str>) -> Result<String, AppError> {
    let (id, meta) = own_meta(base)?;
    let url = workspace::sign_in_url(&meta, sent)?;
    if let Some(username) = username {
        workspace::check_sign_in_once(&id, &url, username, &workspace::metas(base)?)?;
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
    let base = storage::app_data_dir(&app)?;
    let self_signed = self_signed_setting(&app, allow_self_signed);
    enroll_with_token_in(
        &base,
        &server_url,
        |url| async move { enrollment::enroll_with_token(&url, &token, self_signed).await },
        |url| async move { enrollment::reset_identity(&url).await },
    )
    .await
}

/// [`enroll_with_token`] in the app data dir `base`, `enroll` registering this device at the URL
/// it gets: the server of this workspace ([`sign_in_target`]). A workspace without a URL takes
/// the one of a registration that succeeded at once ([`storage::keep_enrolled_url`]): the
/// identity is that server's, and the purge revokes it there. A workspace that does not keep it
/// (it took another server while the registration waited, or its file does not write) would
/// hold an identity its purge cannot revoke where it was issued: `reset` revokes it there at
/// once (`enrollment::reset_identity`), and the registration fails.
async fn enroll_with_token_in<E, EnrollFut, R, ResetFut>(
    base: &Path,
    sent: &str,
    enroll: E,
    reset: R,
) -> Result<(), AppError>
where
    E: FnOnce(String) -> EnrollFut,
    EnrollFut: Future<Output = Result<(), AppError>>,
    R: FnOnce(String) -> ResetFut,
    ResetFut: Future<Output = Result<enrollment::ResetOutcome, AppError>>,
{
    let server_url = sign_in_target(base, sent, None)?;
    enroll(server_url.clone()).await?;
    if let Err(e) = storage::keep_enrolled_url(base, &server_url) {
        // The registration fails with `e` either way; a reset that fails too leaves the
        // identity for the user's own reset, and the message says so.
        if let Err(not_reset) = reset(server_url).await {
            return Err(AppError::Validation(format!(
                "{e}; resetting it failed, the device identity stays, reset it in the \
                 settings: {not_reset}"
            )));
        }
        return Err(e);
    }
    Ok(())
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
pub async fn load_settings(app: tauri::AppHandle) -> Result<Settings, AppError> {
    blocking(move || storage::load_settings_for_webview(&app)).await
}

#[tauri::command]
pub async fn save_settings(app: tauri::AppHandle, settings: Settings) -> Result<(), AppError> {
    blocking(move || storage::save_settings(&app, &settings)).await
}

/// Loads the connections of the sync workspace of this process from the source it keeps
/// ([`sync_source`]), never with the device identity, and keeps them as its own.
#[tauri::command]
pub async fn sync_connections(
    app: tauri::AppHandle,
    url: String,
) -> Result<Vec<Connection>, AppError> {
    let source = sync_source(&storage::app_data_dir(&app)?, &url)?;
    let allow_self_signed = self_signed_setting(&app, None);
    sync::sync_connections(app, source, allow_self_signed).await
}

/// The source a sync of the workspace of this process loads, in the app data dir `base`,
/// `sent` being the one the webview names ([`workspace::sync_url`]). The launcher syncs
/// nothing.
fn sync_source(base: &Path, sent: &str) -> Result<String, AppError> {
    let (_, meta) = own_meta(base)?;
    workspace::sync_url(&meta, sent)
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

/// Runs `work` with a [`connection::Deadline`] of `timeout`. Past it, the command gives up
/// only if the work has not started anything yet; a start that came first is waited for and
/// its outcome returned, so no window opens after the timeout message.
async fn run_with_deadline<F>(timeout: Duration, work: F) -> Result<(), AppError>
where
    F: FnOnce(&connection::Deadline) -> Result<(), AppError> + Send + 'static,
{
    let deadline = std::sync::Arc::new(connection::Deadline::new(timeout));
    let theirs = std::sync::Arc::clone(&deadline);
    let mut handle = tauri::async_runtime::spawn_blocking(move || work(&theirs));
    let joined = match tokio::time::timeout(timeout, &mut handle).await {
        Ok(joined) => joined,
        Err(_) if deadline.expire() => {
            return Err(AppError::Connection(
                connection::TIMEOUT_MESSAGE.to_string(),
            ))
        }
        Err(_) => handle.await,
    };
    joined.map_err(|e| AppError::Connection(format!("Verbindungsaufbau abgebrochen: {e}")))?
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
    run_with_deadline(OPEN_CONNECTION_TIMEOUT, move |deadline| {
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
            deadline,
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
    run_with_deadline(OPEN_CONNECTION_TIMEOUT, move |deadline| {
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
            deadline,
        )
    })
    .await
}

#[tauri::command]
pub async fn password_state(connection: Connection) -> Result<PasswordState, AppError> {
    blocking(move || password::password_state(&connection)).await
}

#[tauri::command]
pub async fn save_password(
    app: tauri::AppHandle,
    connection: Connection,
    password: String,
) -> Result<(), AppError> {
    let base = storage::app_data_dir(&app)?;
    blocking(move || password::save_password(&base, &connection, &password)).await
}

#[tauri::command]
pub async fn delete_password(
    app: tauri::AppHandle,
    connection: Connection,
) -> Result<(), AppError> {
    let base = storage::app_data_dir(&app)?;
    blocking(move || password::delete_password(&base, &connection)).await
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
    // Nothing opens here, so nothing claims the deadline's start.
    run_with_deadline(OPEN_CONNECTION_TIMEOUT, move |_| {
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

/// Workspace only: runs the playbook `playbook_id` of the signed-in server on `targets` in a
/// terminal. File name and content come from the server, not from the webview
/// ([`ansible::fetch_playbook`], [`ansible_run_with`]).
#[tauri::command]
pub async fn ansible_run(
    session: State<'_, SessionState>,
    playbook_id: String,
    targets: Vec<ansible::AnsibleTarget>,
) -> Result<(), AppError> {
    let session = session.inner();
    ansible_run_with(
        &playbook_id,
        targets,
        |id| async move { ansible::fetch_playbook(session, &id).await },
        ansible::launch_ansible,
    )
    .await
}

/// [`ansible_run`] with the fetch of the playbook and the launch passed in. The id is checked
/// before anything goes to the server ([`ansible::check_playbook_id`]); the files are written
/// and launched on a blocking thread, and a step that fails takes the files written so far
/// with it ([`ansible::run`]).
async fn ansible_run_with<F, Fut, L>(
    playbook_id: &str,
    targets: Vec<ansible::AnsibleTarget>,
    fetch: F,
    launch: L,
) -> Result<(), AppError>
where
    F: FnOnce(String) -> Fut,
    Fut: Future<Output = Result<ansible::Playbook, AppError>>,
    L: FnOnce(&str, &str) -> Result<(), AppError> + Send + 'static,
{
    only(Side::Workspace)?;
    ansible::check_playbook_id(playbook_id)?;
    let playbook = fetch(playbook_id.to_string()).await?;
    blocking(move || ansible::run(&targets, &playbook, launch)).await
}

#[cfg(test)]
mod tests {
    use super::{
        ansible_run_with, check_server_cert_in, delete_workspace_in, enroll_with_token_in,
        list_workspaces_in, open_launcher_with, open_workspace_in, reject_foreign_port,
        reset_device_identity_in, reset_server_cert_pin_in, run_with_deadline, save_workspace_in,
        sign_in_target, sync_source,
    };
    use crate::ansible::{AnsibleTarget, Playbook};
    use crate::enrollment::{self, ResetOutcome};
    use crate::error::AppError;
    use crate::keyring_store;
    use crate::launcher::{Spawned, Spawner};
    use crate::models::{Connection, ConnectionKind, Settings, SyncMode, WorkspaceDraft};
    use crate::port_registry::PortRegistry;
    use crate::storage;
    use crate::workspace::{self, Meta, Registry, RegistryEntry, PALETTE};
    use std::cell::{Cell, RefCell};
    use std::path::{Path, PathBuf};
    use std::process::ExitStatus;
    use std::sync::{Arc, Mutex};
    use std::time::Duration;
    use std::{fs, io};

    #[tokio::test]
    async fn run_with_deadline_returns_ok_for_fast_work() {
        assert!(run_with_deadline(Duration::from_secs(5), |_| Ok(()))
            .await
            .is_ok());
    }

    #[tokio::test]
    async fn run_with_deadline_maps_a_hung_task_to_a_timeout_error() {
        // 4.3: a blocking task that overruns the deadline surfaces a Connection error (the
        // user gets a message, not a frozen webview) instead of hanging.
        let r = run_with_deadline(Duration::from_millis(50), |_| {
            std::thread::sleep(Duration::from_millis(500));
            Ok(())
        })
        .await;
        assert!(matches!(r, Err(AppError::Connection(_))));
    }

    #[tokio::test]
    async fn run_with_deadline_starts_nothing_after_the_timeout() {
        // The work reaches its start only past the deadline: it must not start, and the
        // command has already answered with the timeout.
        let started = Arc::new(Mutex::new(None));
        let seen = Arc::clone(&started);
        let r = run_with_deadline(Duration::from_millis(50), move |deadline| {
            std::thread::sleep(Duration::from_millis(200));
            *seen.lock().unwrap() = Some(deadline.start().is_ok());
            Ok(())
        })
        .await;
        assert!(matches!(r, Err(AppError::Connection(_))));
        std::thread::sleep(Duration::from_millis(400));
        assert_eq!(*started.lock().unwrap(), Some(false), "the late start ran");
    }

    #[tokio::test]
    async fn run_with_deadline_waits_for_work_that_started_in_time() {
        // Started before the deadline, finished after it: its outcome counts, not a timeout.
        // A second leaves a loaded runner time to start the blocking thread before it.
        let r = run_with_deadline(Duration::from_secs(1), |deadline| {
            deadline.start()?;
            std::thread::sleep(Duration::from_millis(1500));
            Err(AppError::Connection("the started work's own error".into()))
        })
        .await;
        match r {
            Err(AppError::Connection(message)) => {
                assert_eq!(message, "the started work's own error")
            }
            other => panic!("{other:?}"),
        }
    }

    #[tokio::test]
    async fn run_with_deadline_passes_through_work_errors() {
        let r = run_with_deadline(Duration::from_secs(5), |_| {
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
            unreadable_settings: None,
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

    /// The files of the ansible run directories (`adminhelper_ansible_…` in the temp dir) whose
    /// name or content holds `marker`; each directory with such a file is removed by its full
    /// path. Other tests write run directories at the same time; the marker tells this test's
    /// apart.
    fn remove_ansible_files_with(marker: &str) -> Vec<PathBuf> {
        let mut found = Vec::new();
        for entry in fs::read_dir(std::env::temp_dir()).unwrap().flatten() {
            let name = entry.file_name().to_string_lossy().into_owned();
            if !name.starts_with("adminhelper_ansible_") {
                continue;
            }
            let dir = entry.path();
            let Ok(files) = fs::read_dir(&dir) else {
                continue;
            };
            let marked: Vec<PathBuf> = files
                .flatten()
                .filter(|file| {
                    file.file_name().to_string_lossy().contains(marker)
                        || fs::read_to_string(file.path()).is_ok_and(|text| text.contains(marker))
                })
                .map(|file| file.path())
                .collect();
            if !marked.is_empty() {
                let _ = fs::remove_dir_all(&dir);
                found.extend(marked);
            }
        }
        found
    }

    const PLAYBOOK_ID: &str = "0b6f2c1e-8a4d-4c3b-9e7f-1a2b3c4d5e6f";

    /// The target `<marker>.example` in the group `web`: the inventory of a run holds `marker`.
    fn marked_targets(marker: &str) -> Vec<AnsibleTarget> {
        vec![AnsibleTarget {
            hostname: format!("{marker}.example"),
            groups: vec!["web".to_string()],
        }]
    }

    /// A playbook `site.yml` whose content holds `marker`.
    fn marked_playbook(marker: &str) -> Playbook {
        Playbook {
            filename: "site.yml".to_string(),
            content: format!("# {marker}\n- hosts: all\n"),
        }
    }

    /// What every launch got: inventory path and content, playbook path and content.
    type Launches = Arc<Mutex<Vec<[String; 4]>>>;

    /// A launch that notes what it gets (see [`Launches`]), then answers `answer`.
    fn noting_launch(
        answer: Result<(), AppError>,
    ) -> (
        Launches,
        impl FnOnce(&str, &str) -> Result<(), AppError> + Send + 'static,
    ) {
        let launches = Launches::default();
        let noted = Arc::clone(&launches);
        let launch = move |inventory: &str, playbook: &str| {
            let read = |path: &str| fs::read_to_string(path).unwrap_or_default();
            noted.lock().unwrap().push([
                inventory.to_string(),
                read(inventory),
                playbook.to_string(),
                read(playbook),
            ]);
            answer
        };
        (launches, launch)
    }

    #[tokio::test]
    async fn ansible_run_launches_the_fetched_playbook_on_the_targets() {
        let marker = format!("run-fetched-{}", std::process::id());
        let _in_a_workspace = entered("standard");
        let (launches, launch) = noting_launch(Ok(()));
        let asked = RefCell::new(Vec::new());

        let result = ansible_run_with(
            PLAYBOOK_ID,
            marked_targets(&marker),
            |id| {
                asked.borrow_mut().push(id);
                async { Ok(marked_playbook(&marker)) }
            },
            launch,
        )
        .await;
        let mut written = remove_ansible_files_with(&marker);
        written.sort();

        assert!(result.is_ok(), "{result:?}");
        assert_eq!(*asked.borrow(), [PLAYBOOK_ID]);
        let launches = launches.lock().unwrap().clone();
        assert_eq!(launches.len(), 1, "{launches:?}");
        let [inventory, inventory_text, playbook, playbook_text] = &launches[0];
        assert_eq!(playbook_text, &marked_playbook(&marker).content);
        assert!(playbook.ends_with("_site.yml"), "{playbook}");
        assert!(
            inventory_text.contains(&format!("[all]\n{marker}.example\n"))
                && inventory_text.contains(&format!("[web]\n{marker}.example\n")),
            "{inventory_text}"
        );
        // A launch that succeeded leaves both files to the run.
        let mut handed = vec![PathBuf::from(inventory), PathBuf::from(playbook)];
        handed.sort();
        assert_eq!(written, handed);
    }

    #[tokio::test]
    async fn ansible_run_writes_no_file_when_the_fetch_fails() {
        let marker = format!("run-fetch-fails-{}", std::process::id());
        let _in_a_workspace = entered("standard");
        let (launches, launch) = noting_launch(Ok(()));

        let result = ansible_run_with(
            PLAYBOOK_ID,
            marked_targets(&marker),
            |_| async {
                Err::<Playbook, _>(AppError::Validation(
                    "the playbook could not be loaded (404 Not Found)".to_string(),
                ))
            },
            launch,
        )
        .await;
        let written = remove_ansible_files_with(&marker);

        assert_refused(result, "could not be loaded", "fetch");
        assert_eq!(
            written,
            Vec::<PathBuf>::new(),
            "a failed fetch wrote a file"
        );
        assert_eq!(
            launches.lock().unwrap().len(),
            0,
            "launched without a playbook"
        );
    }

    #[tokio::test]
    async fn ansible_run_removes_both_files_when_the_launch_fails() {
        let marker = format!("run-launch-fails-{}", std::process::id());
        let _in_a_workspace = entered("standard");
        let (launches, launch) =
            noting_launch(Err(AppError::Connection("no terminal found".to_string())));

        let result = ansible_run_with(
            PLAYBOOK_ID,
            marked_targets(&marker),
            |_| async { Ok(marked_playbook(&marker)) },
            launch,
        )
        .await;
        let written = remove_ansible_files_with(&marker);

        assert!(matches!(result, Err(AppError::Connection(_))), "{result:?}");
        let launches = launches.lock().unwrap().clone();
        assert_eq!(launches.len(), 1, "{launches:?}");
        let [inventory, _, playbook, playbook_text] = &launches[0];
        assert_eq!(playbook_text, &marked_playbook(&marker).content);
        assert_eq!(
            written,
            Vec::<PathBuf>::new(),
            "files left after a failed launch"
        );
        assert!(!Path::new(inventory).exists() && !Path::new(playbook).exists());
    }

    #[tokio::test]
    async fn ansible_run_removes_the_inventory_when_the_playbook_cannot_be_written() {
        let marker = format!("run-write-fails-{}", std::process::id());
        let _in_a_workspace = entered("standard");
        let (launches, launch) = noting_launch(Ok(()));

        // No file system takes a name of 300 bytes (ENAMETOOLONG).
        let result = ansible_run_with(
            PLAYBOOK_ID,
            marked_targets(&marker),
            |_| async {
                Ok(Playbook {
                    filename: "a".repeat(300),
                    ..marked_playbook(&marker)
                })
            },
            launch,
        )
        .await;
        let written = remove_ansible_files_with(&marker);

        assert!(result.is_err(), "{result:?}");
        assert_eq!(written, Vec::<PathBuf>::new(), "the inventory was left");
        assert_eq!(
            launches.lock().unwrap().len(),
            0,
            "launched without a playbook"
        );
    }

    #[tokio::test]
    async fn ansible_run_never_fetches_for_an_id_that_is_no_uuid() {
        let marker = format!("run-bad-id-{}", std::process::id());
        let _in_a_workspace = entered("standard");
        let fetches = Cell::new(0);
        let path_behind = format!("{PLAYBOOK_ID}/content");
        let traversal = format!("../{PLAYBOOK_ID}");

        for id in [
            "",
            "pb1",
            &PLAYBOOK_ID[..35],
            &path_behind,
            &traversal,
            "0b6f2c1e-8a4d-4c3b-9e7f-1a2b3c4d5e6g",
        ] {
            let (launches, launch) = noting_launch(Ok(()));
            let result = ansible_run_with(
                id,
                marked_targets(&marker),
                |_| {
                    fetches.set(fetches.get() + 1);
                    async { Ok(marked_playbook(&marker)) }
                },
                launch,
            )
            .await;
            assert_refused(result, "invalid playbook id", id);
            assert_eq!(launches.lock().unwrap().len(), 0, "{id}");
        }

        assert_eq!(fetches.get(), 0, "fetched for an id that is no UUID");
        assert_eq!(remove_ansible_files_with(&marker), Vec::<PathBuf>::new());
    }

    #[tokio::test]
    async fn ansible_run_runs_only_in_a_workspace() {
        let marker = format!("run-only-in-a-workspace-{}", std::process::id());
        let fetches = Cell::new(0);
        let (launches, launch) = noting_launch(Ok(()));

        // The launcher has no workspace.
        let result = ansible_run_with(
            PLAYBOOK_ID,
            marked_targets(&marker),
            |_| {
                fetches.set(fetches.get() + 1);
                async { Ok(marked_playbook(&marker)) }
            },
            launch,
        )
        .await;
        let written = remove_ansible_files_with(&marker);

        assert_refused(result, "only the process of a workspace", "ansible_run");
        assert_eq!(fetches.get(), 0, "the launcher fetched a playbook");
        assert_eq!(launches.lock().unwrap().len(), 0, "the launcher launched");
        assert_eq!(written, Vec::<PathBuf>::new(), "the launcher wrote a file");
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
            unreadable_settings: None,
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
                    "this workspace belongs to the server https://ah.example.com;",
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

    /// The URL in the `workspace.json` of `id` in `base`.
    fn url_of(base: &Path, id: &str) -> Option<String> {
        Meta::load(&base.join("workspaces").join(id)).unwrap().url
    }

    /// The reset of a registration the workspace does not keep: none comes in these cases.
    fn no_reset(url: String) -> std::future::Ready<Result<ResetOutcome, AppError>> {
        panic!("the registration at {url} was reset")
    }

    #[tokio::test]
    async fn login_binding_a_registration_gives_a_workspace_without_a_url_the_one_it_went_to() {
        let scratch = Scratch::new("enroll-url");
        let base = &scratch.0;
        server_workspaces(
            base,
            &[
                (
                    "w-0000000a",
                    "Kunde A",
                    Some("https://ah.example.com"),
                    None,
                ),
                ("w-0000000c", "Neu", None, None),
                ("w-0000000d", "Neu 2", None, None),
            ],
        );
        let asked = RefCell::new(Vec::new());
        let succeeds = |url: String| {
            asked.borrow_mut().push(url);
            async { Ok::<(), AppError>(()) }
        };

        // The launcher registers nowhere.
        let no_workspace = workspace::current().unwrap_err().to_string();
        let refused = enroll_with_token_in(base, "https://ah.example.com", succeeds, no_reset)
            .await
            .unwrap_err();
        assert_eq!(refused.to_string(), no_workspace);
        {
            // Without a URL: registered at the one sent, which the workspace keeps from then on.
            let _c = entered("w-0000000c");
            enroll_with_token_in(base, " https://other.example.com/ ", succeeds, no_reset)
                .await
                .unwrap();
            assert_eq!(
                url_of(base, "w-0000000c").as_deref(),
                Some("https://other.example.com/")
            );
        }
        {
            // A registration that fails gives no URL.
            let _d = entered("w-0000000d");
            let failed = enroll_with_token_in(
                base,
                "https://other.example.com",
                |url| {
                    asked.borrow_mut().push(url);
                    async { Err(AppError::Connection("unreachable".to_string())) }
                },
                no_reset,
            )
            .await;
            assert!(matches!(failed, Err(AppError::Connection(_))), "{failed:?}");
            assert_eq!(url_of(base, "w-0000000d"), None);
        }
        {
            // With a URL: registered there, and the URL stays as it is; another server is refused
            // before the token leaves.
            let _a = entered("w-0000000a");
            enroll_with_token_in(base, "https://AH.example.com:443/", succeeds, no_reset)
                .await
                .unwrap();
            assert_refused(
                enroll_with_token_in(base, "https://other.example.com", succeeds, no_reset).await,
                "this workspace belongs to the server https://ah.example.com;",
                "other server",
            );
            assert_eq!(
                url_of(base, "w-0000000a").as_deref(),
                Some("https://ah.example.com")
            );
        }
        assert_eq!(
            *asked.borrow(),
            [
                "https://other.example.com/",
                "https://other.example.com",
                "https://ah.example.com"
            ]
        );
    }

    #[tokio::test]
    async fn login_binding_a_registration_the_workspace_does_not_keep_is_revoked_at_once() {
        let _keyring = keyring_store::memory();
        let scratch = Scratch::new("enroll-taken");
        let base = &scratch.0;
        server_workspaces(base, &[("w-0000000c", "Neu", None, None)]);
        // Held, not freed: nobody answers at the server the device registers at.
        let (_reserved, port) = crate::test_tls::refused_port();
        let registered_at = format!("https://127.0.0.1:{port}");
        let other = "https://other.example.com";
        let _c = entered("w-0000000c");
        let prefix = workspace::current().unwrap().keyring_prefix();
        let reset_at = RefCell::new(Vec::new());

        let result = enroll_with_token_in(
            base,
            &registered_at,
            |_| async {
                // While the registration waits for its server, a save of the settings gives the
                // workspace another first URL; then the identity arrives.
                let settings = Settings {
                    server_url: Some(other.to_string()),
                    ..Settings::default()
                };
                storage::save_settings_at(base, &settings)?;
                enrolled(&prefix);
                Ok(())
            },
            |url| {
                reset_at.borrow_mut().push(url.clone());
                async move { enrollment::reset_identity(&url).await }
            },
        )
        .await;

        assert_refused(
            result,
            "this workspace took the URL of another server while this device registered",
            "taken",
        );
        // Revoked where it was issued, and gone here; the workspace keeps the URL it took.
        assert_eq!(*reset_at.borrow(), [registered_at]);
        assert!(!enrollment::is_enrolled());
        assert!(!enrollment::holds_identity(&prefix).unwrap());
        assert_eq!(url_of(base, "w-0000000c").as_deref(), Some(other));
    }

    #[tokio::test]
    async fn enroll_not_kept_whose_reset_fails_says_the_identity_stays() {
        let scratch = Scratch::new("enroll-taken-reset-fails");
        let base = &scratch.0;
        server_workspaces(base, &[("w-0000000d", "Neu", None, None)]);
        let _c = entered("w-0000000d");

        let result = enroll_with_token_in(
            base,
            "https://ah.example.com",
            |_| async {
                let settings = Settings {
                    server_url: Some("https://other.example.com".to_string()),
                    ..Settings::default()
                };
                storage::save_settings_at(base, &settings)?;
                Ok(())
            },
            |_| async { Err(AppError::Keyring("the keyring is locked".to_string())) },
        )
        .await;

        let Err(AppError::Validation(msg)) = result else {
            panic!("not refused as it should be: {result:?}");
        };
        for says in [
            "this workspace took the URL of another server while this device registered",
            "the device identity stays, reset it in the settings",
            "the keyring is locked",
        ] {
            assert!(msg.contains(says), "{says:?} missing in {msg:?}");
        }
    }

    // ── Reset, pins and the cert check at the server of the workspace ──

    /// An identity behind the keyring prefix `prefix`, as an enrollment leaves it.
    fn enrolled(prefix: &str) {
        use rcgen::{CertificateParams, KeyPair, PKCS_ECDSA_P256_SHA256};
        let key = KeyPair::generate_for(&PKCS_ECDSA_P256_SHA256).unwrap();
        let cert = CertificateParams::new(vec![])
            .unwrap()
            .self_signed(&key)
            .unwrap()
            .pem();
        for (entry, pem) in [
            ("enroll|key", key.serialize_pem()),
            ("enroll|cert", cert.clone()),
            ("enroll|ca", cert),
        ] {
            keyring_store::set(&format!("{prefix}{entry}"), &pem).unwrap();
        }
    }

    /// The keyring key of the pin of `host_port` (`tofu|cert|<host:port>`, one for the device).
    fn pin(host_port: &str) -> String {
        format!("tofu|cert|{host_port}")
    }

    #[tokio::test]
    async fn login_binding_a_reset_of_the_identity_goes_to_the_server_of_the_workspace() {
        let _keyring = keyring_store::memory();
        let scratch = Scratch::new("reset-identity");
        let base = &scratch.0;
        // Held, not freed: nobody answers at the server of the workspace.
        let (_reserved, port) = crate::test_tls::refused_port();
        let kept = format!("https://127.0.0.1:{port}");
        server_workspaces(
            base,
            &[("w-0000000a", "Kunde A", Some(kept.as_str()), None)],
        );
        let own_pin = pin(&format!("127.0.0.1:{port}"));
        let other_pin = pin("other.example.com:443");
        for key in [&own_pin, &other_pin] {
            keyring_store::set(key, "pinned").unwrap();
        }

        // The launcher has no identity to reset.
        let no_workspace = workspace::current().unwrap_err().to_string();
        let refused = reset_device_identity_in(base, &kept, forget_here)
            .await
            .unwrap_err();
        assert_eq!(refused.to_string(), no_workspace);

        let _a = entered("w-0000000a");
        enrolled(&workspace::current().unwrap().keyring_prefix());
        // Another server: refused before a thing is revoked, deleted or forgotten.
        for other in [
            "https://other.example.com".to_string(),
            format!("http://127.0.0.1:{port}"),
        ] {
            assert_refused(
                reset_device_identity_in(base, &other, forget_here).await,
                &format!("this workspace belongs to the server {kept};"),
                &other,
            );
            assert!(enrollment::is_enrolled(), "{other}");
            for key in [&own_pin, &other_pin] {
                assert!(keyring_store::get(key).is_some(), "{other}: {key}");
            }
        }
        // Its own server, however the webview spells it.
        let outcome =
            reset_device_identity_in(base, &format!("https://127.0.0.1:{port}/x"), forget_here)
                .await
                .unwrap();
        assert_eq!(outcome, ResetOutcome::LocalOnly);
        assert!(!enrollment::is_enrolled());
        assert_eq!(keyring_store::get(&own_pin), None);
        assert!(keyring_store::get(&other_pin).is_some());
    }

    /// Forgets the pin on the test's own thread, where its in-memory keyring lives; the
    /// command does it through `blocking`.
    async fn forget_here(server_url: String) -> Result<(), AppError> {
        crate::tofu::forget_pin(&server_url)
    }

    #[tokio::test]
    async fn a_reset_revoked_here_only_whose_pin_stays_names_both() {
        let _keyring = keyring_store::memory();
        let scratch = Scratch::new("reset-identity-both");
        let base = &scratch.0;
        let (_reserved, port) = crate::test_tls::refused_port();
        let kept = format!("https://127.0.0.1:{port}");
        server_workspaces(
            base,
            &[("w-0000000a", "Kunde A", Some(kept.as_str()), None)],
        );
        let _a = entered("w-0000000a");
        enrolled(&workspace::current().unwrap().keyring_prefix());

        let failed = reset_device_identity_in(base, &kept, |_| async {
            Err(AppError::Keyring("the pin stayed".to_string()))
        })
        .await
        .unwrap_err()
        .to_string();
        assert!(failed.contains("deleted on this device only"), "{failed}");
        assert!(failed.contains("the pin stayed"), "{failed}");
        assert!(!enrollment::is_enrolled());
    }

    #[tokio::test]
    async fn login_binding_the_pin_reset_and_the_cert_check_name_the_server_of_the_workspace() {
        let _keyring = keyring_store::memory();
        let scratch = Scratch::new("reset-pin");
        let base = &scratch.0;
        server_workspaces(
            base,
            &[
                (
                    "w-0000000a",
                    "Kunde A",
                    Some("https://ah.example.com"),
                    None,
                ),
                ("w-0000000c", "Neu", None, None),
            ],
        );
        Meta {
            kind: SyncMode::Sync,
            name: "Sync".to_string(),
            color: PALETTE[0].to_string(),
            url: Some("https://sync.example.com/connections.json".to_string()),
            interval_minutes: 1,
            allow_self_signed_certs: false,
            last_username: None,
            legacy_keys: false,
        }
        .store(&base.join("workspaces").join("w-0000000d"))
        .unwrap();
        let [own, sync, other] = [
            "ah.example.com:443",
            "sync.example.com:443",
            "other.example.com:443",
        ]
        .map(pin);
        for key in [&own, &sync, &other] {
            keyring_store::set(key, "pinned").unwrap();
        }
        let pinned = || [&own, &sync, &other].map(|key| keyring_store::get(key).is_some());

        // The launcher forgets no pin and checks no server.
        let no_workspace = workspace::current().unwrap_err().to_string();
        let refused = reset_server_cert_pin_in(base, "https://ah.example.com").unwrap_err();
        assert_eq!(refused.to_string(), no_workspace);
        let refused = check_server_cert_in(base, "https://ah.example.com")
            .await
            .unwrap_err();
        assert_eq!(refused.to_string(), no_workspace);
        assert_eq!(pinned(), [true, true, true]);
        {
            let _a = entered("w-0000000a");
            let says = "this workspace belongs to the server https://ah.example.com;";
            assert_refused(
                reset_server_cert_pin_in(base, "https://other.example.com"),
                says,
                "pin",
            );
            assert_refused(
                check_server_cert_in(base, "https://other.example.com").await,
                says,
                "cert check",
            );
            assert_eq!(pinned(), [true, true, true]);
            reset_server_cert_pin_in(base, "https://AH.example.com/").unwrap();
            assert_eq!(pinned(), [false, true, true]);
        }
        {
            // A sync workspace: the server of its source.
            let _d = entered("w-0000000d");
            assert_refused(
                reset_server_cert_pin_in(base, "https://other.example.com"),
                "this workspace belongs to the server https://sync.example.com;",
                "sync",
            );
            reset_server_cert_pin_in(base, "https://sync.example.com").unwrap();
            assert_eq!(pinned(), [false, false, true]);
        }
        {
            // Without a URL of its own, the one sent: the login screen before the first sign-in.
            let _c = entered("w-0000000c");
            reset_server_cert_pin_in(base, "https://other.example.com").unwrap();
            assert_eq!(pinned(), [false, false, false]);
        }
    }

    // ── Where the sync of the workspace of this process loads from ──

    /// The source of the sync workspace below; its query carries a key.
    const SYNC_SOURCE: &str = "https://sync.example/c.json?api_key=k1";

    /// Lays out `base` with a workspace of each kind: `w-0000000a` at the server
    /// `https://ah.example`, `w-0000000b` syncing from [`SYNC_SOURCE`], `w-0000000c` syncing
    /// without a source yet, `w-0000000e` local.
    fn sync_workspaces(base: &Path) {
        for (id, kind, url) in [
            ("w-0000000a", SyncMode::Server, Some("https://ah.example")),
            ("w-0000000b", SyncMode::Sync, Some(SYNC_SOURCE)),
            ("w-0000000c", SyncMode::Sync, None),
            ("w-0000000e", SyncMode::Local, None),
        ] {
            Meta {
                kind,
                name: id.to_string(),
                color: PALETTE[0].to_string(),
                url: url.map(String::from),
                interval_minutes: 1,
                allow_self_signed_certs: false,
                last_username: None,
                legacy_keys: false,
            }
            .store(&base.join("workspaces").join(id))
            .unwrap();
        }
    }

    #[test]
    fn sync_binding_loads_the_source_the_sync_workspace_keeps() {
        let scratch = Scratch::new("sync-source");
        let base = &scratch.0;
        sync_workspaces(base);
        let _b = entered("w-0000000b");
        for sent in [SYNC_SOURCE, "  https://sync.example/c.json?api_key=k1 \n"] {
            assert_eq!(sync_source(base, sent).unwrap(), SYNC_SOURCE, "{sent:?}");
        }
    }

    #[test]
    fn sync_binding_refuses_another_source_of_the_same_server_and_names_none() {
        let scratch = Scratch::new("sync-other-source");
        let base = &scratch.0;
        sync_workspaces(base);
        let _b = entered("w-0000000b");
        for other in [
            "https://sync.example/d.json?api_key=k1",
            "https://sync.example/c.json?api_key=k2",
            "https://sync.example/c.json",
            "https://sync.example/c.json?api_key=k1&page=2",
        ] {
            let refused = sync_source(base, other).unwrap_err();
            assert!(
                matches!(&refused, AppError::Validation(_)),
                "{other}: {refused:?}"
            );
            let says = refused.to_string();
            assert!(
                says.contains("syncs only from the sync URL it keeps"),
                "{other}: {says}"
            );
            for secret in ["api_key", "k1", "c.json"] {
                assert!(!says.contains(secret), "{other}: {says}");
            }
        }
    }

    #[test]
    fn sync_binding_syncs_only_in_a_sync_workspace_with_a_source() {
        let scratch = Scratch::new("sync-where");
        let base = &scratch.0;
        sync_workspaces(base);

        // The launcher syncs nothing.
        let no_workspace = workspace::current().unwrap_err().to_string();
        let refused = sync_source(base, SYNC_SOURCE).unwrap_err();
        assert_eq!(refused.to_string(), no_workspace);
        {
            // A server workspace, not even from the URL of its own server.
            let _a = entered("w-0000000a");
            for sent in ["https://ah.example", SYNC_SOURCE] {
                assert_refused(sync_source(base, sent), "only a sync workspace syncs", sent);
            }
        }
        {
            let _e = entered("w-0000000e");
            assert_refused(
                sync_source(base, SYNC_SOURCE),
                "only a sync workspace syncs",
                "local",
            );
        }
        {
            let _c = entered("w-0000000c");
            assert_refused(
                sync_source(base, SYNC_SOURCE),
                "this sync workspace has no sync URL yet",
                "no source",
            );
        }
    }

    /// A synchronous command runs on the main thread: the window stands still while the
    /// keyring or the settings lock keeps it waiting. These wait on either, so each is async
    /// and does its work through `blocking`.
    #[test]
    fn commands_that_wait_run_on_a_blocking_thread() {
        // A Windows checkout carries CRLF line ends.
        let source = include_str!("commands.rs").replace("\r\n", "\n");
        for name in [
            "reset_server_cert_pin",
            "reset_device_identity",
            "pinned_ca_fingerprint",
            "device_identity",
            "is_device_enrolled",
            "load_settings",
            "save_settings",
            "password_state",
            "save_password",
            "delete_password",
        ] {
            let head = format!("#[tauri::command]\npub async fn {name}(");
            let start = source
                .find(&head)
                .unwrap_or_else(|| panic!("{name} is not an async command"));
            let body = &source[start..];
            let body = &body[..body.find("\n}\n").expect("end of the command")];
            assert!(body.contains("blocking("), "{name} does not use blocking");
        }
    }
}
