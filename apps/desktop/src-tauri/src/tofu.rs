// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! Trust-On-First-Use (TOFU) certificate pinning for the self-signed path.
//!
//! When the user enables "allow self-signed certificates", we must NOT fall back
//! to `danger_accept_invalid_certs(true)` — that disables chain *and* hostname
//! verification with no pinning, so an on-path attacker can MITM the connection
//! and steal the login password, the JWT access/refresh tokens and the FRP client
//! private key. Instead we mirror the Go agent's TOFU model (SSH `known_hosts`
//! semantics): on the first connection we capture and persist the server's leaf
//! certificate fingerprint; on every later connection we accept *only* that exact
//! certificate and reject anything else.
//!
//! The pin is the SHA-256 of the leaf certificate's DER. Pinning the fingerprint
//! (not a CA chain) is deliberate: it binds the connection to one specific
//! certificate+key, so a different certificate — even a valid public-CA one for
//! the same host — is rejected. Hostname and expiry are therefore irrelevant in
//! this mode (the pin *is* the identity), exactly like an SSH host key.
//!
//! The signature over the handshake is still verified against the presented
//! certificate's public key (delegated to the ring provider), so a captured
//! certificate cannot be replayed by an attacker who does not hold its key.

use std::collections::HashMap;
use std::sync::{Arc, LazyLock, Mutex};

use rustls::client::danger::{HandshakeSignatureValid, ServerCertVerified, ServerCertVerifier};
use rustls::crypto::CryptoProvider;
use rustls::pki_types::{CertificateDer, ServerName, UnixTime};
use rustls::{DigitallySignedStruct, Error as TlsError, SignatureScheme};
use url::Url;

use crate::error::AppError;

// ── Pure logic (unit-tested) ──────────────────────────────────────────

/// SHA-256 of a leaf certificate's DER, lower-case hex. This is what we pin.
fn fingerprint(cert_der: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let digest = Sha256::digest(cert_der);
    let mut hex = String::with_capacity(digest.len() * 2);
    for byte in digest {
        // Two lower-case hex nibbles, no allocation per byte.
        hex.push(char::from_digit((byte >> 4) as u32, 16).unwrap());
        hex.push(char::from_digit((byte & 0x0f) as u32, 16).unwrap());
    }
    hex
}

/// Stable pin identity for a server URL: `host[:port]` (scheme default port
/// filled in), so `https://h:8443/` and `https://h:8443` share one pin and the
/// pin tracks the server host, like an SSH `known_hosts` entry.
fn pin_identity(server_url: &str) -> String {
    match Url::parse(server_url) {
        Ok(url) => {
            let host = url.host_str().unwrap_or("").to_string();
            match url.port_or_known_default() {
                Some(port) => format!("{host}:{port}"),
                None => host,
            }
        }
        Err(_) => server_url.trim().to_string(),
    }
}

/// The TOFU decision for a presented certificate given the stored pin.
#[derive(Debug, PartialEq, Eq)]
enum PinDecision {
    /// Pin matches the presented certificate — accept.
    Trust,
    /// No pin yet — accept and persist this fingerprint (first use).
    Capture,
    /// A pin exists but differs — reject (possible MITM / cert rotation).
    Reject,
}

fn decide(pinned: Option<&str>, presented: &str) -> PinDecision {
    match pinned {
        Some(pin) if pin == presented => PinDecision::Trust,
        Some(_) => PinDecision::Reject,
        None => PinDecision::Capture,
    }
}

// ── Pin storage ───────────────────────────────────────────────────────

/// Where pinned fingerprints live. Abstracted so the verifier is unit-testable
/// without a real OS keyring.
trait PinStore: Send + Sync {
    /// `Ok(None)` = no pin (first use), `Ok(Some)` = the pin, `Err(())` = the store
    /// could not be read. The last one must fail closed at the decision (3.60).
    fn load(&self, identity: &str) -> Result<Option<String>, ()>;
    fn store(&self, identity: &str, fingerprint: &str);

    /// Atomically decide the TOFU outcome for `presented` and, on first use,
    /// capture it — the whole read→decide→store sequence under ONE lock. The
    /// split `load()` then `store()` is racy: two concurrent first connections
    /// can both observe "no pin" and pin different certs. The default impl is the
    /// non-atomic fallback (fine for the single-threaded in-memory test store);
    /// the keyring store overrides it to hold its cache lock across the decision.
    fn load_or_store(&self, identity: &str, presented: &str) -> PinDecision {
        // Fail closed: an unreadable store must not be taken as "no pin" (3.60).
        let pinned = match self.load(identity) {
            Err(()) => return PinDecision::Reject,
            Ok(opt) => opt,
        };
        let decision = decide(pinned.as_deref(), presented);
        if decision == PinDecision::Capture {
            self.store(identity, presented);
        }
        decision
    }
}

