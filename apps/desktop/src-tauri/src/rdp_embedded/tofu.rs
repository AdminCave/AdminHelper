// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! Certificate pinning of the embedded RDP client (docs/features/arch-rdp-backend.md, condition 5).
//!
//! IronRDP takes no rustls verifier of ours, only a callback it asks once its strict check
//! (platform roots and server name) has failed. Self-signed RDP certificates, the normal case,
//! always reach the callback; a certificate a platform CA issued for the host name does not
//! (open question 1 of the spec).
//!
//! Unlike the server pin (`crate::tofu`), a first contact pins nothing by itself: the session
//! refuses and reports the fingerprint, and only `rdp_trust_certificate` stores the one the user
//! confirmed. The pin is read before the connection starts, on a thread that may wait for the
//! keyring; the callback runs inside the TLS handshake and only compares values.
//!
//! Outside the callback's reach: IronRDP accepts the certificate a redirecting server reports for
//! the target of its redirection without asking it, and IronRDP's rustls configuration writes the
//! TLS session keys to the file `SSLKEYLOGFILE` names, if that variable is set.

#![cfg_attr(not(test), expect(dead_code, reason = "the session in T5 uses it"))]

use std::sync::{Arc, Mutex};

use ironrdp_client::config::Destination;

use crate::error::AppError;
use crate::models::Connection;
use crate::tofu::{decide, fingerprint, KeyringPinStore, PinDecision, PinStore};
use crate::tunnel::ResolvedConnection;
use crate::workspace::WorkspaceId;

/// Keeps the RDP pins apart from the server pins (`host:port`) in the same keyring namespace.
const IDENTITY_PREFIX: &str = "rdp/";
const DEFAULT_RDP_PORT: u16 = 3389;
/// Room for a workspace id, a tunnel name and a DNS name; a keyring key has to end somewhere.
const MAX_IDENTITY_LEN: usize = 512;

/// The pin identity of an RDP target: `rdp/<workspace>/<host>:<port>`, or
/// `rdp/<workspace>/<tunnel>/<host>:<port>` through a tunnel. Host and port are those of the
/// stored connection, not of the local visitor: private addresses repeat between sites, and one
/// pin for the same address at two sites would refuse the second as changed. The workspace comes
/// first for the same reason: tunnel names are unique per server only, and the servers of two
/// workspaces may name a tunnel and an address alike.
pub(crate) fn pin_identity(
    workspace: &WorkspaceId,
    stored: &Connection,
    resolved: &ResolvedConnection,
) -> String {
    let host = stored
        .host
        .as_deref()
        .unwrap_or_default()
        .trim()
        .to_ascii_lowercase();
    let host = if host.contains(':') && !host.starts_with('[') {
        format!("[{host}]")
    } else {
        host
    };
    let host = segment(&host);
    let port = stored.port.unwrap_or(DEFAULT_RDP_PORT);
    match resolved.tunnel_name.as_deref() {
        Some(tunnel) if resolved.via_tunnel => format!(
            "{IDENTITY_PREFIX}{workspace}/{}/{host}:{port}",
            segment(tunnel)
        ),
        _ => format!("{IDENTITY_PREFIX}{workspace}/{host}:{port}"),
    }
}

/// A tunnel name or a host as one part of an identity: `%` and `/` become `%25` and `%2F`, so a
/// `/` in an identity only ever separates its parts.
fn segment(part: &str) -> String {
    part.replace('%', "%25").replace('/', "%2F")
}

/// What the validation callback accepts, decided before the connection starts.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum CertPolicy {
    /// The connection's `trust_cert`: accept any certificate without a dialog and leave the pins
    /// alone, like `/cert:ignore` of the OS client.
    TrustAll,
    /// Accept only the certificate pinned for `identity`, and only from `endpoint`, the
    /// destination the session connects to as IronRDP names it to the callback (`host:port`);
    /// without a pin, accept none.
    Pinned {
        identity: String,
        pin: Option<String>,
        endpoint: String,
    },
}

