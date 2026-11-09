// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! Embedded RDP, stage 1: the backend (docs/features/arch-rdp-backend.md).
//!
//! `rdp_session_start` checks and resolves the listed connection the way a start with the stored
//! password does and hands it to a session thread (`session`). The webview hears the phases as
//! `rdp-session` events and takes the picture from the session's WebSocket (`frame_ws`).

#[cfg(windows)]
mod clipboard_win;
pub(crate) mod frame_ws;
#[cfg(test)]
mod license_gate;
#[cfg(target_os = "linux")]
mod openh264;
pub(crate) mod session;
pub(crate) mod tofu;
pub(crate) mod watchdog;
pub(crate) mod window;

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};

use ironrdp_client::config::Destination;
use serde::Serialize;
use tauri::{Emitter, Manager, State};
use tauri_plugin_dialog::DialogExt;
use tokio::sync::oneshot;
use zeroize::Zeroizing;

use self::frame_ws::{Frames, Tokens};
use self::session::{Code, Display, Report, Target};
use self::tofu::{cert_policy, CertPolicy, CertReason};
use crate::commands::{reject_foreign_port, run_with_deadline, OPEN_CONNECTION_TIMEOUT};
use crate::connection::{checked_password_source, CredentialConnection};
use crate::error::AppError;
use crate::models::{Connection, ConnectionKind, RdpPerformanceProfile, VisitorBinding};
use crate::password::{load_password_keyring, rdp_port};
use crate::session::SessionState;
use crate::tofu::{KeyringPinStore, PinStore};
use crate::tunnel::{resolve_connection, ResolvedConnection, TunnelMapping};
use crate::validation::validate_connection_input;
use crate::{frpc, storage, workspace};

/// The Tauri event that carries the phases of every session.
const EVENT: &str = "rdp-session";

type Running = Arc<Mutex<HashMap<String, Handle>>>;

/// What the app keeps of a session that has not ended.
struct Handle {
    stop: oneshot::Sender<()>,
    frames: Frames,
    /// Set once the session has started.
    info: Option<SessionInfo>,
    /// The port of its WebSocket and the tokens of later logins, set once it has started.
    socket: Option<(u16, Tokens)>,
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|e| e.into_inner())
}

/// The sessions of this process that have not ended, each with the sender that stops it, its
/// picture and what it connected to.
#[derive(Default)]
pub(crate) struct RdpSessions {
    next: AtomicU64,
    running: Running,
}

impl RdpSessions {
    fn add(&self, stop: oneshot::Sender<()>, frames: Frames) -> String {
        let id = format!("rdp-{}", self.next.fetch_add(1, Ordering::Relaxed) + 1);
        let handle = Handle {
            stop,
            frames,
            info: None,
            socket: None,
        };
        lock(&self.running).insert(id.clone(), handle);
        id
    }

    fn started(&self, id: &str, info: SessionInfo, ws_port: u16, tokens: Tokens) {
        if let Some(handle) = lock(&self.running).get_mut(id) {
            handle.info = Some(info);
            handle.socket = Some((ws_port, tokens));
        }
    }

    /// Port and a fresh token for a new login at the WebSocket of session `id` that shows
    /// `screen`; the token that screen had before logs in no more.
    fn attach(&self, id: &str, screen: usize) -> Result<Attached, AppError> {
        if screen >= frame_ws::SCREENS {
            return Err(AppError::Validation(format!("no screen {screen}")));
        }
        let (ws_port, tokens) = lock(&self.running)
            .get(id)
            .and_then(|handle| handle.socket.clone())
            .ok_or_else(ended)?;
        Ok(Attached {
            ws_port,
            token: tokens.renew(screen)?,
        })
    }

    fn stop(&self, id: &str) {
        if let Some(handle) = lock(&self.running).remove(id) {
            let _ = handle.stop.send(());
        }
    }

    /// Ends every session and returns their ids.
    fn stop_all(&self) -> Vec<String> {
        let running = std::mem::take(&mut *lock(&self.running));
        running
            .into_iter()
            .map(|(id, handle)| {
                let _ = handle.stop.send(());
                id
            })
            .collect()
    }

    fn frames(&self, id: &str) -> Result<Frames, AppError> {
        lock(&self.running)
            .get(id)
            .map(|handle| handle.frames.clone())
            .ok_or_else(ended)
    }

    fn info(&self, id: &str) -> Result<SessionInfo, AppError> {
        lock(&self.running)
            .get(id)
            .and_then(|handle| handle.info.clone())
            .ok_or_else(ended)
    }
}

fn ended() -> AppError {
    AppError::Validation("the RDP session has ended".to_string())
}

/// What a session connected to, for the connection info of the webview.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub(crate) struct SessionInfo {
    /// `host:port` of the connection as it is stored, also when a tunnel carries it.
    target: String,
    via_tunnel: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    tunnel: Option<String>,
    credssp: bool,
    /// `pinned` or `trust_all`.
    certificate: &'static str,
    /// The pinned fingerprint; none when the connection trusts every certificate.
    #[serde(skip_serializing_if = "Option::is_none")]
    fingerprint: Option<String>,
}

fn session_info(
    listed: &Connection,
    resolved: &ResolvedConnection,
    target: &Target,
) -> SessionInfo {
    let host = listed.host.as_deref().unwrap_or_default().trim();
    let host = if host.contains(':') && !host.starts_with('[') {
        format!("[{host}]")
    } else {
        host.to_string()
    };
    let (certificate, fingerprint) = match &target.policy {
        CertPolicy::TrustAll => ("trust_all", None),
        CertPolicy::Pinned { pin, .. } => ("pinned", pin.clone()),
    };
    SessionInfo {
        target: format!("{host}:{}", rdp_port(listed)),
        via_tunnel: resolved.via_tunnel,
        tunnel: resolved.tunnel_name.clone().filter(|_| resolved.via_tunnel),
        credssp: target.credssp,
        certificate,
        fingerprint,
    }
}