/// Production store: OS keyring (same secure store as the JWT tokens) backed by
/// a process-wide in-memory cache, so the enforcement path does not hit the
/// keyring on every single request — only the first read and the first-use write.
struct KeyringPinStore;

// A poisoned lock only means another thread panicked mid-access; the map
// itself stays consistent, so recover the guard instead of panicking too.
fn cache() -> &'static Mutex<HashMap<String, String>> {
    static CACHE: LazyLock<Mutex<HashMap<String, String>>> =
        LazyLock::new(|| Mutex::new(HashMap::new()));
    &CACHE
}

impl PinStore for KeyringPinStore {
    fn load(&self, identity: &str) -> Result<Option<String>, ()> {
        if let Some(hit) = cache()
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get(identity)
            .cloned()
        {
            return Ok(Some(hit));
        }
        let stored = keyring_read(identity)?;
        if let Some(ref fingerprint) = stored {
            cache()
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .insert(identity.to_string(), fingerprint.clone());
        }
        Ok(stored)
    }

    fn store(&self, identity: &str, fingerprint: &str) {
        keyring_write(identity, fingerprint);
        cache()
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .insert(identity.to_string(), fingerprint.to_string());
    }

    fn load_or_store(&self, identity: &str, presented: &str) -> PinDecision {
        // Hold the cache lock across the entire read→decide→capture so two
        // parallel first connections cannot both read "no pin" and pin different
        // certs. On a cache miss the (slow) keyring read happens under the lock —
        // acceptable because it only fires on the first use per identity; every
        // later request is a pure in-memory cache hit.
        let mut guard = cache().lock().unwrap_or_else(|e| e.into_inner());
        let pinned = match guard.get(identity) {
            Some(hit) => Some(hit.clone()),
            None => match keyring_read(identity) {
                // Fail closed: a keyring we cannot read must not be taken as "no pin"
                // and capture the presented cert — an MITM presenting its own cert
                // during a keyring outage would otherwise be pinned and trusted (3.60).
                Err(()) => return PinDecision::Reject,
                Ok(stored) => {
                    if let Some(ref fingerprint) = stored {
                        guard.insert(identity.to_string(), fingerprint.clone());
                    }
                    stored
                }
            },
        };
        let decision = decide(pinned.as_deref(), presented);
        if decision == PinDecision::Capture {
            keyring_write(identity, presented);
            guard.insert(identity.to_string(), presented.to_string());
        }
        decision
    }
}

fn keyring_key(identity: &str) -> String {
    format!("tofu|cert|{identity}")
}

/// `Ok(None)` = no pin yet (genuine first use), `Ok(Some)` = the pinned fingerprint,
/// `Err(())` = the keyring couldn't be read (locked/transient). The caller must treat
/// `Err` as fail-closed, not as "no pin" (3.60).
fn keyring_read(identity: &str) -> Result<Option<String>, ()> {
    crate::keyring_store::try_get(&keyring_key(identity)).map_err(|_| ())
}

fn keyring_write(identity: &str, fingerprint: &str) {
    let _ = crate::keyring_store::set(&keyring_key(identity), fingerprint);
}

fn keyring_delete(identity: &str) {
    let _ = crate::keyring_store::delete(&keyring_key(identity));
}

// ── rustls verifier ───────────────────────────────────────────────────

/// The ring provider, matched to the backend reqwest's `rustls-tls` resolves.
/// Built once: `builder_with_provider` requires an explicit provider because
/// reqwest does not install a process-default one. Shared with `enrollment.rs`
/// so the enrolled mTLS client uses the same provider.
pub(crate) fn ring_provider() -> Arc<CryptoProvider> {
    static PROVIDER: LazyLock<Arc<CryptoProvider>> =
        LazyLock::new(|| Arc::new(rustls::crypto::ring::default_provider()));
    PROVIDER.clone()
}

struct TofuVerifier {
    identity: String,
    store: Arc<dyn PinStore>,
    provider: Arc<CryptoProvider>,
}