/// The policy for a session of `workspace` to `stored` that connects to `destination`, with the
/// pin read from `store`. A pin that cannot be read means no session (fail closed, like
/// `PinDecision::Unavailable`): taking it as "no pin" would only ask the user, but a pin the
/// keyring hides must not look like a first contact.
pub(crate) fn cert_policy(
    workspace: &WorkspaceId,
    stored: &Connection,
    resolved: &ResolvedConnection,
    destination: &Destination,
    store: &dyn PinStore,
) -> Result<CertPolicy, AppError> {
    if stored.trust_cert {
        return Ok(CertPolicy::TrustAll);
    }
    let identity = pin_identity(workspace, stored, resolved);
    let pin = store.load(&identity).map_err(|()| {
        AppError::Keyring(format!(
            "The certificate pin for {identity} could not be read from the system keyring, so \
             the session was not started. Unlock the system keyring and connect again."
        ))
    })?;
    Ok(CertPolicy::Pinned {
        identity,
        pin,
        endpoint: destination.to_string(),
    })
}

/// Why the callback refused a certificate.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum CertReason {
    /// No pin for this target yet.
    Unknown,
    /// A pin exists and the certificate differs from it.
    Changed,
}

/// A certificate the callback refused, for the `certificate` phase of the session.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct CertProblem {
    pub(crate) identity: String,
    pub(crate) fingerprint: String,
    pub(crate) reason: CertReason,
}

/// Where the callback leaves its last refusal; the session takes it once the connection failed.
#[derive(Debug, Clone, Default)]
pub(crate) struct CertReport(Arc<Mutex<Option<CertProblem>>>);

impl CertReport {
    fn put(&self, problem: CertProblem) {
        *self.0.lock().unwrap_or_else(|e| e.into_inner()) = Some(problem);
    }

    pub(crate) fn take(&self) -> Option<CertProblem> {
        self.0.lock().unwrap_or_else(|e| e.into_inner()).take()
    }
}

/// The verdict of `policy` on a certificate with the SHA-256 fingerprint `presented` that
/// `endpoint` showed. `Err(None)`: refused, with nothing the user could confirm.
fn check(policy: &CertPolicy, endpoint: &str, presented: &str) -> Result<(), Option<CertProblem>> {
    let CertPolicy::Pinned {
        identity,
        pin,
        endpoint: expected,
    } = policy
    else {
        return Ok(());
    };
    if endpoint != expected {
        // IronRDP follows a server redirection by itself and asks again for the new target; the
        // pin and a confirmation belong to the target the session was started for.
        return Err(None);
    }
    let reason = match decide(pin.as_deref(), presented) {
        PinDecision::Trust => return Ok(()),
        PinDecision::Reject => CertReason::Changed,
        // `decide` only says "capture" here; capturing is the trust command's job.
        PinDecision::Capture | PinDecision::Unavailable => CertReason::Unknown,
    };
    Err(Some(CertProblem {
        identity: identity.clone(),
        fingerprint: presented.to_string(),
        reason,
    }))
}

/// The callback for `ironrdp_client` (`with_certificate_validation_callback`). It never writes a
/// pin, so no handshake can pin a certificate the user has not seen.
pub(crate) fn validation_callback(
    policy: CertPolicy,
    report: CertReport,
) -> ironrdp_tls::CertificateValidationCallback {
    Arc::new(move |leaf_der: &[u8], endpoint: &str, _error: &str| {
        match check(&policy, endpoint, &fingerprint(leaf_der)) {
            Ok(()) => true,
            Err(Some(problem)) => {
                report.put(problem);
                false
            }
            Err(None) => {
                log::warn!(
                    "refused the RDP certificate of {endpoint}: the session was started for \
                     another target"
                );
                false
            }
        }
    })
}

/// Stores the fingerprint the user confirmed as the pin of `identity`; the webview then starts
/// the session again. Only RDP identities of this process's workspace: the server pins live in
/// the same namespace, and the pins of another workspace are not this one's to set.
#[tauri::command]
pub(crate) async fn rdp_trust_certificate(
    identity: String,
    fingerprint: String,
) -> Result<(), AppError> {
    let workspace = crate::workspace::current()?;
    // The keyring may wait (a locked Secret Service); neither the main thread nor an async
    // worker waits with it.
    tauri::async_runtime::spawn_blocking(move || {
        trust_with(
            &KeyringPinStore::production(),
            &workspace.id,
            &identity,
            &fingerprint,
        )
    })
    .await
    .map_err(|e| {
        AppError::Io(std::io::Error::other(format!(
            "the command did not finish: {e}"
        )))
    })?
}