/// The performance profile of a session to `listed`: its own, else the one of the settings.
fn performance(listed: &Connection, settings: RdpPerformanceProfile) -> RdpPerformanceProfile {
    listed
        .options
        .as_ref()
        .and_then(|options| options.rdp.as_ref())
        .and_then(|rdp| rdp.performance_profile)
        .unwrap_or(settings)
}

/// One phase of a session as the webview reads it.
#[derive(Debug, Clone, Serialize)]
struct PhaseEvent {
    session_id: String,
    phase: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    code: Option<Code>,
    #[serde(skip_serializing_if = "Option::is_none")]
    identity: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    fingerprint: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    reason: Option<&'static str>,
}

impl PhaseEvent {
    fn new(session_id: &str, report: Report) -> Self {
        let mut event = PhaseEvent {
            session_id: session_id.to_string(),
            phase: "",
            code: None,
            identity: None,
            fingerprint: None,
            reason: None,
        };
        event.phase = match report {
            Report::Connecting => "connecting",
            Report::Connected => "connected",
            Report::Reconnecting => "reconnecting",
            Report::Certificate(problem) => {
                event.identity = Some(problem.identity);
                event.fingerprint = Some(problem.fingerprint);
                event.reason = Some(match problem.reason {
                    CertReason::Unknown => "unknown",
                    CertReason::Changed => "changed",
                });
                "certificate"
            }
            Report::Disconnected(code) => {
                event.code = Some(code);
                "disconnected"
            }
            Report::Failed(code) => {
                event.code = Some(code);
                "failed"
            }
        };
        event
    }
}

/// The phases of session `id` as events to `sink`. The last one takes the session out of
/// `running` first, so a stop that comes after it finds nothing to stop.
fn reporter(
    id: String,
    running: Running,
    sink: impl Fn(PhaseEvent) + Send + 'static,
) -> impl Fn(Report) + Send + 'static {
    move |report| {
        if report.ends() {
            lock(&running).remove(&id);
        }
        sink(PhaseEvent::new(&id, report));
    }
}

/// The target of a session to `listed`, the connection as the webview lists it. Rust resolves
/// it with the session's `tunnels` and the `bindings` of its frpc and checks it as
/// `connection::open_connection_stored` checks a start with the stored password; the password
/// is `typed` when the user typed one for this start, else it comes from the keyring, the
/// certificate pin from `pins`. Both may wait: a blocking thread only.
fn prepare(
    base: &Path,
    listed: &Connection,
    tunnels: &[TunnelMapping],
    connections: &[Connection],
    bindings: &[VisitorBinding],
    pins: &dyn PinStore,
    typed: Option<Zeroizing<String>>,
) -> Result<Target, AppError> {
    if listed.kind != ConnectionKind::Rdp {
        return Err(AppError::Validation(
            "an embedded RDP session needs an RDP connection".to_string(),
        ));
    }
    validate_connection_input(listed)?;
    let own = listed
        .options
        .as_ref()
        .and_then(|options| options.rdp.as_ref());
    if own.is_some_and(|rdp| rdp.gateway.is_some()) {
        return Err(AppError::RdpOsClient(
            "an embedded RDP session cannot go through an RD gateway".to_string(),
        ));
    }
    if own.is_some_and(|rdp| rdp.printers == Some(true)) {
        return Err(AppError::RdpOsClient(
            "an embedded RDP session cannot share printers".to_string(),
        ));
    }
    let workspace = workspace::current()?;
    let resolved = resolve_connection(listed, tunnels, bindings);
    let credential = CredentialConnection {
        connection: Some(listed),
        tunnels,
        connections,
        bindings,
    };
    let source = checked_password_source(&resolved.connection, &credential)?;
    reject_foreign_port(base, &resolved.connection, bindings)?;
    let host = resolved.connection.host.as_deref().map(str::trim);
    let Some(host) = host.filter(|host| !host.is_empty()) else {
        return Err(AppError::Validation(
            "an embedded RDP session needs a host".to_string(),
        ));
    };
    let username = source.username.as_deref().map(str::trim);
    let Some(username) = username.filter(|username| !username.is_empty()) else {
        return Err(AppError::Validation(
            "an embedded RDP session needs a user name".to_string(),
        ));
    };
    let domain = source.domain.as_deref().map(str::trim);
    let domain = domain.filter(|domain| !domain.is_empty());
    let destination = Destination::from_parts(host, rdp_port(&resolved.connection));
    let policy = cert_policy(&workspace.id, listed, &resolved, &destination, pins)?;
    // An empty one is none, as on the OS client's way (`connection::rdp`).
    let password = match typed.filter(|typed| !typed.is_empty()) {
        Some(typed) => typed,
        None => Zeroizing::new(load_password_keyring(base, source)?.ok_or_else(|| {
            AppError::Validation("no password is stored for this RDP connection".to_string())
        })?),
    };
    Ok(Target {
        destination,
        // `rdp_session_start` sets the size the webview asks for.
        display: Display::default(),
        username: username.to_string(),
        domain: domain.map(str::to_string),
        password,
        policy,
        audio: own.and_then(|rdp| rdp.audio),
        drive: None,
        credssp: own.is_none_or(|rdp| rdp.nla != Some(false)),
        // `rdp_session_start` sets it from the settings, which `prepare` does not read.
        performance: RdpPerformanceProfile::Auto,
        // `rdp_session_start` sets it, after the settings and the download.
        #[cfg(target_os = "linux")]
        h264: None,
    })
}

/// The folders a shared drive must not reach.
#[derive(Default)]
struct Kept {
    /// Neither it nor a folder above it: XDG_DOWNLOAD_DIR may name the home folder itself.
    home: Option<PathBuf>,
    /// Neither these, a folder above nor one below them (app data, configuration).
    private: Vec<PathBuf>,
}

