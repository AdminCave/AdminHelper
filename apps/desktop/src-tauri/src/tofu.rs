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

/// Keyring service shared with `auth.rs` / `password.rs`.
const KEYRING_SERVICE: &str = "com.adminhelper.app";

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
    fn load(&self, identity: &str) -> Option<String>;
    fn store(&self, identity: &str, fingerprint: &str);
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
    fn load(&self, identity: &str) -> Option<String> {
        if let Some(hit) = cache()
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get(identity)
            .cloned()
        {
            return Some(hit);
        }
        let stored = keyring_read(identity);
        if let Some(ref fingerprint) = stored {
            cache()
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .insert(identity.to_string(), fingerprint.clone());
        }
        stored
    }

    fn store(&self, identity: &str, fingerprint: &str) {
        keyring_write(identity, fingerprint);
        cache()
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .insert(identity.to_string(), fingerprint.to_string());
    }
}

fn keyring_key(identity: &str) -> String {
    format!("tofu|cert|{identity}")
}

// A keyring read error (locked, transient) degrades to "no pin", i.e. first-use
// capture — never fail-closed, matching the lenient keyring handling elsewhere.
// The handshake signature check still proves the server holds the key.
#[cfg(unix)]
fn keyring_read(identity: &str) -> Option<String> {
    use keyring::Entry;
    Entry::new(KEYRING_SERVICE, &keyring_key(identity))
        .ok()?
        .get_password()
        .ok()
}

#[cfg(unix)]
fn keyring_write(identity: &str, fingerprint: &str) {
    use keyring::Entry;
    if let Ok(entry) = Entry::new(KEYRING_SERVICE, &keyring_key(identity)) {
        let _ = entry.set_password(fingerprint);
    }
}

#[cfg(unix)]
fn keyring_delete(identity: &str) {
    use keyring::Entry;
    if let Ok(entry) = Entry::new(KEYRING_SERVICE, &keyring_key(identity)) {
        let _ = entry.delete_credential();
    }
}

#[cfg(target_os = "windows")]
fn keyring_read(identity: &str) -> Option<String> {
    crate::password::windows_read_credential(&keyring_key(identity))
        .ok()
        .filter(|value| !value.is_empty())
}

#[cfg(target_os = "windows")]
fn keyring_write(identity: &str, fingerprint: &str) {
    let _ = crate::password::windows_store_credential(
        &keyring_key(identity),
        "adminhelper",
        fingerprint,
    );
}

#[cfg(target_os = "windows")]
fn keyring_delete(identity: &str) {
    let _ = crate::password::windows_delete_credential(&keyring_key(identity));
}

#[cfg(not(any(unix, target_os = "windows")))]
fn keyring_read(_identity: &str) -> Option<String> {
    None
}

#[cfg(not(any(unix, target_os = "windows")))]
fn keyring_write(_identity: &str, _fingerprint: &str) {}

#[cfg(not(any(unix, target_os = "windows")))]
fn keyring_delete(_identity: &str) {}

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
        let presented = fingerprint(end_entity.as_ref());
        match decide(self.store.load(&self.identity).as_deref(), &presented) {
            PinDecision::Trust => Ok(ServerCertVerified::assertion()),
            PinDecision::Capture => {
                self.store.store(&self.identity, &presented);
                Ok(ServerCertVerified::assertion())
            }
            PinDecision::Reject => Err(TlsError::General(format!(
                "AdminHelper TOFU: Das Server-Zertifikat für {} hat sich seit dem \
                 ersten Verbinden geändert (mögliche MITM-Attacke). War der Wechsel \
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
    reqwest::Client::builder()
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
        fn load(&self, identity: &str) -> Option<String> {
            self.map.lock().unwrap().get(identity).cloned()
        }
        fn store(&self, identity: &str, fingerprint: &str) {
            self.map
                .lock()
                .unwrap()
                .insert(identity.to_string(), fingerprint.to_string());
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
    fn pin_identity_normalizes_host_and_port() {
        assert_eq!(pin_identity("https://h.example:8443/"), "h.example:8443");
        assert_eq!(pin_identity("https://h.example:8443"), "h.example:8443");
        // Default https port is filled in so scheme-implicit and explicit match.
        assert_eq!(pin_identity("https://h.example"), "h.example:443");
        assert_eq!(pin_identity("https://h.example:443/api"), "h.example:443");
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
        assert_eq!(store.load("server").as_deref(), Some(FP_A));

        // Reconnect with the same cert: trusted.
        assert!(verifier
            .verify_server_cert(&cert_a, &[], &name, &[], now)
            .is_ok());

        // The server presents a *different* cert under the same identity: reject.
        assert!(verifier
            .verify_server_cert(&cert_b, &[], &name, &[], now)
            .is_err());
    }

    // Real-handshake proof: an in-process TLS server presenting a controlled
    // certificate, so we verify reqwest actually drives our verifier (signature
    // delegation included) and that a cert change is rejected end to end —
    // exactly the property that could not be checked without a live server.
    mod tls_handshake {
        use super::*;
        use std::time::Duration;
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        use tokio::net::TcpListener;
        use tokio_rustls::TlsAcceptor;

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

        /// Accept exactly one TLS connection, answer a minimal HTTP/1.1 200, and
        /// stay tolerant of a client that aborts mid-handshake (the reject case).
        async fn serve_once(listener: TcpListener, config: Arc<rustls::ServerConfig>) {
            let acceptor = TlsAcceptor::from(config);
            if let Ok((tcp, _)) = listener.accept().await {
                if let Ok(mut tls) = acceptor.accept(tcp).await {
                    let mut buf = [0u8; 1024];
                    let _ = tls.read(&mut buf).await;
                    let _ = tls
                        .write_all(
                            b"HTTP/1.1 200 OK\r\ncontent-length: 0\r\nconnection: close\r\n\r\n",
                        )
                        .await;
                    let _ = tls.flush().await;
                    let _ = tls.shutdown().await;
                }
            }
        }

        fn pinning_client_for(identity: &str, store: Arc<dyn PinStore>) -> reqwest::Client {
            let verifier = Arc::new(TofuVerifier {
                identity: identity.to_string(),
                store,
                provider: ring_provider(),
            });
            client_with_verifier(verifier).unwrap()
        }

        async fn get(client: &reqwest::Client, port: u16) -> Result<reqwest::StatusCode, ()> {
            let url = format!("https://127.0.0.1:{port}/");
            match tokio::time::timeout(Duration::from_secs(5), client.get(url).send()).await {
                Ok(Ok(resp)) => Ok(resp.status()),
                _ => Err(()),
            }
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
            assert_eq!(store.load("pin-test").as_deref(), Some(FP_A));

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