fn trust_with(
    store: &dyn PinStore,
    workspace: &WorkspaceId,
    identity: &str,
    fingerprint: &str,
) -> Result<(), AppError> {
    if !is_rdp_identity(workspace, identity) {
        return Err(AppError::Validation(
            "not the pin identity of an RDP target of this workspace".to_string(),
        ));
    }
    if !is_fingerprint(fingerprint) {
        return Err(AppError::Validation(
            "a certificate fingerprint is 64 lower-case hex characters".to_string(),
        ));
    }
    store.store(identity, fingerprint).map_err(|()| {
        AppError::Keyring(format!(
            "The certificate pin for {identity} could not be stored in the system keyring."
        ))
    })
}

fn is_rdp_identity(workspace: &WorkspaceId, identity: &str) -> bool {
    identity.len() <= MAX_IDENTITY_LEN
        && identity
            .strip_prefix(&format!("{IDENTITY_PREFIX}{workspace}/"))
            .is_some_and(|rest| !rest.is_empty())
        && !identity.chars().any(char::is_control)
}

/// The form `crate::tofu::fingerprint` writes; an upper-case one would never match.
fn is_fingerprint(fingerprint: &str) -> bool {
    fingerprint.len() == 64
        && fingerprint
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;
    use crate::models::ConnectionKind;
    use crate::workspace::Workspace;

    const CERT_A: &[u8] = include_bytes!("../../test-fixtures/certA.der");
    const KEY_A: &[u8] = include_bytes!("../../test-fixtures/keyA.der");
    // SHA-256 of certA.der and certB.der (`sha256sum`), as in `crate::tofu`'s tests.
    const FP_A: &str = "ef8f54d07c7272f6e224d4b9d153fdca5be69a1a0ba25fb50b4bb5e2cd9462c0";
    const FP_B: &str = "65ab0fef4e64dea7c994dd335636576a09dc51d06062c967297d43658439ca36";
    /// The endpoint the handshake tests connect to, as `Destination` writes it.
    const ENDPOINT: &str = "127.0.0.1:3389";

    fn ws(id: &str) -> WorkspaceId {
        WorkspaceId::parse(id).unwrap()
    }

    fn rdp(host: &str, port: Option<u16>, trust_cert: bool) -> Connection {
        Connection {
            id: "c1".to_string(),
            name: "rdp".to_string(),
            kind: ConnectionKind::Rdp,
            host: Some(host.to_string()),
            port,
            username: Some("e2e".to_string()),
            domain: None,
            key_path: None,
            url: None,
            notes: None,
            tags: Vec::new(),
            trust_cert,
            last_used: None,
            server_id: None,
        }
    }

    fn direct(stored: &Connection) -> ResolvedConnection {
        ResolvedConnection {
            connection: stored.clone(),
            via_tunnel: false,
            tunnel_name: None,
            tunnel_type: None,
        }
    }

    /// Resolved to the local visitor of `tunnel`, the way `resolve_connection` does for STCP.
    fn tunneled(stored: &Connection, tunnel: &str) -> ResolvedConnection {
        let mut local = stored.clone();
        local.host = Some("127.0.0.1".to_string());
        local.port = Some(23000);
        ResolvedConnection {
            connection: local,
            via_tunnel: true,
            tunnel_name: Some(tunnel.to_string()),
            tunnel_type: Some("stcp".to_string()),
        }
    }

    /// The destination a session to `resolved` connects to.
    fn destination(resolved: &ResolvedConnection) -> Destination {
        Destination::from_parts(
            resolved.connection.host.clone().unwrap(),
            resolved.connection.port.unwrap_or(DEFAULT_RDP_PORT),
        )
    }

    #[derive(Default)]
    struct MemoryStore(Mutex<HashMap<String, String>>);

    impl PinStore for MemoryStore {
        fn load(&self, identity: &str) -> Result<Option<String>, ()> {
            Ok(self.0.lock().unwrap().get(identity).cloned())
        }
        fn store(&self, identity: &str, fingerprint: &str) -> Result<(), ()> {
            self.0
                .lock()
                .unwrap()
                .insert(identity.to_string(), fingerprint.to_string());
            Ok(())
        }
    }

    struct BrokenStore;

    impl PinStore for BrokenStore {
        fn load(&self, _identity: &str) -> Result<Option<String>, ()> {
            Err(())
        }
        fn store(&self, _identity: &str, _fingerprint: &str) -> Result<(), ()> {
            Err(())
        }
    }

    fn pinned(identity: &str, pin: Option<&str>, endpoint: &str) -> CertPolicy {
        CertPolicy::Pinned {
            identity: identity.to_string(),
            pin: pin.map(str::to_string),
            endpoint: endpoint.to_string(),
        }
    }

    #[test]
    fn tofu_identity_of_a_direct_target_is_its_stored_host_and_port() {
        let stored = rdp("Win01.Example.org", Some(3390), false);
        assert_eq!(
            pin_identity(&ws("kunde-a"), &stored, &direct(&stored)),
            "rdp/kunde-a/win01.example.org:3390"
        );
        let default_port = rdp("192.0.2.10", None, false);
        assert_eq!(
            pin_identity(&ws("kunde-a"), &default_port, &direct(&default_port)),
            "rdp/kunde-a/192.0.2.10:3389"
        );
    }

    #[test]
    fn tofu_identity_through_a_tunnel_names_the_tunnel_not_the_visitor() {
        let stored = rdp("192.0.2.5", Some(3389), false);
        let ws = ws("kunde-a");
        let site_a = pin_identity(&ws, &stored, &tunneled(&stored, "site-a"));
        let site_b = pin_identity(&ws, &stored, &tunneled(&stored, "site-b"));
        assert_eq!(site_a, "rdp/kunde-a/site-a/192.0.2.5:3389");
        assert_ne!(
            site_a, site_b,
            "one private address at two sites is two servers"
        );
        assert_ne!(site_a, pin_identity(&ws, &stored, &direct(&stored)));
    }

    #[test]
    fn tofu_identity_belongs_to_one_workspace() {
        let stored = rdp("192.0.2.5", Some(3389), false);
        let resolved = tunneled(&stored, "site-a");
        let a = pin_identity(&ws("kunde-a"), &stored, &resolved);
        let b = pin_identity(&ws("kunde-b"), &stored, &resolved);
        assert_ne!(a, b, "the same tunnel name and address in two workspaces");
        assert!(trust_with(&MemoryStore::default(), &ws("kunde-a"), &a, FP_A).is_ok());
        let err = trust_with(&MemoryStore::default(), &ws("kunde-a"), &b, FP_A).unwrap_err();
        assert_eq!(err.code(), "ERR_VALIDATION");
    }

    #[test]
    fn tofu_identity_escapes_the_separator_in_its_parts() {
        let ws = ws("kunde-a");
        let slash_host = rdp("a/b", None, false);
        let plain_host = rdp("b", None, false);
        let in_host = pin_identity(&ws, &slash_host, &direct(&slash_host));
        let as_tunnel = pin_identity(&ws, &plain_host, &tunneled(&plain_host, "a"));
        assert_eq!(in_host, "rdp/kunde-a/a%2Fb:3389");
        assert_eq!(as_tunnel, "rdp/kunde-a/a/b:3389");

        let slash_tunnel = pin_identity(&ws, &plain_host, &tunneled(&plain_host, "x/y"));
        assert_eq!(slash_tunnel, "rdp/kunde-a/x%2Fy/b:3389");
        // The host is lower-cased before the escape, so its `%2F` turns into `%252f`.
        let escaped_host = rdp("a%2Fb", None, false);
        let escaped = pin_identity(&ws, &escaped_host, &direct(&escaped_host));
        assert_eq!(escaped, "rdp/kunde-a/a%252fb:3389");
        assert_ne!(
            escaped, in_host,
            "an escape in the name stays apart from an escaped slash"
        );
    }

    #[test]
    fn tofu_identity_brackets_an_ipv6_host() {
        let stored = rdp("2001:DB8::10", None, false);
        assert_eq!(
            pin_identity(&ws("kunde-a"), &stored, &direct(&stored)),
            "rdp/kunde-a/[2001:db8::10]:3389"
        );
        let bracketed = rdp("[2001:db8::10]", None, false);
        assert_eq!(
            pin_identity(&ws("kunde-a"), &bracketed, &direct(&bracketed)),
            "rdp/kunde-a/[2001:db8::10]:3389"
        );
    }

    #[test]
    fn tofu_policy_reads_the_pin_before_the_session() {
        let stored = rdp("192.0.2.10", None, false);
        let resolved = direct(&stored);
        let store = MemoryStore::default();
        let ws = ws("kunde-a");
        assert_eq!(
            cert_policy(&ws, &stored, &resolved, &destination(&resolved), &store).unwrap(),
            pinned("rdp/kunde-a/192.0.2.10:3389", None, "192.0.2.10:3389")
        );
        store.store("rdp/kunde-a/192.0.2.10:3389", FP_A).unwrap();
        assert_eq!(
            cert_policy(&ws, &stored, &resolved, &destination(&resolved), &store).unwrap(),
            pinned("rdp/kunde-a/192.0.2.10:3389", Some(FP_A), "192.0.2.10:3389")
        );
    }

    #[test]
    fn tofu_policy_through_a_tunnel_expects_the_visitor_endpoint() {
        let stored = rdp("192.0.2.5", None, false);
        let resolved = tunneled(&stored, "site-a");
        let policy = cert_policy(
            &ws("kunde-a"),
            &stored,
            &resolved,
            &destination(&resolved),
            &MemoryStore::default(),
        )
        .unwrap();
        assert_eq!(
            policy,
            pinned("rdp/kunde-a/site-a/192.0.2.5:3389", None, "127.0.0.1:23000")
        );
    }

    #[test]
    fn tofu_policy_trust_cert_accepts_without_reading_the_keyring() {
        let stored = rdp("192.0.2.10", None, true);
        let resolved = direct(&stored);
        assert_eq!(
            cert_policy(
                &ws("kunde-a"),
                &stored,
                &resolved,
                &destination(&resolved),
                &BrokenStore
            )
            .unwrap(),
            CertPolicy::TrustAll
        );
    }

    #[test]
    fn tofu_policy_an_unreadable_pin_starts_no_session() {
        let stored = rdp("192.0.2.10", None, false);
        let resolved = direct(&stored);
        let err = cert_policy(
            &ws("kunde-a"),
            &stored,
            &resolved,
            &destination(&resolved),
            &BrokenStore,
        )
        .unwrap_err();
        assert_eq!(err.code(), "ERR_KEYRING");
    }

    #[test]
    fn tofu_callback_decides_the_four_cases_and_reports_refusals() {
        let identity = "rdp/kunde-a/h:3389";
        let cases = [
            (CertPolicy::TrustAll, true, None),
            (pinned(identity, Some(FP_A), ENDPOINT), true, None),
            (
                pinned(identity, None, ENDPOINT),
                false,
                Some(CertReason::Unknown),
            ),
            (
                pinned(identity, Some(FP_B), ENDPOINT),
                false,
                Some(CertReason::Changed),
            ),
        ];
        for (policy, accepted, reason) in cases {
            let report = CertReport::default();
            let callback = validation_callback(policy.clone(), report.clone());
            assert_eq!(
                callback(CERT_A, ENDPOINT, "invalid peer certificate: UnknownIssuer"),
                accepted,
                "{policy:?}"
            );
            let expected = reason.map(|reason| CertProblem {
                identity: identity.to_string(),
                fingerprint: FP_A.to_string(),
                reason,
            });
            assert_eq!(report.take(), expected, "{policy:?}");
        }
    }

    #[test]
    fn tofu_callback_refuses_another_endpoint_and_reports_nothing() {
        let identity = "rdp/kunde-a/h:3389";
        for pin in [None, Some(FP_A), Some(FP_B)] {
            let report = CertReport::default();
            let callback = validation_callback(pinned(identity, pin, ENDPOINT), report.clone());
            assert!(
                !callback(CERT_A, "198.51.100.7:3389", "UnknownIssuer"),
                "{pin:?}"
            );
            assert_eq!(report.take(), None, "{pin:?}");
        }
        let callback = validation_callback(CertPolicy::TrustAll, CertReport::default());
        assert!(callback(CERT_A, "198.51.100.7:3389", "UnknownIssuer"));
    }

    #[test]
    fn tofu_callback_never_writes_a_pin() {
        let store = MemoryStore::default();
        let stored = rdp("192.0.2.10", None, false);
        let resolved = direct(&stored);
        let policy = cert_policy(
            &ws("kunde-a"),
            &stored,
            &resolved,
            &destination(&resolved),
            &store,
        )
        .unwrap();
        let callback = validation_callback(policy, CertReport::default());
        assert!(!callback(CERT_A, "192.0.2.10:3389", "UnknownIssuer"));
        assert!(!callback(CERT_A, "192.0.2.10:3389", "UnknownIssuer"));
        assert_eq!(store.load("rdp/kunde-a/192.0.2.10:3389"), Ok(None));
    }

    #[test]
    fn tofu_trust_command_checks_identity_and_fingerprint() {
        let store = MemoryStore::default();
        let ws = ws("kunde-a");
        let refused = [
            ("192.0.2.10:3389", FP_A),
            ("rdp/", FP_A),
            ("rdp/kunde-a/", FP_A),
            ("rdp/h:3389", FP_A),
            ("rdp/kunde-b/h:3389", FP_A),
            ("rdp/kunde-a-2/h:3389", FP_A),
            ("rdp/kunde-a/h\n:3389", FP_A),
            ("rdp/kunde-a/h:3389", &FP_A[..63]),
            ("rdp/kunde-a/h:3389", &format!("{FP_A}0")),
            ("rdp/kunde-a/h:3389", &FP_A.to_ascii_uppercase()),
            ("rdp/kunde-a/h:3389", &FP_A.replace('e', "g")),
        ];
        for (identity, fingerprint) in refused {
            let err = trust_with(&store, &ws, identity, fingerprint).unwrap_err();
            assert_eq!(err.code(), "ERR_VALIDATION", "{identity} {fingerprint}");
        }
        let long = format!("rdp/kunde-a/{}:3389", "h".repeat(MAX_IDENTITY_LEN));
        assert!(trust_with(&store, &ws, &long, FP_A).is_err());
        assert!(
            store.0.lock().unwrap().is_empty(),
            "a refused pin was stored"
        );

        assert_eq!(
            trust_with(&BrokenStore, &ws, "rdp/kunde-a/h:3389", FP_A)
                .unwrap_err()
                .code(),
            "ERR_KEYRING"
        );
    }

    #[tokio::test]
    async fn tofu_trust_command_refuses_in_the_launcher() {
        let err = rdp_trust_certificate("rdp/standard/h:3389".to_string(), FP_A.to_string())
            .await
            .unwrap_err();
        assert_eq!(err.code(), "ERR_VALIDATION");
    }

    #[tokio::test]
    async fn tofu_trust_command_takes_only_its_own_workspace() {
        let _ws = crate::workspace::enter(Workspace {
            id: ws("kunde-a"),
            name: "Kunde A".to_string(),
            legacy_keys: false,
        });
        let err = rdp_trust_certificate("rdp/kunde-b/h:3389".to_string(), FP_A.to_string())
            .await
            .unwrap_err();
        assert_eq!(err.code(), "ERR_VALIDATION");
    }

    #[test]
    fn tofu_trust_command_stores_the_pin_in_the_keyring() {
        let _keyring = crate::keyring_store::memory();
        // The production store caches pins process-wide: a workspace no other test uses.
        let ws = ws("trust-command");
        let identity = "rdp/trust-command/site-77/192.0.2.77:3389";
        trust_with(&KeyringPinStore::production(), &ws, identity, FP_A).unwrap();
        assert_eq!(
            crate::keyring_store::try_get(&format!("tofu|cert|{identity}"))
                .unwrap()
                .as_deref(),
            Some(FP_A)
        );
        let stored = rdp("192.0.2.77", None, false);
        let resolved = tunneled(&stored, "site-77");
        assert_eq!(
            cert_policy(
                &ws,
                &stored,
                &resolved,
                &destination(&resolved),
                &KeyringPinStore::production()
            )
            .unwrap(),
            pinned(identity, Some(FP_A), "127.0.0.1:23000")
        );
    }

    // The real handshake: IronRDP's own TLS upgrade against an in-process server with a
    // self-signed certificate. It proves IronRDP asks our callback when its strict check
    // fails, with the endpoint it was given, that a refusal ends the handshake and a pin lets it
    // through, and that IronRDP's rustls configuration finds ring (it panics if the build has
    // no single provider).
    mod tls_handshake {
        use super::*;
        use rustls::pki_types::{CertificateDer, PrivateKeyDer, PrivatePkcs8KeyDer};
        use tokio::net::{TcpListener, TcpStream};
        use tokio_rustls::TlsAcceptor;

        const IDENTITY: &str = "rdp/kunde-a/h:3389";

        async fn handshake(policy: CertPolicy) -> (bool, Option<CertProblem>) {
            let config = rustls::ServerConfig::builder_with_provider(crate::tofu::ring_provider())
                .with_safe_default_protocol_versions()
                .unwrap()
                .with_no_client_auth()
                .with_single_cert(
                    vec![CertificateDer::from(CERT_A.to_vec())],
                    PrivateKeyDer::Pkcs8(PrivatePkcs8KeyDer::from(KEY_A.to_vec())),
                )
                .unwrap();
            let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let port = listener.local_addr().unwrap().port();
            let server = tokio::spawn(async move {
                let (tcp, _) = listener.accept().await.unwrap();
                TlsAcceptor::from(Arc::new(config))
                    .accept(tcp)
                    .await
                    .is_ok()
            });

            let report = CertReport::default();
            let tcp = TcpStream::connect(("127.0.0.1", port)).await.unwrap();
            let client = ironrdp_tls::upgrade_with_certificate_validation_callback_for_endpoint(
                tcp,
                "127.0.0.1",
                ENDPOINT,
                validation_callback(policy, report.clone()),
            )
            .await;
            let accepted = client.is_ok();
            drop(client);
            let _ = server.await;
            (accepted, report.take())
        }

        #[tokio::test]
        async fn tofu_handshake_without_a_pin_is_refused_and_reports_the_fingerprint() {
            let (accepted, problem) = handshake(pinned(IDENTITY, None, ENDPOINT)).await;
            assert!(!accepted);
            assert_eq!(
                problem,
                Some(CertProblem {
                    identity: IDENTITY.to_string(),
                    fingerprint: FP_A.to_string(),
                    reason: CertReason::Unknown,
                })
            );
        }

        #[tokio::test]
        async fn tofu_handshake_with_another_pin_is_refused_as_changed() {
            let (accepted, problem) = handshake(pinned(IDENTITY, Some(FP_B), ENDPOINT)).await;
            assert!(!accepted);
            assert_eq!(problem.map(|p| p.reason), Some(CertReason::Changed));
        }

        #[tokio::test]
        async fn tofu_handshake_with_the_pin_goes_through() {
            let (accepted, problem) = handshake(pinned(IDENTITY, Some(FP_A), ENDPOINT)).await;
            assert!(accepted);
            assert_eq!(problem, None);
        }

        #[tokio::test]
        async fn tofu_handshake_at_another_endpoint_is_refused_even_with_the_pin() {
            let (accepted, problem) =
                handshake(pinned(IDENTITY, Some(FP_A), "192.0.2.10:3389")).await;
            assert!(!accepted);
            assert_eq!(problem, None);
        }

        #[tokio::test]
        async fn tofu_handshake_with_trust_cert_goes_through() {
            let (accepted, problem) = handshake(CertPolicy::TrustAll).await;
            assert!(accepted);
            assert_eq!(problem, None);
        }
    }
}
