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
pub(crate) mod session;
pub(crate) mod tofu;
pub(crate) mod watchdog;

use std::collections::HashMap;
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};

use ironrdp_client::config::Destination;
use serde::Serialize;
use tauri::{Emitter, State};
use tokio::sync::oneshot;
use zeroize::Zeroizing;

use self::session::{Code, Report, Target};
use self::tofu::{cert_policy, CertReason};
use crate::commands::{reject_foreign_port, run_with_deadline, OPEN_CONNECTION_TIMEOUT};
use crate::connection::{checked_password_source, CredentialConnection};
use crate::error::AppError;
use crate::models::{Connection, ConnectionKind, VisitorBinding};
use crate::password::{load_password_keyring, rdp_port};
use crate::session::SessionState;
use crate::tofu::{KeyringPinStore, PinStore};
use crate::tunnel::{resolve_connection, TunnelMapping};
use crate::validation::validate_connection_input;
use crate::{frpc, storage, workspace};

/// The Tauri event that carries the phases of every session.
const EVENT: &str = "rdp-session";

type Running = Arc<Mutex<HashMap<String, oneshot::Sender<()>>>>;

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|e| e.into_inner())
}

/// The sessions of this process that have not ended, each with the sender that stops it.
#[derive(Default)]
pub(crate) struct RdpSessions {
    next: AtomicU64,
    running: Running,
}

impl RdpSessions {
    fn add(&self, stop: oneshot::Sender<()>) -> String {
        let id = format!("rdp-{}", self.next.fetch_add(1, Ordering::Relaxed) + 1);
        lock(&self.running).insert(id.clone(), stop);
        id
    }

    fn stop(&self, id: &str) {
        if let Some(stop) = lock(&self.running).remove(id) {
            let _ = stop.send(());
        }
    }
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
/// comes from the keyring, the certificate pin from `pins`. Both may wait: a blocking thread only.
fn prepare(
    base: &Path,
    listed: &Connection,
    tunnels: &[TunnelMapping],
    connections: &[Connection],
    bindings: &[VisitorBinding],
    pins: &dyn PinStore,
) -> Result<Target, AppError> {
    if listed.kind != ConnectionKind::Rdp {
        return Err(AppError::Validation(
            "an embedded RDP session needs an RDP connection".to_string(),
        ));
    }
    validate_connection_input(listed)?;
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
    let password = load_password_keyring(base, source)?.ok_or_else(|| {
        AppError::Validation("no password is stored for this RDP connection".to_string())
    })?;
    Ok(Target {
        destination,
        username: username.to_string(),
        domain: domain.map(str::to_string),
        password: Zeroizing::new(password),
        policy,
        audio: listed
            .options
            .as_ref()
            .and_then(|options| options.rdp.as_ref())
            .and_then(|rdp| rdp.audio),
    })
}

/// Where the webview takes the picture of a started session from.
#[derive(Debug, Serialize)]
pub(crate) struct Started {
    session_id: String,
    ws_port: u16,
    token: String,
}

/// Starts an embedded session to `connection` as the webview lists it; the call returns once the
/// session's WebSocket listens. The phases follow as `rdp-session` events, the first one possibly
/// before this call returns: the webview listens before it calls. A refusal before the start is
/// the error of this call, as with `open_connection_stored`.
#[tauri::command]
pub(crate) async fn rdp_session_start(
    app: tauri::AppHandle,
    state: State<'_, frpc::FrpcState>,
    signed_in: State<'_, SessionState>,
    sessions: State<'_, RdpSessions>,
    connection: Connection,
) -> Result<Started, AppError> {
    let (tunnels, connections, bindings) = match signed_in.current().await {
        Some(now) => {
            let bindings = frpc::bindings_for(state.inner(), &now.signed_in());
            (now.tunnels, now.connections, bindings)
        }
        None => Default::default(),
    };
    let (stop, stopped) = oneshot::channel();
    let session_id = sessions.add(stop);
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
    let started = run_with_deadline(OPEN_CONNECTION_TIMEOUT, move |deadline| {
        let base = storage::app_data_dir(&app)?;
        let pins = KeyringPinStore::production();
        let target = prepare(&base, &connection, &tunnels, &connections, &bindings, &pins)?;
        deadline.start()?;
        session::spawn(target, stopped, report)
    })
    .await;
    match started {
        Ok((ws_port, token)) => Ok(Started {
            session_id,
            ws_port,
            token,
        }),
        Err(error) => {
            sessions.stop(&session_id);
            Err(error)
        }
    }
}

/// Ends the session `session_id` and its WebSocket; one that ended already, or never was, is no
/// error. The `disconnected` phase follows as an event.
#[tauri::command]
pub(crate) fn rdp_session_stop(sessions: State<'_, RdpSessions>, session_id: String) {
    sessions.stop(&session_id);
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
        let refused = refusal(prepare(&scratch.0, &ssh, &[], &[], &[], &no_pins()));
        assert!(refused.contains("needs an RDP connection"), "{refused}");
    }