impl std::fmt::Debug for TofuVerifier {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("TofuVerifier")
            .field("identity", &self.identity)
            .finish_non_exhaustive()
    }
}

impl ServerCertVerifier for TofuVerifier {
    fn verify_server_cert(
        &self,
        end_entity: &CertificateDer<'_>,
        _intermediates: &[CertificateDer<'_>],
        _server_name: &ServerName<'_>,
        _ocsp_response: &[u8],
        _now: UnixTime,
    ) -> Result<ServerCertVerified, TlsError> {
        // Pin the leaf only; hostname/expiry are intentionally not checked here —
        // the fingerprint match *is* the identity check (SSH known_hosts model).
        // Read→decide→capture is atomic (one lock) so two parallel first
        // connections cannot pin different certs.
        let presented = fingerprint(end_entity.as_ref());
        match self.store.load_or_store(&self.identity, &presented) {
            PinDecision::Trust | PinDecision::Capture => Ok(ServerCertVerified::assertion()),
            // The ERR_TOFU_PIN_MISMATCH prefix is a stable, language-independent
            // contract: the login screen keys the "reset pin" recovery action off
            // it (Login.svelte) instead of the human prose, which is free to change
            // or be localized. It reaches the UI buried in the reqwest source chain,
            // so the frontend matches it as a substring, not a prefix.
            PinDecision::Reject => Err(TlsError::General(format!(
                "ERR_TOFU_PIN_MISMATCH: AdminHelper TOFU: Das Server-Zertifikat für {} hat sich \
                 seit dem ersten Verbinden geändert (mögliche MITM-Attacke). War der Wechsel \
                 erwartet, den gepinnten Eintrag in den Einstellungen zurücksetzen.",
                self.identity
            ))),
        }
    }

    fn verify_tls12_signature(
        &self,
        message: &[u8],
        cert: &CertificateDer<'_>,
        dss: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, TlsError> {
        rustls::crypto::verify_tls12_signature(
            message,
            cert,
            dss,
            &self.provider.signature_verification_algorithms,
        )
    }

    fn verify_tls13_signature(
        &self,
        message: &[u8],
        cert: &CertificateDer<'_>,
        dss: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, TlsError> {
        rustls::crypto::verify_tls13_signature(
            message,
            cert,
            dss,
            &self.provider.signature_verification_algorithms,
        )
    }

    fn supported_verify_schemes(&self) -> Vec<SignatureScheme> {
        self.provider
            .signature_verification_algorithms
            .supported_schemes()
    }
}

// ── Public API ────────────────────────────────────────────────────────

fn client_with_verifier(
    verifier: Arc<dyn ServerCertVerifier>,
) -> Result<reqwest::Client, AppError> {
    let tls = rustls::ClientConfig::builder_with_provider(ring_provider())
        .with_safe_default_protocol_versions()
        .map_err(|err| AppError::Connection(format!("TLS-Konfiguration: {err}")))?
        .dangerous()
        .with_custom_certificate_verifier(verifier)
        .with_no_client_auth();
    crate::http_client::with_timeouts(reqwest::Client::builder())
        .use_preconfigured_tls(tls)
        .build()
        .map_err(AppError::from)
}

/// Build a reqwest client that pins the given server's certificate (TOFU). Used
/// only on the self-signed path; the public-CA path keeps reqwest's default
/// full validation.
pub fn pinning_client(server_url: &str) -> Result<reqwest::Client, AppError> {
    let verifier = Arc::new(TofuVerifier {
        identity: pin_identity(server_url),
        store: Arc::new(KeyringPinStore),
        provider: ring_provider(),
    });
    client_with_verifier(verifier)
}

/// Forget the pinned certificate for a server, so the next connection re-pins
/// (TOFU first use). For recovering from a legitimate certificate rotation.
pub fn forget_pin(server_url: &str) {
    let identity = pin_identity(server_url);
    cache()
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .remove(&identity);
    keyring_delete(&identity);
    // Drop the cached http client — it may hold a pool pinned to the old cert (5.1).
    crate::http_client::invalidate_client_cache();
}

#[cfg(test)]
mod tests {
    use super::*;

    const CERT_A: &[u8] = include_bytes!("../test-fixtures/certA.der");
    const CERT_B: &[u8] = include_bytes!("../test-fixtures/certB.der");
    // SHA-256 of the fixtures, computed independently (`sha256sum certX.der`),
    // so this also pins our fingerprint() to the standard algorithm.
    const FP_A: &str = "ef8f54d07c7272f6e224d4b9d153fdca5be69a1a0ba25fb50b4bb5e2cd9462c0";
    const FP_B: &str = "65ab0fef4e64dea7c994dd335636576a09dc51d06062c967297d43658439ca36";

    #[derive(Default)]
    struct InMemoryPinStore {
        map: Mutex<HashMap<String, String>>,
    }
    impl PinStore for InMemoryPinStore {
        fn load(&self, identity: &str) -> Result<Option<String>, ()> {
            Ok(self.map.lock().unwrap().get(identity).cloned())
        }
        fn store(&self, identity: &str, fingerprint: &str) {
            self.map
                .lock()
                .unwrap()
                .insert(identity.to_string(), fingerprint.to_string());
        }
    }

    /// A store whose load() always reports a read failure — models a locked/
    /// unavailable keyring so the fail-closed path is unit-testable (3.60).
    struct FailingPinStore;
    impl PinStore for FailingPinStore {
        fn load(&self, _identity: &str) -> Result<Option<String>, ()> {
            Err(())
        }
        fn store(&self, _identity: &str, _fingerprint: &str) {
            panic!("store must not be called when the pin store is unreadable");
        }
    }

    #[test]
    fn fingerprint_matches_standard_sha256_and_differs_per_cert() {
        assert_eq!(fingerprint(CERT_A), FP_A);
        assert_eq!(fingerprint(CERT_B), FP_B);
        assert_ne!(fingerprint(CERT_A), fingerprint(CERT_B));
    }

    #[test]
    fn decide_covers_trust_capture_reject() {
        assert_eq!(decide(None, FP_A), PinDecision::Capture);
        assert_eq!(decide(Some(FP_A), FP_A), PinDecision::Trust);
        assert_eq!(decide(Some(FP_A), FP_B), PinDecision::Reject);
    }

    #[test]
    fn load_or_store_captures_then_trusts_and_rejects() {
        let store = InMemoryPinStore::default();
        // First use: capture and persist.
        assert_eq!(store.load_or_store("h:8443", FP_A), PinDecision::Capture);
        assert_eq!(store.load("h:8443").unwrap().as_deref(), Some(FP_A));
        // Same cert later: trust, no change.
        assert_eq!(store.load_or_store("h:8443", FP_A), PinDecision::Trust);
        // Changed cert: reject, pin unchanged.
        assert_eq!(store.load_or_store("h:8443", FP_B), PinDecision::Reject);
        assert_eq!(store.load("h:8443").unwrap().as_deref(), Some(FP_A));
    }

    #[test]
    fn load_or_store_fails_closed_when_store_unreadable() {
        // 3.60: an unreadable keyring must reject, not treat the outage as "no pin"
        // and capture+trust whatever cert is presented (an MITM's during a keyring hang).
        let store = FailingPinStore;
        assert_eq!(store.load_or_store("h:8443", FP_A), PinDecision::Reject);
    }

    #[test]
    fn pin_identity_normalizes_host_and_port() {
        assert_eq!(pin_identity("https://h.example:8443/"), "h.example:8443");
        assert_eq!(pin_identity("https://h.example:8443"), "h.example:8443");
        // Default https port is filled in so scheme-implicit and explicit match.
        assert_eq!(pin_identity("https://h.example"), "h.example:443");
        assert_eq!(pin_identity("https://h.example:443/api"), "h.example:443");
    }

    #[test]
    fn forget_pin_clears_the_cache_under_the_normalized_identity() {
        // 6.111: forget_pin is the only recovery after a legitimate cert rotation. It must clear the
        // process cache under the SAME pin_identity normalization used when pinning — so a URL with
        // the implicit default port must forget a pin stored under the explicit ":443". A regression
        // that forgets the cache (or normalizes differently) leaves the user stuck in a pin mismatch
        // until restart. keyring_delete is fail-silent, so this needs no keyring backend.
        let identity = pin_identity("https://forget-test.example:443/");
        cache()
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .insert(identity.clone(), FP_A.to_string());

        // A different spelling (no explicit port, trailing path) that normalizes to the same identity.
        forget_pin("https://forget-test.example/api");

        let present = cache()
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .contains_key(&identity);
        assert!(
            !present,
            "forget_pin must clear the cached pin under the normalized identity"
        );
    }

    #[test]
    fn verifier_captures_then_trusts_same_cert_and_rejects_changed_cert() {
        let store = Arc::new(InMemoryPinStore::default());
        let verifier = TofuVerifier {
            identity: "server".to_string(),
            store: store.clone(),
            provider: ring_provider(),
        };
        let cert_a = CertificateDer::from(CERT_A.to_vec());
        let cert_b = CertificateDer::from(CERT_B.to_vec());
        let name = ServerName::try_from("localhost").unwrap();
        let now = UnixTime::now();

        // First use: captures the pin and accepts.
        assert!(verifier
            .verify_server_cert(&cert_a, &[], &name, &[], now)
            .is_ok());
        assert_eq!(store.load("server").unwrap().as_deref(), Some(FP_A));

        // Reconnect with the same cert: trusted.
        assert!(verifier
            .verify_server_cert(&cert_a, &[], &name, &[], now)
            .is_ok());

        // The server presents a *different* cert under the same identity: reject
        // with the stable ERR_TOFU_PIN_MISMATCH code the login screen keys its
        // "reset pin" recovery off (symmetric to the CA-pin test in enrollment.rs).
        match verifier.verify_server_cert(&cert_b, &[], &name, &[], now) {
            Err(TlsError::General(msg)) => assert!(
                msg.contains("ERR_TOFU_PIN_MISMATCH"),
                "Reject muss den stabilen Fehlercode fuer das Login-Recovery tragen, war: {msg}"
            ),
            other => panic!("erwartet General-Reject mit Fehlercode, war: {other:?}"),
        }
    }

    // Real-handshake proof: an in-process TLS server presenting a controlled
    // certificate, so we verify reqwest actually drives our verifier (signature
    // delegation included) and that a cert change is rejected end to end —
    // exactly the property that could not be checked without a live server.
    mod tls_handshake {
        use super::*;
        use tokio::net::TcpListener;

        use crate::test_tls::{get, serve_once};

        const KEY_A: &[u8] = include_bytes!("../test-fixtures/keyA.der");
        const KEY_B: &[u8] = include_bytes!("../test-fixtures/keyB.der");

        fn server_config(cert_der: &[u8], key_der: &[u8]) -> Arc<rustls::ServerConfig> {
            use rustls::pki_types::{PrivateKeyDer, PrivatePkcs8KeyDer};
            let cert = CertificateDer::from(cert_der.to_vec());
            let key = PrivateKeyDer::Pkcs8(PrivatePkcs8KeyDer::from(key_der.to_vec()));
            let config = rustls::ServerConfig::builder_with_provider(ring_provider())
                .with_safe_default_protocol_versions()
                .unwrap()
                .with_no_client_auth()
                .with_single_cert(vec![cert], key)
                .unwrap();
            Arc::new(config)
        }

        fn pinning_client_for(identity: &str, store: Arc<dyn PinStore>) -> reqwest::Client {
            let verifier = Arc::new(TofuVerifier {
                identity: identity.to_string(),
                store,
                provider: ring_provider(),
            });
            client_with_verifier(verifier).unwrap()
        }

        #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
        async fn first_use_pins_and_same_cert_reconnects() {
            let store: Arc<dyn PinStore> = Arc::new(InMemoryPinStore::default());

            // First connection with cert A: pins it.
            let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let port = listener.local_addr().unwrap().port();
            tokio::spawn(serve_once(listener, server_config(CERT_A, KEY_A)));
            let client = pinning_client_for("pin-test", store.clone());
            assert_eq!(get(&client, port).await, Ok(reqwest::StatusCode::OK));
            assert_eq!(store.load("pin-test").unwrap().as_deref(), Some(FP_A));

            // Reconnect, same cert A under the same pin identity: accepted.
            let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let port = listener.local_addr().unwrap().port();
            tokio::spawn(serve_once(listener, server_config(CERT_A, KEY_A)));
            let client = pinning_client_for("pin-test", store.clone());
            assert_eq!(get(&client, port).await, Ok(reqwest::StatusCode::OK));
        }

        #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
        async fn changed_cert_is_rejected() {
            // Store already pins cert A for this identity.
            let store = Arc::new(InMemoryPinStore::default());
            store.store("pin-test", FP_A);
            let store: Arc<dyn PinStore> = store;

            // Server now presents cert B under the same identity: must be rejected.
            let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let port = listener.local_addr().unwrap().port();
            tokio::spawn(serve_once(listener, server_config(CERT_B, KEY_B)));
            let client = pinning_client_for("pin-test", store);
            assert_eq!(get(&client, port).await, Err(()));
        }
    }
}