/// The folder `listed` shares as its drive: the user's `downloads` folder when its options ask
/// for drives (`options.rdp.drives`), else none. A folder that cannot be shared is the reason the
/// session goes without one; so is a root and a folder that reaches one of the `kept`.
fn shared_drive(
    listed: &Connection,
    downloads: Option<PathBuf>,
    kept: &Kept,
) -> Result<Option<PathBuf>, String> {
    let wanted = listed
        .options
        .as_ref()
        .and_then(|options| options.rdp.as_ref())
        .and_then(|rdp| rdp.drives)
        .unwrap_or(false);
    if !wanted {
        return Ok(None);
    }
    let folder = downloads.ok_or("there is no Downloads folder")?;
    let folder = folder
        .canonicalize()
        .map_err(|error| format!("the Downloads folder cannot be resolved: {error}"))?;
    if folder.parent().is_none() {
        return Err("the Downloads folder is a root".into());
    }
    let resolved = |paths: &mut dyn Iterator<Item = &PathBuf>| -> Vec<PathBuf> {
        paths.filter_map(|path| path.canonicalize().ok()).collect()
    };
    let private = resolved(&mut kept.private.iter());
    if resolved(&mut kept.home.iter().chain(&kept.private))
        .iter()
        .any(|kept| kept.starts_with(&folder))
        || private.iter().any(|kept| folder.starts_with(kept))
    {
        return Err(
            "the Downloads folder reaches the home, app data or configuration folder".into(),
        );
    }
    #[cfg(windows)]
    let folder = without_verbatim(&folder.to_string_lossy()).map_or(folder, PathBuf::from);
    session::rdpdr_factory(&folder)?;
    Ok(Some(folder))
}

