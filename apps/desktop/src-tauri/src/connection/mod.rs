// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Passwords flow through here to child processes. Memory that held one is overwritten here only
// by safe means (`zeroize`), so that no code here claims more about it than Rust upholds.
#![forbid(unsafe_code)]

pub mod rdp;
pub mod rdp_logic;
pub mod ssh;
pub mod web;

use crate::error::AppError;
use crate::models::{ClientInfo, Connection, ConnectionKind, RdpOptions, VisitorBinding};
use crate::tunnel::{mapping_of, resolve_connection, TunnelMapping};
use crate::validation::validate_connection_input;
use std::sync::atomic::{AtomicU8, Ordering};
use std::time::{Duration, Instant};

/// What the user reads when opening a connection ran out of time.
pub const TIMEOUT_MESSAGE: &str =
    "Verbindungsaufbau: Zeitueberschreitung (Server nicht erreichbar oder haengt)";

/// The deadline of opening one connection, shared by the command that waits and the work that
/// opens. The work claims the start right before its first visible effect (a window, a
/// process); the command gives up only while nothing has started. So after the timeout
/// message no window opens any more, and a start that won the race is waited for.
pub struct Deadline {
    at: Instant,
    state: AtomicU8,
}

const OPEN: u8 = 0;
const STARTED: u8 = 1;
const EXPIRED: u8 = 2;

impl Deadline {
    pub fn new(timeout: Duration) -> Self {
        Self {
            at: Instant::now() + timeout,
            state: AtomicU8::new(OPEN),
        }
    }

    /// Claims the start: `Ok` while open and in time (and again once started), the timeout
    /// error once expired or past the deadline.
    pub fn start(&self) -> Result<(), AppError> {
        if Instant::now() >= self.at {
            let _ = self.expire();
        }
        match self
            .state
            .compare_exchange(OPEN, STARTED, Ordering::AcqRel, Ordering::Acquire)
        {
            Ok(_) | Err(STARTED) => Ok(()),
            Err(_) => Err(AppError::Connection(TIMEOUT_MESSAGE.to_string())),
        }
    }

    /// Expires an open deadline; false once the work has started.
    pub(crate) fn expire(&self) -> bool {
        self.state
            .compare_exchange(OPEN, EXPIRED, Ordering::AcqRel, Ordering::Acquire)
            .is_ok()
            || self.state.load(Ordering::Acquire) == EXPIRED
    }

    /// The time left, zero once past. Only the xfreerdp credential check (Unix) reads it.
    #[cfg_attr(not(unix), allow(dead_code))]
    pub fn remaining(&self) -> Duration {
        self.at.saturating_duration_since(Instant::now())
    }
}

#[allow(clippy::too_many_arguments)]
pub fn open_connection(
    connection: &Connection,
    password: Option<&str>,
    client: Option<&ClientInfo>,
    rdp: RdpOptions,
    ui_language: Option<&str>,
    correlation_id: &str,
    app: &tauri::AppHandle,
    deadline: &Deadline,
) -> Result<(), AppError> {
    validate_connection_input(connection)?;
    // On Windows a typed password goes to no store, not even for the start, and mstsc asks for
    // it as before R-0431: only a stored one holds a `TERMSRV/…` entry for the start.
    #[cfg(target_os = "windows")]
    let password: Option<&str> = {
        let _ = password;
        None
    };
    match connection.kind {
        ConnectionKind::Ssh => {
            deadline.start()?;
            ssh::open_ssh(connection)
        }
        ConnectionKind::Rdp => rdp::open_rdp(
            connection,
            password,
            client,
            rdp,
            ui_language,
            correlation_id,
            app,
            deadline,
        ),
        ConnectionKind::Web => {
            deadline.start()?;
            web::open_web(connection)
        }
    }
}

/// The connection as listed, whose keyring entry holds the stored password (without one, the
/// opened connection), and what Rust checks it against: the tunnel mappings and the server's
/// connections the session fetched, and where the visitors of the running frpc listen, all
/// read when the connection opens.
pub struct CredentialConnection<'a> {
    pub connection: Option<&'a Connection>,
    pub tunnels: &'a [TunnelMapping],
    pub connections: &'a [Connection],
    pub bindings: &'a [VisitorBinding],
}