    #[test]
    fn start_refuses_the_port_of_another_workspace() {
        let scratch = Scratch::new("foreign-port");
        PortRegistry::new(&scratch.0).seed("w-0000000b", &[("db-visitor", 6000, 23005)]);
        let _ws = entered("w-0000000a");
        let listed = rdp("127.0.0.1", Some(23005));
        let refused = refusal(prepare(&scratch.0, &listed, &[], &[], &[], &no_pins()));
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
            ));
            assert!(refused.contains("does not match"), "{refused}");
        }
    }

    #[test]
    fn start_refuses_when_the_pin_cannot_be_read() {
        let scratch = Scratch::new("pin");
        let _ws = entered("w-0000000a");
        let listed = rdp("192.0.2.10", None);
        let refused = refusal(prepare(&scratch.0, &listed, &[], &[], &[], &Pins(None)));
        assert!(refused.contains("could not be read"), "{refused}");
    }

    #[test]
    fn start_refuses_without_a_stored_password() {
        let scratch = Scratch::new("no-password");
        let _keyring = crate::keyring_store::memory();
        let _ws = entered("w-0000000a");
        let listed = rdp("192.0.2.10", None);
        let refused = refusal(prepare(&scratch.0, &listed, &[], &[], &[], &no_pins()));
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
        let target = prepare(&scratch.0, &listed, &[], &[], &[], &pins).unwrap();
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
    fn start_takes_the_audio_of_the_connection_options() {
        let scratch = Scratch::new("audio");
        let _keyring = crate::keyring_store::memory();
        let _ws = entered("w-0000000a");
        let mut listed = rdp("192.0.2.10", None);
        save_password_keyring(&scratch.0, &listed, "secret").unwrap();
        let target = prepare(&scratch.0, &listed, &[], &[], &[], &no_pins()).unwrap();
        assert_eq!(target.audio, None);
        listed.options = Some(ConnectionOptions {
            ssh: None,
            rdp: Some(RdpConnectionOptions {
                audio: Some(RdpAudio::Off),
                ..Default::default()
            }),
        });
        let target = prepare(&scratch.0, &listed, &[], &[], &[], &no_pins()).unwrap();
        assert_eq!(target.audio, Some(RdpAudio::Off));
    }

    #[test]
    fn stop_of_an_unknown_session_is_no_error() {
        let sessions = RdpSessions::default();
        sessions.stop("rdp-1");
        let (stop, mut stopped) = oneshot::channel();
        let id = sessions.add(stop);
        sessions.stop("rdp-99");
        assert!(stopped.try_recv().is_err());
        sessions.stop(&id);
        assert_eq!(stopped.try_recv(), Ok(()));
        sessions.stop(&id);
    }

    #[test]
    fn the_last_phase_ends_the_session() {
        let sessions = RdpSessions::default();
        let (stop, _stopped) = oneshot::channel();
        let id = sessions.add(stop);
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