/// `path` without the `\\?\` prefix `canonicalize` gives on Windows, which IronRDP's
/// `RedirectedDrive` refuses (f96f664); `None` for a path without one.
#[cfg_attr(not(windows), allow(dead_code))]
fn without_verbatim(path: &str) -> Option<String> {
    let rest = path.strip_prefix(r"\\?\")?;
    Some(match rest.strip_prefix(r"UNC\") {
        Some(share) => format!(r"\\{share}"),
        None => rest.to_string(),
    })
}

/// Where the webview takes the picture of a started session from.
#[derive(Debug, Serialize)]
pub(crate) struct Started {
    session_id: String,
    ws_port: u16,
    token: String,
    /// `drive_unavailable`: the options ask for a drive, the session shares none.
    #[serde(skip_serializing_if = "Option::is_none")]
    notice: Option<&'static str>,
}

/// Where a window logs in again at the WebSocket of a running session. No `Debug`: it carries
/// the token.
#[derive(Serialize)]
pub(crate) struct Attached {
    ws_port: u16,
    token: String,
}

/// Starts an embedded session to `connection` as the webview lists it; the call returns once the
/// session's WebSocket listens. The phases follow as `rdp-session` events, the first one possibly
/// before this call returns: the webview listens before it calls. A refusal before the start is
/// the error of this call, as with `open_connection_stored`. A `password` the user typed goes to
/// this session only and to no store. `display` is the desktop to start with, 1280×720 at 100 %
/// when the webview names none.
#[tauri::command]
pub(crate) async fn rdp_session_start(
    app: tauri::AppHandle,
    state: State<'_, frpc::FrpcState>,
    signed_in: State<'_, SessionState>,
    sessions: State<'_, RdpSessions>,
    connection: Connection,
    password: Option<String>,
    display: Option<Display>,
) -> Result<Started, AppError> {
    let password = password.map(Zeroizing::new);
    let (tunnels, connections, bindings) = match signed_in.current().await {
        Some(now) => {
            let bindings = frpc::bindings_for(state.inner(), &now.signed_in());
            (now.tunnels, now.connections, bindings)
        }
        None => Default::default(),
    };
    let (stop, stopped) = oneshot::channel();
    let frames = Frames::default();
    let session_id = sessions.add(stop, frames.clone());
    let emitter = app.clone();
    let report = reporter(
        session_id.clone(),
        Arc::clone(&sessions.running),
        move |event| {
            if let Err(error) = emitter.emit(EVENT, event) {
                log::warn!("could not pass the phase of an RDP session to the webview: {error}");
            }
        },
    );
    #[cfg(target_os = "linux")]
    let h264 = h264_library(&app).await;
    let started = run_with_deadline(OPEN_CONNECTION_TIMEOUT, move |deadline| {
        let base = storage::app_data_dir(&app)?;
        let pins = KeyringPinStore::production();
        let mut target = prepare(
            &base,
            &connection,
            &tunnels,
            &connections,
            &bindings,
            &pins,
            password,
        )?;
        target.display = display.map_or_else(Display::default, |display| {
            Display::clamped(display.width, display.height, display.scale)
        });
        #[cfg(target_os = "linux")]
        {
            target.h264 = h264;
        }
        target.performance = performance(
            &connection,
            storage::load_settings(&app)?.rdp_performance_profile,
        );
        let info = session_info(
            &connection,
            &resolve_connection(&connection, &tunnels, &bindings),
            &target,
        );
        let kept = Kept {
            home: app.path().home_dir().ok(),
            private: [app.path().app_data_dir(), app.path().config_dir()]
                .into_iter()
                .filter_map(Result::ok)
                .collect(),
        };
        let notice = match shared_drive(&connection, app.path().download_dir().ok(), &kept) {
            Ok(drive) => {
                target.drive = drive;
                None
            }
            Err(reason) => {
                log::warn!("the RDP session shares no drive: {reason}");
                Some("drive_unavailable")
            }
        };
        deadline.start()?;
        session::spawn(target, frames, stopped, report)
            .map(|(ws_port, token, tokens)| (ws_port, token, tokens, notice, info))
    })
    .await;
    match started {
        Ok((ws_port, token, tokens, notice, info)) => {
            sessions.started(&session_id, info, ws_port, tokens);
            Ok(Started {
                session_id,
                ws_port,
                token,
                notice,
            })
        }
        Err(error) => {
            sessions.stop(&session_id);
            Err(error)
        }
    }
}

/// Cisco's OpenH264 for a session while the settings keep H.264 on (R-1102), downloaded when it
/// is missing; a failed download costs this session H.264 only, and the next one tries again.
#[cfg(target_os = "linux")]
async fn h264_library(app: &tauri::AppHandle) -> Option<PathBuf> {
    if !storage::load_settings(app).ok()?.rdp_h264 {
        return None;
    }
    let base = storage::app_data_dir(app).ok()?;
    match openh264::ensure(&base).await {
        Ok(path) => Some(path),
        Err(error) => {
            log::warn!("the RDP session runs without H.264: {error}");
            None
        }
    }
}

/// Deletes Cisco's OpenH264 library when the settings turn H.264 off (R-1102). None there is no
/// error; elsewhere than on Linux there never is one.
#[tauri::command]
pub(crate) fn openh264_remove(app: tauri::AppHandle) -> Result<(), AppError> {
    #[cfg(target_os = "linux")]
    openh264::remove(&storage::app_data_dir(&app)?)?;
    #[cfg(not(target_os = "linux"))]
    let _ = app;
    Ok(())
}

/// Ends the session `session_id` and its WebSocket; one that ended already, or never was, is no
/// error. The `disconnected` phase follows as an event.
#[tauri::command]
pub(crate) fn rdp_session_stop(
    window: tauri::Window,
    sessions: State<'_, RdpSessions>,
    session_id: String,
) -> Result<(), AppError> {
    window::may_reach(window.label(), &session_id)?;
    sessions.stop(&session_id);
    Ok(())
}

/// Port and a fresh, single-use token for logging in again at the WebSocket of session
/// `session_id`, after the webview lost its connection or for another window (R-1101). The login
/// takes over from the client before; the token handed out before no longer logs in. An error once
/// the session has ended. `screen` 1 is the second monitor of a session across two windows; the
/// default 0 shows the session's whole desktop, or its first monitor.
#[tauri::command]
pub(crate) fn rdp_session_attach(
    window: tauri::Window,
    sessions: State<'_, RdpSessions>,
    session_id: String,
    screen: Option<u8>,
) -> Result<Attached, AppError> {
    window::may_reach(window.label(), &session_id)?;
    let screen = usize::from(screen.unwrap_or(0));
    window::may_show(window.label(), screen)?;
    sessions.attach(&session_id, screen)
}

/// Saves the desktop of session `session_id` as a PNG where the user chooses; `false` once the
/// dialog is cancelled. The picture is the one of the moment of the call, not of the save.
#[tauri::command]
pub(crate) async fn rdp_session_screenshot(
    window: tauri::Window,
    sessions: State<'_, RdpSessions>,
    session_id: String,
) -> Result<bool, AppError> {
    let frames = sessions.frames(&session_id)?;
    let name = format!("rdp-{}.png", chrono::Local::now().format("%Y%m%d-%H%M%S"));
    let chosen = tauri::async_runtime::spawn_blocking(move || {
        let png = frames.png().map_err(AppError::Validation)?;
        let Some(chosen) = window
            .dialog()
            .file()
            .set_parent(&window)
            .set_file_name(name)
            .add_filter("PNG", &["png"])
            .blocking_save_file()
        else {
            return Ok(false);
        };
        let path = chosen
            .into_path()
            .map_err(|error| AppError::Validation(error.to_string()))?;
        std::fs::write(path, png)?;
        Ok(true)
    })
    .await
    .map_err(|error| {
        AppError::Io(std::io::Error::other(format!(
            "the screenshot did not finish: {error}"
        )))
    })?;
    chosen
}

/// What session `session_id` connected to; an error once it has ended.
#[tauri::command]
pub(crate) fn rdp_session_info(
    sessions: State<'_, RdpSessions>,
    session_id: String,
) -> Result<SessionInfo, AppError> {
    sessions.info(&session_id)
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;
    use std::sync::mpsc;

    use super::tofu::{CertPolicy, CertProblem};
    use super::*;
    use crate::models::{ConnectionOptions, RdpAudio, RdpConnectionOptions};
    use crate::password::save_password_keyring;
    use crate::port_registry::PortRegistry;
    use crate::workspace::{EnteredWorkspace, Workspace, WorkspaceId};

    /// A directory of its own for one test case under the system temp dir, gone with the guard.
    struct Scratch(PathBuf);

    impl Scratch {
        fn new(case: &str) -> Self {
            let dir =
                std::env::temp_dir().join(format!("ah-rdp-embedded-{case}-{}", std::process::id()));
            let _ = std::fs::remove_dir_all(&dir);
            std::fs::create_dir_all(&dir).unwrap();
            Scratch(dir)
        }
    }

    impl Drop for Scratch {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn entered(id: &str) -> EnteredWorkspace {
        workspace::enter(Workspace {
            id: WorkspaceId::parse(id).unwrap(),
            name: id.to_string(),
            legacy_keys: false,
        })
    }

    fn rdp(host: &str, port: Option<u16>) -> Connection {
        Connection {
            id: "c1".to_string(),
            name: "rdp".to_string(),
            kind: ConnectionKind::Rdp,
            host: Some(host.to_string()),
            port,
            username: Some("e2e".to_string()),
            domain: Some("LAB".to_string()),
            key_path: None,
            url: None,
            notes: None,
            tags: Vec::new(),
            trust_cert: false,
            last_used: None,
            server_id: None,
            options: None,
        }
    }

    fn mapping(connection_id: &str) -> TunnelMapping {
        TunnelMapping {
            id: "t1".to_string(),
            server_id: "s1".to_string(),
            tunnel_type: "stcp".to_string(),
            protocol: "rdp".to_string(),
            local_port: 3389,
            visitor_port: Some(6000),
            custom_domains: None,
            connection_id: Some(connection_id.to_string()),
            enabled: true,
            name: "lab-rdp".to_string(),
        }
    }

    /// Pins in memory; `None` fails every read, like a locked keyring.
    struct Pins(Option<HashMap<String, String>>);

    impl PinStore for Pins {
        fn load(&self, identity: &str) -> Result<Option<String>, ()> {
            match &self.0 {
                Some(pins) => Ok(pins.get(identity).cloned()),
                None => Err(()),
            }
        }
        fn store(&self, _identity: &str, _fingerprint: &str) -> Result<(), ()> {
            Err(())
        }
    }

    fn no_pins() -> Pins {
        Pins(Some(HashMap::new()))
    }

    fn refusal(result: Result<Target, AppError>) -> String {
        match result {
            Ok(_) => panic!("the start was not refused"),
            Err(error) => error.to_string(),
        }
    }

    #[test]
    fn start_refuses_another_kind_of_connection() {
        let scratch = Scratch::new("kind");
        let _ws = entered("w-0000000a");
        let mut ssh = rdp("192.0.2.10", None);
        ssh.kind = ConnectionKind::Ssh;
        let refused = refusal(prepare(&scratch.0, &ssh, &[], &[], &[], &no_pins(), None));
        assert!(refused.contains("needs an RDP connection"), "{refused}");
    }

    #[test]
    fn start_refuses_the_port_of_another_workspace() {
        let scratch = Scratch::new("foreign-port");
        PortRegistry::new(&scratch.0).seed("w-0000000b", &[("db-visitor", 6000, 23005)]);
        let _ws = entered("w-0000000a");
        let listed = rdp("127.0.0.1", Some(23005));
        let refused = refusal(prepare(
            &scratch.0,
            &listed,
            &[],
            &[],
            &[],
            &no_pins(),
            None,
        ));
        assert!(
            refused.starts_with("port 23005 on this machine"),
            "{refused}"
        );
    }

    #[test]
    fn start_refuses_a_tunnelled_connection_the_server_does_not_list() {
        let scratch = Scratch::new("source");
        let _ws = entered("w-0000000a");
        let listed = rdp("192.0.2.10", None);
        let mut moved = listed.clone();
        moved.host = Some("198.51.100.7".to_string());
        for connections in [Vec::new(), vec![moved]] {
            let refused = refusal(prepare(
                &scratch.0,
                &listed,
                &[mapping("c1")],
                &connections,
                &[],
                &no_pins(),
                None,
            ));
            assert!(refused.contains("does not match"), "{refused}");
        }
    }

    #[test]
    fn start_refuses_when_the_pin_cannot_be_read() {
        let scratch = Scratch::new("pin");
        let _ws = entered("w-0000000a");
        let listed = rdp("192.0.2.10", None);
        let refused = refusal(prepare(
            &scratch.0,
            &listed,
            &[],
            &[],
            &[],
            &Pins(None),
            None,
        ));
        assert!(refused.contains("could not be read"), "{refused}");
    }

    #[test]
    fn start_refuses_without_a_stored_password() {
        let scratch = Scratch::new("no-password");
        let _keyring = crate::keyring_store::memory();
        let _ws = entered("w-0000000a");
        let listed = rdp("192.0.2.10", None);
        let refused = refusal(prepare(
            &scratch.0,
            &listed,
            &[],
            &[],
            &[],
            &no_pins(),
            None,
        ));
        assert!(refused.contains("no password is stored"), "{refused}");
    }

    #[test]
    fn start_takes_the_stored_password_and_the_pin() {
        let scratch = Scratch::new("target");
        let _keyring = crate::keyring_store::memory();
        let _ws = entered("w-0000000a");
        let listed = rdp("192.0.2.10", Some(3390));
        save_password_keyring(&scratch.0, &listed, "secret").unwrap();
        let identity = "rdp/w-0000000a/192.0.2.10:3390".to_string();
        let pins = Pins(Some(HashMap::from([(identity.clone(), "ab".repeat(32))])));
        let target = prepare(&scratch.0, &listed, &[], &[], &[], &pins, None).unwrap();
        assert_eq!(target.destination.to_string(), "192.0.2.10:3390");
        assert_eq!(target.username, "e2e");
        assert_eq!(target.domain.as_deref(), Some("LAB"));
        assert_eq!(target.password.as_str(), "secret");
        assert_eq!(
            target.policy,
            CertPolicy::Pinned {
                identity,
                pin: Some("ab".repeat(32)),
                endpoint: "192.0.2.10:3390".to_string(),
            }
        );
    }

    #[test]
    fn start_takes_a_typed_password_before_the_stored_one_and_stores_none() {
        let scratch = Scratch::new("typed");
        let _keyring = crate::keyring_store::memory();
        let _ws = entered("w-0000000a");
        let listed = rdp("192.0.2.10", None);
        let typed = Some(Zeroizing::new("typed".to_string()));
        let target = prepare(&scratch.0, &listed, &[], &[], &[], &no_pins(), typed).unwrap();
        assert_eq!(target.password.as_str(), "typed");
        assert_eq!(load_password_keyring(&scratch.0, &listed).unwrap(), None);

        save_password_keyring(&scratch.0, &listed, "stored").unwrap();
        let typed = Some(Zeroizing::new("typed".to_string()));
        let target = prepare(&scratch.0, &listed, &[], &[], &[], &no_pins(), typed).unwrap();
        assert_eq!(target.password.as_str(), "typed");
        assert_eq!(
            load_password_keyring(&scratch.0, &listed)
                .unwrap()
                .as_deref(),
            Some("stored")
        );
    }

    #[test]
    fn an_empty_typed_password_is_none() {
        let scratch = Scratch::new("typed-empty");
        let _keyring = crate::keyring_store::memory();
        let _ws = entered("w-0000000a");
        let listed = rdp("192.0.2.10", None);
        let empty = Some(Zeroizing::new(String::new()));
        let refused = refusal(prepare(
            &scratch.0,
            &listed,
            &[],
            &[],
            &[],
            &no_pins(),
            empty,
        ));
        assert!(refused.contains("no password is stored"), "{refused}");
    }

    #[test]
    fn a_typed_password_passes_no_check_the_stored_one_must() {
        let scratch = Scratch::new("typed-checks");
        PortRegistry::new(&scratch.0).seed("w-0000000b", &[("db-visitor", 6000, 23005)]);
        let _keyring = crate::keyring_store::memory();
        let _ws = entered("w-0000000a");
        let typed = || Some(Zeroizing::new("typed".to_string()));
        let foreign = rdp("127.0.0.1", Some(23005));
        let refused = refusal(prepare(
            &scratch.0,
            &foreign,
            &[],
            &[],
            &[],
            &no_pins(),
            typed(),
        ));
        assert!(
            refused.starts_with("port 23005 on this machine"),
            "{refused}"
        );
        let listed = rdp("192.0.2.10", None);
        let refused = refusal(prepare(
            &scratch.0,
            &listed,
            &[mapping("c1")],
            &[],
            &[],
            &no_pins(),
            typed(),
        ));
        assert!(refused.contains("does not match"), "{refused}");
        let refused = refusal(prepare(
            &scratch.0,
            &listed,
            &[],
            &[],
            &[],
            &Pins(None),
            typed(),
        ));
        assert!(refused.contains("could not be read"), "{refused}");
        let mut ssh = listed.clone();
        ssh.kind = ConnectionKind::Ssh;
        let refused = refusal(prepare(
            &scratch.0,
            &ssh,
            &[],
            &[],
            &[],
            &no_pins(),
            typed(),
        ));
        assert!(refused.contains("needs an RDP connection"), "{refused}");
    }

    #[test]
    fn session_info_names_the_stored_target_the_tunnel_and_the_pin() {
        let scratch = Scratch::new("info");
        let _keyring = crate::keyring_store::memory();
        let _ws = entered("w-0000000a");
        let listed = rdp("192.0.2.10", Some(3390));
        save_password_keyring(&scratch.0, &listed, "secret").unwrap();
        let identity = "rdp/w-0000000a/192.0.2.10:3390".to_string();
        let pins = Pins(Some(HashMap::from([(identity, "ab".repeat(32))])));
        let target = prepare(&scratch.0, &listed, &[], &[], &[], &pins, None).unwrap();
        let tunneled = ResolvedConnection {
            connection: rdp("127.0.0.1", Some(6000)),
            via_tunnel: true,
            tunnel_name: Some("lab-rdp".to_string()),
            tunnel_type: Some("stcp".to_string()),
        };
        let info = session_info(&listed, &tunneled, &target);
        assert_eq!(
            serde_json::to_value(&info).unwrap(),
            serde_json::json!({
                "target": "192.0.2.10:3390",
                "via_tunnel": true,
                "tunnel": "lab-rdp",
                "credssp": true,
                "certificate": "pinned",
                "fingerprint": "ab".repeat(32),
            })
        );

        let six = rdp("2001:db8::10", None);
        assert_eq!(
            session_info(&six, &tunneled, &target).target,
            "[2001:db8::10]:3389"
        );

        let direct = ResolvedConnection {
            connection: listed.clone(),
            via_tunnel: false,
            tunnel_name: None,
            tunnel_type: None,
        };
        let mut trusting = target;
        trusting.policy = CertPolicy::TrustAll;
        trusting.credssp = false;
        assert_eq!(
            serde_json::to_value(session_info(&listed, &direct, &trusting)).unwrap(),
            serde_json::json!({
                "target": "192.0.2.10:3390",
                "via_tunnel": false,
                "credssp": false,
                "certificate": "trust_all",
            })
        );
    }

    #[test]
    fn session_takes_its_own_performance_profile_before_the_settings() {
        let mut listed = rdp("192.0.2.10", None);
        assert_eq!(
            performance(&listed, RdpPerformanceProfile::Broadband),
            RdpPerformanceProfile::Broadband
        );
        listed.options = Some(ConnectionOptions {
            rdp: Some(RdpConnectionOptions {
                performance_profile: Some(RdpPerformanceProfile::Low),
                ..Default::default()
            }),
            ..Default::default()
        });
        assert_eq!(
            performance(&listed, RdpPerformanceProfile::Broadband),
            RdpPerformanceProfile::Low
        );
    }

    #[test]
    fn sessions_keep_picture_and_info_until_the_session_ends() {
        let sessions = RdpSessions::default();
        let frames = Frames::default();
        let (stop, mut stopped) = oneshot::channel();
        let id = sessions.add(stop, frames);
        assert!(sessions.frames(&id).is_ok());
        // Between the start and the end of `rdp_session_start` there is no info yet.
        assert!(sessions.info(&id).is_err());
        let info = SessionInfo {
            target: "192.0.2.10:3389".to_string(),
            via_tunnel: false,
            tunnel: None,
            credssp: true,
            certificate: "trust_all",
            fingerprint: None,
        };
        let tokens = || frame_ws::FrameServer::bind().unwrap().tokens();
        sessions.started(&id, info.clone(), 4711, tokens());
        assert_eq!(sessions.info(&id).unwrap(), info);

        sessions.stop(&id);
        assert!(stopped.try_recv().is_ok());
        assert!(sessions.frames(&id).is_err());
        assert!(sessions.info(&id).is_err());
        // A late start of an ended session brings no info back.
        sessions.started(&id, info, 4711, tokens());
        assert!(sessions.info(&id).is_err());
        assert!(sessions.attach(&id, 0).is_err());
    }

    #[test]
    fn attach_hands_out_a_fresh_token_for_a_started_session_only() {
        let sessions = RdpSessions::default();
        assert!(
            sessions.attach("rdp-1", 0).is_err(),
            "attached to no session"
        );
        let (stop, _stopped) = oneshot::channel();
        let id = sessions.add(stop, Frames::default());
        assert!(
            sessions.attach(&id, 0).is_err(),
            "attached before the start"
        );

        let server = frame_ws::FrameServer::bind().unwrap();
        let first = server.token();
        let info = SessionInfo {
            target: "192.0.2.10:3389".to_string(),
            via_tunnel: false,
            tunnel: None,
            credssp: true,
            certificate: "trust_all",
            fingerprint: None,
        };
        sessions.started(&id, info, 4711, server.tokens());
        let one = sessions.attach(&id, 0).unwrap();
        let two = sessions.attach(&id, 0).unwrap();
        assert_eq!((one.ws_port, two.ws_port), (4711, 4711));
        assert_eq!(one.token.len(), 64);
        assert!(
            one.token != first && two.token != one.token,
            "a token came twice"
        );
        assert_eq!(
            serde_json::to_value(&two).unwrap(),
            serde_json::json!({ "ws_port": 4711, "token": two.token })
        );
        // The second screen gets a token of its own; there is no third.
        let second = sessions.attach(&id, 1).unwrap();
        assert!(second.token != two.token);
        assert!(matches!(
            sessions.attach(&id, 2),
            Err(AppError::Validation(_))
        ));
    }

    #[test]
    fn start_takes_the_audio_of_the_connection_options() {
        let scratch = Scratch::new("audio");
        let _keyring = crate::keyring_store::memory();
        let _ws = entered("w-0000000a");
        let mut listed = rdp("192.0.2.10", None);
        save_password_keyring(&scratch.0, &listed, "secret").unwrap();
        let target = prepare(&scratch.0, &listed, &[], &[], &[], &no_pins(), None).unwrap();
        assert_eq!(target.audio, None);
        listed.options = Some(ConnectionOptions {
            ssh: None,
            rdp: Some(RdpConnectionOptions {
                audio: Some(RdpAudio::Off),
                ..Default::default()
            }),
        });
        let target = prepare(&scratch.0, &listed, &[], &[], &[], &no_pins(), None).unwrap();
        assert_eq!(target.audio, Some(RdpAudio::Off));
    }

    fn with_rdp(options: RdpConnectionOptions) -> Connection {
        let mut listed = rdp("192.0.2.10", None);
        listed.options = Some(ConnectionOptions {
            ssh: None,
            rdp: Some(options),
        });
        listed
    }

    #[test]
    fn start_leaves_a_gateway_or_printers_to_the_os_client() {
        let scratch = Scratch::new("os-client");
        let _keyring = crate::keyring_store::memory();
        let _ws = entered("w-0000000a");
        let cases = [
            (
                RdpConnectionOptions {
                    gateway: Some("rdgw.example.org:443".to_string()),
                    ..Default::default()
                },
                "RD gateway",
            ),
            (
                RdpConnectionOptions {
                    printers: Some(true),
                    ..Default::default()
                },
                "printers",
            ),
        ];
        for (options, reason) in cases {
            let listed = with_rdp(options);
            save_password_keyring(&scratch.0, &listed, "secret").unwrap();
            match prepare(&scratch.0, &listed, &[], &[], &[], &no_pins(), None) {
                Err(error) => {
                    assert_eq!(error.code(), "ERR_RDP_OS_CLIENT", "{error}");
                    assert!(error.to_string().contains(reason), "{error}");
                }
                Ok(_) => panic!("the start with {reason} was not refused"),
            }
        }
        let listed = with_rdp(RdpConnectionOptions {
            printers: Some(false),
            ..Default::default()
        });
        save_password_keyring(&scratch.0, &listed, "secret").unwrap();
        assert!(prepare(&scratch.0, &listed, &[], &[], &[], &no_pins(), None).is_ok());
    }

    #[test]
    fn start_goes_without_credssp_only_when_nla_is_off() {
        let scratch = Scratch::new("nla");
        let _keyring = crate::keyring_store::memory();
        let _ws = entered("w-0000000a");
        for (nla, credssp) in [(None, true), (Some(true), true), (Some(false), false)] {
            let listed = with_rdp(RdpConnectionOptions {
                nla,
                ..Default::default()
            });
            save_password_keyring(&scratch.0, &listed, "secret").unwrap();
            let target = prepare(&scratch.0, &listed, &[], &[], &[], &no_pins(), None).unwrap();
            assert_eq!(target.credssp, credssp, "nla {nla:?}");
        }
        let plain = rdp("192.0.2.10", None);
        save_password_keyring(&scratch.0, &plain, "secret").unwrap();
        assert!(
            prepare(&scratch.0, &plain, &[], &[], &[], &no_pins(), None)
                .unwrap()
                .credssp
        );
    }

    fn with_drives(drives: Option<bool>) -> Connection {
        let mut listed = rdp("192.0.2.10", None);
        listed.options = Some(ConnectionOptions {
            ssh: None,
            rdp: Some(RdpConnectionOptions {
                drives,
                ..Default::default()
            }),
        });
        listed
    }

    #[test]
    fn start_shares_the_downloads_folder_only_when_the_options_ask() {
        let scratch = Scratch::new("drive");
        let downloads = Some(scratch.0.clone());
        for listed in [
            rdp("192.0.2.10", None),
            with_drives(None),
            with_drives(Some(false)),
        ] {
            assert_eq!(
                shared_drive(&listed, downloads.clone(), &Kept::default()),
                Ok(None)
            );
        }
        assert_eq!(
            shared_drive(&with_drives(Some(true)), downloads, &Kept::default()),
            Ok(Some(shared(&scratch.0)))
        );
    }

    #[test]
    fn start_names_why_it_shares_no_drive() {
        let wanted = with_drives(Some(true));
        let reason = shared_drive(&wanted, None, &Kept::default()).unwrap_err();
        assert_eq!(reason, "there is no Downloads folder");
        let scratch = Scratch::new("drive-gone");
        let gone = scratch.0.join("Downloads");
        assert!(shared_drive(&wanted, Some(gone), &Kept::default()).is_err());
    }

    #[test]
    fn start_shares_no_folder_that_is_or_holds_a_kept_one() {
        let wanted = with_drives(Some(true));
        let scratch = Scratch::new("drive-kept");
        let home = scratch.0.join("home");
        let app_data = home.join(".local").join("share").join("adminhelper");
        let downloads = home.join("Downloads");
        std::fs::create_dir_all(&app_data).unwrap();
        std::fs::create_dir_all(&downloads).unwrap();
        let below = app_data.join("workspaces");
        std::fs::create_dir_all(&below).unwrap();
        let kept = Kept {
            home: Some(home.clone()),
            private: vec![app_data.clone()],
        };
        for refused in [
            home.clone(),
            home.join("."),
            downloads.join(".."),
            home.join(".local"),
            app_data.clone(),
            below,
            scratch.0.clone(),
        ] {
            assert!(
                shared_drive(&wanted, Some(refused.clone()), &kept).is_err(),
                "shared {refused:?}"
            );
        }
        let root = std::path::Path::new(&std::path::MAIN_SEPARATOR.to_string())
            .canonicalize()
            .unwrap();
        assert_eq!(
            shared_drive(&wanted, Some(root), &Kept::default()),
            Err("the Downloads folder is a root".into())
        );
        assert_eq!(
            shared_drive(&wanted, Some(downloads.clone()), &kept),
            Ok(Some(shared(&downloads)))
        );
    }

    /// The path `shared_drive` gives for `folder`: resolved, on Windows without `\\?\`.
    fn shared(folder: &std::path::Path) -> PathBuf {
        let folder = folder.canonicalize().unwrap();
        if cfg!(windows) {
            without_verbatim(&folder.to_string_lossy()).map_or(folder, PathBuf::from)
        } else {
            folder
        }
    }

    #[test]
    fn a_shared_folder_goes_without_the_verbatim_prefix() {
        assert_eq!(
            without_verbatim(r"\\?\C:\Users\a\Downloads").as_deref(),
            Some(r"C:\Users\a\Downloads")
        );
        assert_eq!(
            without_verbatim(r"\\?\UNC\server\share\Downloads").as_deref(),
            Some(r"\\server\share\Downloads")
        );
        assert_eq!(without_verbatim("/home/a/Downloads"), None);
        assert_eq!(without_verbatim(r"C:\Users"), None);
    }

    #[test]
    fn the_start_names_a_missing_drive_only() {
        let started = |notice| {
            serde_json::to_value(Started {
                session_id: "rdp-1".into(),
                ws_port: 1,
                token: "t".into(),
                notice,
            })
            .unwrap()
        };
        assert!(started(None).get("notice").is_none());
        assert_eq!(
            started(Some("drive_unavailable"))["notice"],
            "drive_unavailable"
        );
    }

    #[test]
    fn stop_of_an_unknown_session_is_no_error() {
        let sessions = RdpSessions::default();
        sessions.stop("rdp-1");
        let (stop, mut stopped) = oneshot::channel();
        let id = sessions.add(stop, Frames::default());
        sessions.stop("rdp-99");
        assert!(stopped.try_recv().is_err());
        sessions.stop(&id);
        assert_eq!(stopped.try_recv(), Ok(()));
        sessions.stop(&id);
    }

    #[test]
    fn stop_all_ends_every_session() {
        let sessions = RdpSessions::default();
        assert!(sessions.stop_all().is_empty());
        let (stop1, mut stopped1) = oneshot::channel();
        let (stop2, mut stopped2) = oneshot::channel();
        let first = sessions.add(stop1, Frames::default());
        let second = sessions.add(stop2, Frames::default());
        let mut ended = sessions.stop_all();
        ended.sort();
        assert_eq!(ended, vec![first, second]);
        assert_eq!(stopped1.try_recv(), Ok(()));
        assert_eq!(stopped2.try_recv(), Ok(()));
        assert!(lock(&sessions.running).is_empty());
    }

    #[test]
    fn the_last_phase_ends_the_session() {
        let sessions = RdpSessions::default();
        let (stop, _stopped) = oneshot::channel();
        let id = sessions.add(stop, Frames::default());
        let (sender, events) = mpsc::channel();
        let report = reporter(id.clone(), Arc::clone(&sessions.running), move |event| {
            sender.send(event).unwrap();
        });
        report(Report::Connecting);
        report(Report::Connected);
        assert!(lock(&sessions.running).contains_key(&id));
        report(Report::Disconnected(Code::Closed));
        assert!(lock(&sessions.running).is_empty());
        let phases: Vec<_> = events.try_iter().map(|event| event.phase).collect();
        assert_eq!(phases, ["connecting", "connected", "disconnected"]);
    }

    #[test]
    fn phase_events_carry_only_their_fields() {
        let json = |report| serde_json::to_value(PhaseEvent::new("rdp-1", report)).unwrap();
        assert_eq!(
            json(Report::Connected),
            serde_json::json!({ "session_id": "rdp-1", "phase": "connected" })
        );
        assert_eq!(
            json(Report::Failed(Code::Watchdog)),
            serde_json::json!({ "session_id": "rdp-1", "phase": "failed", "code": "watchdog" })
        );
        let problem = CertProblem {
            identity: "rdp/w-0000000a/192.0.2.10:3389".to_string(),
            fingerprint: "ab".repeat(32),
            reason: CertReason::Changed,
        };
        assert_eq!(
            json(Report::Certificate(problem)),
            serde_json::json!({
                "session_id": "rdp-1",
                "phase": "certificate",
                "identity": "rdp/w-0000000a/192.0.2.10:3389",
                "fingerprint": "ab".repeat(32),
                "reason": "changed",
            })
        );
    }
}