#[allow(clippy::too_many_arguments)]
pub fn open_connection_stored(
    app: &tauri::AppHandle,
    connection: &Connection,
    credential: CredentialConnection<'_>,
    client: Option<&ClientInfo>,
    rdp: RdpOptions,
    ui_language: Option<&str>,
    correlation_id: &str,
    deadline: &Deadline,
) -> Result<(), AppError> {
    validate_connection_input(connection)?;
    let source = checked_password_source(connection, &credential)?;
    match connection.kind {
        ConnectionKind::Rdp => open_rdp_with_stored_password(
            app,
            connection,
            source,
            // The resolution the check took the opened connection for: a mapping of the
            // connection counts, with a running visitor or without.
            resolve_connection(source, credential.tunnels, credential.bindings).via_tunnel,
            client,
            rdp,
            ui_language,
            correlation_id,
            deadline,
        ),
        _ => open_connection(
            connection,
            None,
            client,
            rdp,
            ui_language,
            correlation_id,
            app,
            deadline,
        ),
    }
}

/// The connection whose keyring entry holds the stored RDP password. A tunnelled
/// target arrives resolved to `127.0.0.1:<local port>`, but the UI checks and
/// saves the password under the connection as listed, so the caller passes
/// that one separately; without it the opened connection is its own source.
fn stored_password_source<'a>(
    connection: &'a Connection,
    credential_connection: Option<&'a Connection>,
) -> &'a Connection {
    credential_connection.unwrap_or(connection)
}

/// The source of the stored password for opening `connection`, once
/// `check_credential_connection` took it for `connection`. The check runs without a
/// credential connection, too: the opened one then has to be its own resolution.
fn checked_password_source<'a>(
    connection: &'a Connection,
    credential: &CredentialConnection<'a>,
) -> Result<&'a Connection, AppError> {
    let source = stored_password_source(connection, credential.connection);
    validate_connection_input(source)?;
    check_credential_connection(
        connection,
        source,
        credential.tunnels,
        credential.connections,
        credential.bindings,
    )?;
    Ok(source)
}

/// The credential connection is accepted only as the same connection as the
/// opened one: same id, kind, username and domain, and the opened one trusts
/// no certificate the credential connection does not. The opened one must then
/// point at exactly the host and port Rust resolves the credential connection
/// to with `tunnels` and `bindings` (`tunnel::resolve_connection`). Without a
/// listening visitor for it, that is the credential connection's own target.
///
/// A mapping belongs to the server's connection of its id, so through a mapping
/// the credential connection is taken only as one of `connections` with that id,
/// in kind, host and port (user and domain may come from the password prompt),
/// and the opened one trusts no certificate that one does not.
fn check_credential_connection(
    connection: &Connection,
    credential: &Connection,
    tunnels: &[TunnelMapping],
    connections: &[Connection],
    bindings: &[VisitorBinding],
) -> Result<(), AppError> {
    let same_identity = connection.id == credential.id
        && connection.kind == credential.kind
        && connection.username == credential.username
        && connection.domain == credential.domain;
    let same_trust = !connection.trust_cert || credential.trust_cert;
    let server_connection = || {
        mapping_of(credential, tunnels).is_none()
            || connections.iter().any(|server| {
                server.id == credential.id
                    && server.kind == credential.kind
                    && server.host == credential.host
                    && server.port == credential.port
                    && (!connection.trust_cert || server.trust_cert)
            })
    };
    let resolved_target = || {
        let resolved = resolve_connection(credential, tunnels, bindings).connection;
        connection.host == resolved.host && connection.port == resolved.port
    };
    if same_identity && same_trust && server_connection() && resolved_target() {
        Ok(())
    } else {
        Err(AppError::Validation(
            "credential connection does not match the opened connection".to_string(),
        ))
    }
}

/// Opens `connection` with the password stored for `source`; `via_tunnel` if the start goes
/// through a tunnel of `source`.
#[allow(clippy::too_many_arguments)]
fn open_rdp_with_stored_password(
    app: &tauri::AppHandle,
    connection: &Connection,
    source: &Connection,
    via_tunnel: bool,
    client: Option<&ClientInfo>,
    rdp: RdpOptions,
    ui_language: Option<&str>,
    correlation_id: &str,
    deadline: &Deadline,
) -> Result<(), AppError> {
    // Both connections are already validated and matched by the sole caller,
    // open_connection_stored. xfreerdp reads the password from its stdin; mstsc finds it in a
    // `TERMSRV/…` entry that holds it only for the start (R-0431), after a migrated workspace
    // took over the entry of a version before for a connection without a tunnel (T40).
    #[cfg(target_os = "windows")]
    let password = crate::password::load_password_for_mstsc(
        &crate::storage::app_data_dir(app)?,
        source,
        via_tunnel,
    )?;
    #[cfg(not(target_os = "windows"))]
    let password = {
        let _ = via_tunnel;
        crate::password::load_password_keyring(&crate::storage::app_data_dir(app)?, source)?
    };
    rdp::open_rdp(
        connection,
        password.as_deref(),
        client,
        rdp,
        ui_language,
        correlation_id,
        app,
        deadline,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deadline_start_in_time_is_ok_and_holds_after_the_time() {
        let deadline = Deadline::new(Duration::from_millis(50));
        assert!(deadline.start().is_ok());
        std::thread::sleep(Duration::from_millis(80));
        assert!(deadline.start().is_ok(), "a started deadline stays started");
        assert!(!deadline.expire(), "a started deadline does not expire");
    }

    #[test]
    fn deadline_start_after_the_time_fails_and_expires() {
        let deadline = Deadline::new(Duration::from_millis(10));
        std::thread::sleep(Duration::from_millis(30));
        assert!(matches!(deadline.start(), Err(AppError::Connection(m)) if m == TIMEOUT_MESSAGE));
        assert!(deadline.expire());
        assert_eq!(deadline.remaining(), Duration::ZERO);
    }

    #[test]
    fn deadline_expired_refuses_a_start_in_time() {
        let deadline = Deadline::new(Duration::from_secs(5));
        assert!(deadline.expire());
        assert!(deadline.start().is_err());
        assert!(deadline.remaining() > Duration::from_secs(4));
    }
    use crate::password::rdp_storage_key;

    fn rdp(host: &str, port: u16) -> Connection {
        Connection {
            id: "c1".into(),
            name: "T".into(),
            kind: ConnectionKind::Rdp,
            host: Some(host.into()),
            port: Some(port),
            username: Some("Admin".into()),
            domain: Some("CORP".into()),
            key_path: None,
            url: None,
            notes: None,
            tags: Vec::new(),
            trust_cert: false,
            last_used: None,
            server_id: None,
        }
    }

    /// The session's mapping of the connection `c1` to the visitor at server port 13389.
    fn mapping() -> Vec<TunnelMapping> {
        vec![TunnelMapping {
            id: "t1".into(),
            server_id: "s1".into(),
            tunnel_type: "stcp".into(),
            protocol: "rdp".into(),
            local_port: 3389,
            visitor_port: Some(13389),
            custom_domains: None,
            connection_id: Some("c1".into()),
            enabled: true,
            name: "rdp-tunnel".into(),
        }]
    }

    fn binding(name: &str, server_port: u16, local_port: u16) -> VisitorBinding {
        VisitorBinding {
            name: name.into(),
            server_port,
            local_port,
        }
    }

    /// A running frpc whose visitors listen elsewhere than their server ports.
    fn running() -> Vec<VisitorBinding> {
        vec![
            binding("rdp-visitor", 13389, 23000),
            binding("db-visitor", 6000, 23005),
        ]
    }

    /// What Rust holds when a connection opens: the session's mappings and connections and
    /// where the visitors of the running frpc listen.
    struct Held {
        tunnels: Vec<TunnelMapping>,
        connections: Vec<Connection>,
        bindings: Vec<VisitorBinding>,
    }

    impl Held {
        /// An admin's session with the mapping of `c1`, the server's `c1` at
        /// `rdp.example.com:3389`, and a running frpc.
        fn admin() -> Self {
            Self {
                tunnels: mapping(),
                connections: vec![rdp("rdp.example.com", 3389)],
                bindings: running(),
            }
        }

        /// No session (local or sync mode), no frpc.
        fn nothing() -> Self {
            Self {
                tunnels: Vec::new(),
                connections: Vec::new(),
                bindings: Vec::new(),
            }
        }

        fn check(&self, connection: &Connection, credential: &Connection) -> Result<(), AppError> {
            check_credential_connection(
                connection,
                credential,
                &self.tunnels,
                &self.connections,
                &self.bindings,
            )
        }

        /// Where the stored password for opening `connection` comes from, given `credential`
        /// or none.
        fn source<'a>(
            &'a self,
            connection: &'a Connection,
            credential: Option<&'a Connection>,
        ) -> Result<&'a Connection, AppError> {
            checked_password_source(
                connection,
                &CredentialConnection {
                    connection: credential,
                    tunnels: &self.tunnels,
                    connections: &self.connections,
                    bindings: &self.bindings,
                },
            )
        }

        /// Where Rust resolves `connection` to.
        fn resolve(&self, connection: &Connection) -> Connection {
            resolve_connection(connection, &self.tunnels, &self.bindings).connection
        }

        fn assert_rejected(&self, connection: &Connection, credential: &Connection) {
            assert!(
                matches!(
                    self.check(connection, credential),
                    Err(AppError::Validation(_))
                ),
                "{:?}:{:?} must not take the password source {:?}:{:?} \
                 ({} mappings, {} connections, bindings {:?})",
                connection.host,
                connection.port,
                credential.host,
                credential.port,
                self.tunnels.len(),
                self.connections.len(),
                self.bindings
            );
        }
    }

    /// Where `connection` points, to compare with an expected target.
    fn target(connection: &Connection) -> (Option<&str>, Option<u16>) {
        (connection.host.as_deref(), connection.port)
    }

    // The tunnel resolves a listed RDP target to the local visitor port; the
    // password lookup must still use the key the UI saved it under.
    #[test]
    fn stored_password_key_uses_credential_connection() {
        let listed = rdp("rdp.example.com", 3389);
        let resolved = rdp("127.0.0.1", 6000);
        let key = rdp_storage_key(stored_password_source(&resolved, Some(&listed)));
        assert_eq!(
            key.as_deref(),
            Some("rdp|c1|rdp.example.com|3389|admin|corp")
        );
        assert_ne!(key, rdp_storage_key(&resolved));
    }

    #[test]
    fn stored_password_key_without_credential_connection_uses_connection() {
        let direct = rdp("192.0.2.10", 3390);
        let key = rdp_storage_key(stored_password_source(&direct, None));
        assert_eq!(key.as_deref(), Some("rdp|c1|192.0.2.10|3390|admin|corp"));
    }

    #[test]
    fn stored_password_key_without_credential_connection_rejects_a_moved_visitor_target() {
        // frpc runs the visitors for server ports 13389 and 6000 on 23000 and 23005, so the
        // literal ports reach whatever else listens there. Without a credential connection the
        // opened one is its source and has to be its own resolution.
        let held = Held {
            tunnels: Vec::new(),
            ..Held::admin()
        };
        for (host, port) in [
            ("127.0.0.1", 6000),
            ("localhost", 6000),
            ("127.0.0.1", 13389),
        ] {
            let opened = rdp(host, port);
            assert_ne!(target(&held.resolve(&opened)), target(&opened));
            assert!(
                matches!(held.source(&opened, None), Err(AppError::Validation(_))),
                "{host}:{port}"
            );
        }
    }

    #[test]
    fn stored_password_key_without_credential_connection_or_frpc_takes_the_connection() {
        let listed = rdp("rdp.example.com", 3389);
        let auto = rdp("127.0.0.1", 6000);
        let direct = rdp("192.0.2.10", 3390);
        let stopped = || Held {
            bindings: Vec::new(),
            ..Held::admin()
        };
        let unmapped = || Held {
            tunnels: Vec::new(),
            ..stopped()
        };
        for (opened, held) in [
            (&listed, stopped()),
            (&auto, unmapped()),
            (&direct, unmapped()),
            (&direct, Held::nothing()),
        ] {
            match held.source(opened, None) {
                Ok(source) => assert_eq!(rdp_storage_key(source), rdp_storage_key(opened)),
                Err(err) => panic!("{:?}: {err:?}", target(opened)),
            }
        }
    }

    #[test]
    fn stored_password_key_accepts_the_resolution_through_the_mapping() {
        let held = Held::admin();
        let listed = rdp("rdp.example.com", 3389);
        let resolved = held.resolve(&listed);
        assert_eq!(target(&resolved), (Some("127.0.0.1"), Some(23000)));
        assert!(held.check(&resolved, &listed).is_ok());
        let key = rdp_storage_key(stored_password_source(&resolved, Some(&listed)));
        assert_eq!(
            key.as_deref(),
            Some("rdp|c1|rdp.example.com|3389|admin|corp")
        );
    }

    #[test]
    fn stored_password_key_accepts_a_mapping_whose_server_connection_matches() {
        // The prompt may change user and domain; the server's connection of the id still
        // names the same kind, host and port.
        let held = Held::admin();
        let mut listed = rdp("rdp.example.com", 3389);
        listed.username = Some("Other".into());
        listed.domain = None;
        let resolved = held.resolve(&listed);
        assert_eq!(target(&resolved), (Some("127.0.0.1"), Some(23000)));
        assert!(held.check(&resolved, &listed).is_ok());
    }

    #[test]
    fn stored_password_key_rejects_a_mapping_reached_through_a_foreign_id() {
        let held = Held::admin();
        // Another target under the id `c1`, whose mapping the session holds.
        let credential = rdp("a.example", 3389);
        let resolved = held.resolve(&credential);
        assert_eq!(target(&resolved), (Some("127.0.0.1"), Some(23000)));
        held.assert_rejected(&resolved, &credential);

        // The server's `c1` differs in kind or port, or the session holds no `c1`.
        let mut ssh = rdp("rdp.example.com", 3389);
        ssh.kind = ConnectionKind::Ssh;
        for connections in [vec![ssh], vec![rdp("rdp.example.com", 3390)], vec![]] {
            let held = Held {
                connections,
                ..Held::admin()
            };
            let listed = rdp("rdp.example.com", 3389);
            held.assert_rejected(&held.resolve(&listed), &listed);
        }
    }

    #[test]
    fn stored_password_key_accepts_the_literal_resolution() {
        // Without a mapping (a non-admin reads only those of the servers assigned to them) the
        // listed target names the server port of a visitor on loopback.
        let held = Held {
            tunnels: Vec::new(),
            ..Held::admin()
        };
        for host in ["127.0.0.1", "localhost"] {
            let listed = rdp(host, 6000);
            let resolved = held.resolve(&listed);
            assert_eq!(
                target(&resolved),
                (Some("127.0.0.1"), Some(23005)),
                "{host}"
            );
            assert!(held.check(&resolved, &listed).is_ok(), "{host}");
            let key = rdp_storage_key(stored_password_source(&resolved, Some(&listed)));
            assert_eq!(key, rdp_storage_key(&listed), "{host}");
        }
    }

    #[test]
    fn stored_password_key_rejects_a_loopback_port_off_the_resolution() {
        let held = Held::admin();
        let listed = rdp("rdp.example.com", 3389);
        for (host, port) in [
            // The visitor's server port, not where it listens.
            ("127.0.0.1", 13389),
            // Another visitor.
            ("127.0.0.1", 23005),
            ("127.0.0.1", 6000),
            // frpc listens on 127.0.0.1 only.
            ("::1", 23000),
            ("localhost", 23000),
            // The listed target itself, past the visitor that runs for it.
            ("rdp.example.com", 3389),
        ] {
            held.assert_rejected(&rdp(host, port), &listed);
        }

        let held = Held {
            tunnels: Vec::new(),
            ..Held::admin()
        };
        let auto = rdp("127.0.0.1", 6000);
        for (host, port) in [
            ("127.0.0.1", 6000),
            ("127.0.0.1", 23000),
            ("localhost", 23005),
        ] {
            held.assert_rejected(&rdp(host, port), &auto);
        }
    }

    #[test]
    fn stored_password_key_without_a_running_tunnel_takes_only_the_same_connection() {
        let listed = rdp("rdp.example.com", 3389);
        let auto = rdp("127.0.0.1", 6000);
        let stopped = || Held {
            bindings: Vec::new(),
            ..Held::admin()
        };
        let unmapped = || Held {
            tunnels: Vec::new(),
            ..stopped()
        };
        for (credential, held) in [
            (&listed, stopped()),
            (&listed, unmapped()),
            (&auto, unmapped()),
            (&listed, Held::nothing()),
        ] {
            assert!(
                held.check(credential, credential).is_ok(),
                "{:?}",
                target(credential)
            );
            for (host, port) in [
                ("127.0.0.1", 23000),
                ("127.0.0.1", 23005),
                ("127.0.0.1", 13389),
                ("localhost", 6000),
            ] {
                held.assert_rejected(&rdp(host, port), credential);
            }
        }
    }

    #[test]
    fn stored_password_key_takes_a_mapping_without_its_visitor_as_the_same_connection() {
        // frpc runs, but not the visitor the mapping names.
        let held = Held {
            bindings: vec![binding("db-visitor", 6000, 23005)],
            ..Held::admin()
        };
        let listed = rdp("rdp.example.com", 3389);
        assert!(held.check(&listed, &listed).is_ok());
        for (host, port) in [
            ("127.0.0.1", 23000),
            ("127.0.0.1", 13389),
            ("127.0.0.1", 23005),
        ] {
            held.assert_rejected(&rdp(host, port), &listed);
        }

        // The mapping decides before the literal target: `c1` at the server port of the
        // visitor that runs stays itself.
        let mapped_auto = rdp("127.0.0.1", 6000);
        let held = Held {
            connections: vec![mapped_auto.clone()],
            ..held
        };
        assert!(held.check(&mapped_auto, &mapped_auto).is_ok());
        held.assert_rejected(&rdp("127.0.0.1", 23005), &mapped_auto);
    }

    #[test]
    fn stored_password_key_rejects_a_resolution_frpc_changed_since() {
        let listed = rdp("rdp.example.com", 3389);
        let resolved = Held::admin().resolve(&listed);
        // frpc gave the visitor another port, or ended.
        for bindings in [vec![binding("rdp-visitor", 13389, 23001)], vec![]] {
            Held {
                bindings,
                ..Held::admin()
            }
            .assert_rejected(&resolved, &listed);
        }
    }

    #[test]
    fn stored_password_key_rejects_a_resolution_through_a_mapping_it_is_not_given() {
        let listed = rdp("rdp.example.com", 3389);
        let resolved = Held::admin().resolve(&listed);
        Held {
            tunnels: Vec::new(),
            ..Held::admin()
        }
        .assert_rejected(&resolved, &listed);
    }

    #[test]
    fn stored_password_key_rejects_a_trust_cert_its_source_does_not_have() {
        // Without a mapping: the credential connection decides.
        let direct = rdp("192.0.2.10", 3390);
        let trusting = Connection {
            trust_cert: true,
            ..direct.clone()
        };
        let held = Held::nothing();
        held.assert_rejected(&trusting, &direct);
        assert!(held.check(&trusting, &trusting).is_ok());
        assert!(held.check(&direct, &trusting).is_ok());

        // Through a mapping: the server's connection has to trust it, too.
        let listed = Connection {
            trust_cert: true,
            ..rdp("rdp.example.com", 3389)
        };
        let resolved = Held::admin().resolve(&listed);
        assert!(resolved.trust_cert);
        Held::admin().assert_rejected(&resolved, &listed);
        let held = Held {
            connections: vec![listed.clone()],
            ..Held::admin()
        };
        assert!(held.check(&resolved, &listed).is_ok());
    }

    #[test]
    fn stored_password_key_accepts_the_same_connection_without_resolution() {
        let direct = rdp("192.0.2.10", 3390);
        assert!(Held::nothing().check(&direct, &direct.clone()).is_ok());
        // frpc runs, but nothing resolves this target.
        let held = Held {
            tunnels: Vec::new(),
            ..Held::admin()
        };
        assert!(held.check(&direct, &direct.clone()).is_ok());
    }

    #[test]
    fn stored_password_key_rejects_another_target_without_a_tunnel() {
        let held = Held::nothing();
        let listed = rdp("rdp.example.com", 3389);
        held.assert_rejected(&rdp("198.51.100.7", 3389), &listed);
        held.assert_rejected(&rdp("198.51.100.7", 6000), &listed);
        // Same host, another port: not the listed target either.
        held.assert_rejected(&rdp("rdp.example.com", 6000), &listed);
    }

    /// The resolution of the listed `c1`, which the identity checks below take apart.
    fn resolved_c1() -> (Connection, Connection) {
        let listed = rdp("rdp.example.com", 3389);
        let resolved = Held::admin().resolve(&listed);
        (listed, resolved)
    }

    #[test]
    fn stored_password_key_rejects_another_id() {
        let (listed, mut resolved) = resolved_c1();
        resolved.id = "c2".into();
        Held::admin().assert_rejected(&resolved, &listed);
    }

    #[test]
    fn stored_password_key_rejects_another_username() {
        let (listed, mut resolved) = resolved_c1();
        resolved.username = Some("Other".into());
        Held::admin().assert_rejected(&resolved, &listed);
        resolved.username = None;
        Held::admin().assert_rejected(&resolved, &listed);
    }

    #[test]
    fn stored_password_key_rejects_another_kind_or_domain() {
        let (listed, mut resolved) = resolved_c1();
        resolved.kind = ConnectionKind::Ssh;
        Held::admin().assert_rejected(&resolved, &listed);
        let (listed, mut resolved) = resolved_c1();
        resolved.domain = Some("OTHER".into());
        Held::admin().assert_rejected(&resolved, &listed);
    }
}
