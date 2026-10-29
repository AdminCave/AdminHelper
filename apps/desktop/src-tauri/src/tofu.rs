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
pub(crate) fn fingerprint(cert_der: &[u8]) -> String {
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
    /// No pin yet — persist this fingerprint and accept (first use). The store
    /// answers it only once the pin is stored.
    Capture,
    /// A pin exists but differs — reject (possible MITM / cert rotation).
    Reject,
    /// The pin store could not be read, or the first-use pin could not be stored —
    /// reject without pinning.
    Unavailable,
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
    /// could not be read. The last one must fail closed at the decision
    /// (`PinDecision::Unavailable`, 3.60).
    fn load(&self, identity: &str) -> Result<Option<String>, ()>;
    /// `Err(())` = the pin was not stored. A first use counts only after `Ok`: a pin
    /// that does not outlive the process is no pin at the next start.
    fn store(&self, identity: &str, fingerprint: &str) -> Result<(), ()>;

    /// Atomically decide the TOFU outcome for `presented` and, on first use,
    /// capture it — the whole read→decide→store sequence of one identity under one
    /// lock. The split `load()` then `store()` is racy: two concurrent first
    /// connections can both observe "no pin" and pin different certs. The default
    /// impl is the non-atomic fallback (fine for the single-threaded in-memory test
    /// store); the keyring store overrides it to hold the lock of the identity.
    fn load_or_store(&self, identity: &str, presented: &str) -> PinDecision {
        // Fail closed: an unreadable store must not be taken as "no pin" (3.60).
        let pinned = match self.load(identity) {
            Err(()) => return PinDecision::Unavailable,
            Ok(opt) => opt,
        };
        let decision = decide(pinned.as_deref(), presented);
        if decision == PinDecision::Capture && self.store(identity, presented).is_err() {
            return PinDecision::Unavailable;
        }
        decision
    }
}

/// Production store: OS keyring backed by a process-wide in-memory cache, so the
/// enforcement path does not hit the keyring on every single request — only the
/// first read and the first-use write. The cache only holds pins the keyring
/// returned or stored, never one whose write failed.
///
/// No keyring call runs under the global lock (R-0644): a keyring that keeps one
/// identity waiting would stall every connection, the pinned ones too. The global
/// lock guards the cache and the table of per-identity locks only; the read, decide
/// and store of a first contact run under the lock of its identity, so two first
/// contacts of one server still cannot both pin.
struct KeyringPinStore {
    cache: &'static Mutex<HashMap<String, String>>,
    locks: &'static Mutex<HashMap<String, Arc<Mutex<()>>>>,
    read: ReadPin,
    write: WritePin,
    delete: DeletePin,
}

type ReadPin = Arc<dyn Fn(&str) -> Result<Option<String>, ()> + Send + Sync>;
type WritePin = Arc<dyn Fn(&str, &str) -> Result<(), ()> + Send + Sync>;
type DeletePin = Arc<dyn Fn(&str) -> Result<(), AppError> + Send + Sync>;

// A poisoned lock only means another thread panicked mid-access; the map
// itself stays consistent, so recover the guard instead of panicking too.
fn cache() -> &'static Mutex<HashMap<String, String>> {
    static CACHE: LazyLock<Mutex<HashMap<String, String>>> =
        LazyLock::new(|| Mutex::new(HashMap::new()));
    &CACHE
}

fn identity_locks() -> &'static Mutex<HashMap<String, Arc<Mutex<()>>>> {
    static LOCKS: LazyLock<Mutex<HashMap<String, Arc<Mutex<()>>>>> =
        LazyLock::new(|| Mutex::new(HashMap::new()));
    &LOCKS
}

impl KeyringPinStore {
    fn production() -> Self {
        Self {
            cache: cache(),
            locks: identity_locks(),
            read: Arc::new(keyring_read),
            write: Arc::new(keyring_write),
            delete: Arc::new(keyring_delete),
        }
    }

    fn cached(&self, identity: &str) -> Option<String> {
        self.cache
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get(identity)
            .cloned()
    }

    fn remember(&self, identity: &str, fingerprint: &str) {
        self.cache
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .insert(identity.to_string(), fingerprint.to_string());
    }

    /// The lock of one pin identity, made under the global lock on first use.
    fn identity_lock(&self, identity: &str) -> Arc<Mutex<()>> {
        Arc::clone(
            self.locks
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .entry(identity.to_string())
                .or_default(),
        )
    }

    /// Drop the pin of `identity` from cache and keyring, after any first contact of it
    /// that is storing right now: that one is then gone too, or begins only afterwards.
    fn forget(&self, identity: &str) -> Result<(), AppError> {
        let lock = self.identity_lock(identity);
        let _held = lock.lock().unwrap_or_else(|e| e.into_inner());
        self.cache
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .remove(identity);
        (self.delete)(identity)
    }
}

impl PinStore for KeyringPinStore {
    fn load(&self, identity: &str) -> Result<Option<String>, ()> {
        if let Some(hit) = self.cached(identity) {
            return Ok(Some(hit));
        }
        // Under the lock of the identity, like `forget`: a pin read before a forget must not
        // land in the cache after it.
        let lock = self.identity_lock(identity);
        let _held = lock.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(hit) = self.cached(identity) {
            return Ok(Some(hit));
        }
        let stored = (self.read)(identity)?;
        if let Some(ref fingerprint) = stored {
            self.remember(identity, fingerprint);
        }
        Ok(stored)
    }

    fn store(&self, identity: &str, fingerprint: &str) -> Result<(), ()> {
        let lock = self.identity_lock(identity);
        let _held = lock.lock().unwrap_or_else(|e| e.into_inner());
        (self.write)(identity, fingerprint)?;
        self.remember(identity, fingerprint);
        Ok(())
    }

    fn load_or_store(&self, identity: &str, presented: &str) -> PinDecision {
        // Every request after the first: a pure in-memory hit, no lock but the cache's.
        if let Some(hit) = self.cached(identity) {
            return decide(Some(&hit), presented);
        }
        let lock = self.identity_lock(identity);
        let _held = lock.lock().unwrap_or_else(|e| e.into_inner());
        // A first contact of this identity in parallel may have stored meanwhile.
        if let Some(hit) = self.cached(identity) {
            return decide(Some(&hit), presented);
        }
        let pinned = match (self.read)(identity) {
            // Fail closed: a keyring we cannot read must not be taken as "no pin"
            // and capture the presented cert — an MITM presenting its own cert
            // during a keyring outage would otherwise be pinned and trusted (3.60).
            Err(()) => return PinDecision::Unavailable,
            Ok(stored) => stored,
        };
        if let Some(ref fingerprint) = pinned {
            self.remember(identity, fingerprint);
        }
        let decision = decide(pinned.as_deref(), presented);
        if decision == PinDecision::Capture {
            // Trust a first use only once the pin is in the keyring: a pin held in
            // the cache alone ends with the process, and the next start would pin
            // whatever certificate is presented then.
            if (self.write)(identity, presented).is_err() {
                return PinDecision::Unavailable;
            }
            self.remember(identity, presented);
        }
        decision
    }
}

fn keyring_key(identity: &str) -> String {
    format!("tofu|cert|{identity}")
}

/// `Ok(None)` = no pin yet (genuine first use), `Ok(Some)` = the pinned fingerprint,
/// `Err(())` = the keyring couldn't be read (locked/transient). The caller must treat
/// `Err` as fail-closed (`PinDecision::Unavailable`), not as "no pin" (3.60).
/// The keyring helpers log a failure with the pin identity, never the fingerprint
/// (R-0771).
fn keyring_read(identity: &str) -> Result<Option<String>, ()> {
    crate::keyring_store::try_get(&keyring_key(identity)).map_err(|e| {
        log::warn!("the TOFU pin of {identity} could not be read from the keyring: {e}");
    })
}

/// `Err(())` = the keyring did not store the pin; the caller must then not trust
/// the presented certificate.
fn keyring_write(identity: &str, fingerprint: &str) -> Result<(), ()> {
    crate::keyring_store::set(&keyring_key(identity), fingerprint).map_err(|e| {
        log::warn!("the TOFU pin of {identity} could not be stored in the keyring: {e}");
    })
}

/// A missing pin is success (see `keyring_store::delete`); any other failure is an `Err`.
fn keyring_delete(identity: &str) -> Result<(), AppError> {
    crate::keyring_store::delete(&keyring_key(identity)).inspect_err(|e| {
        log::warn!("the TOFU pin of {identity} could not be deleted from the keyring: {e}");
    })
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
            // No ERR_TOFU_PIN_MISMATCH: the certificate did not change, and the pin
            // reset the login offers on that code cannot fix an unusable keyring.
            PinDecision::Unavailable => Err(TlsError::General(format!(
                "AdminHelper TOFU: The certificate pin for {} could not be read from or stored \
                 in the system keyring, so the connection was refused. Unlock the system \
                 keyring and connect again.",
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
        store: Arc::new(KeyringPinStore::production()),
        provider: ring_provider(),
    });
    client_with_verifier(verifier)
}

/// Forget the pinned certificate for a server, so the next connection re-pins
/// (TOFU first use). For recovering from a legitimate certificate rotation. An
/// `Err` when the keyring could not delete the pin: the old pin may still decide
/// the next connection, so the reset must not be reported as done (R-0748).
pub fn forget_pin(server_url: &str) -> Result<(), AppError> {
    forget_pin_with(server_url, keyring_delete)
}

/// [`forget_pin`] with the keyring delete as a parameter, so a test can make it fail.
fn forget_pin_with(
    server_url: &str,
    delete: impl Fn(&str) -> Result<(), AppError> + Send + Sync + 'static,
) -> Result<(), AppError> {
    let identity = pin_identity(server_url);
    let store = KeyringPinStore {
        delete: Arc::new(delete),
        ..KeyringPinStore::production()
    };
    // Both caches go even when the delete fails: this process then holds no pin the
    // user asked to forget, and the next contact reads the keyring again.
    let deleted = store.forget(&identity);
    // Drop the cached http client — it may hold a pool pinned to the old cert (5.1).
    crate::http_client::invalidate_client_cache();
    deleted.map_err(|err| {
        AppError::Keyring(format!(
            "the pinned certificate could not be removed from the keyring: {err}"
        ))
    })
}

/// Pin `fingerprint` for `server_url` in the process cache only, as if the keyring
/// had stored it: for tests whose handshake runs on a thread without a test keyring.
#[cfg(test)]
pub(crate) fn seed_cached_pin(server_url: &str, fingerprint: &str) {
    cache()
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .insert(pin_identity(server_url), fingerprint.to_string());
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── R-0644: no keyring call under the global lock ─────────────────────────

    use std::sync::mpsc;
    use std::time::Duration;

    /// A gate the test opens: the keyring call that waits on it hangs until then, and
    /// says so once it is inside, so the test goes on only once the call hangs.
    struct Gate {
        wait: Mutex<Option<mpsc::Receiver<()>>>,
        inside: Mutex<mpsc::Sender<()>>,
    }

    impl Gate {
        /// The gate, the sender that opens it and the receiver that hears it was entered.
        fn new() -> (Arc<Self>, mpsc::Sender<()>, mpsc::Receiver<()>) {
            let (open, wait) = mpsc::channel();
            let (inside, entered) = mpsc::channel();
            let gate = Self {
                wait: Mutex::new(Some(wait)),
                inside: Mutex::new(inside),
            };
            (Arc::new(gate), open, entered)
        }
        fn pass(&self) {
            if let Some(wait) = self.wait.lock().unwrap().take() {
                let _ = self.inside.lock().unwrap().send(());
                let _ = wait.recv();
            }
        }
    }

    /// A store with a cache, locks and a keyring map of its own; `read` and `write` may hang.
    struct Probe {
        store: Arc<KeyringPinStore>,
        keyring: Arc<Mutex<HashMap<String, String>>>,
        writes: Arc<std::sync::atomic::AtomicUsize>,
    }

    fn probe(
        read_gate: Option<(String, Arc<Gate>)>,
        write_gate: Option<(String, Arc<Gate>)>,
        read_fails: bool,
        write_fails: Arc<std::sync::atomic::AtomicBool>,
    ) -> Probe {
        let keyring = Arc::new(Mutex::new(HashMap::new()));
        let writes = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let (k1, k2, k3, w) = (
            keyring.clone(),
            keyring.clone(),
            keyring.clone(),
            writes.clone(),
        );
        let store = KeyringPinStore {
            cache: Box::leak(Box::new(Mutex::new(HashMap::new()))),
            locks: Box::leak(Box::new(Mutex::new(HashMap::new()))),
            read: Arc::new(move |id: &str| {
                if let Some((ref gated, ref gate)) = read_gate {
                    if gated == id {
                        gate.pass();
                    }
                }
                if read_fails {
                    return Err(());
                }
                Ok(k1.lock().unwrap().get(id).cloned())
            }),
            write: Arc::new(move |id: &str, fp: &str| {
                w.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                if let Some((ref gated, ref gate)) = write_gate {
                    if gated == id {
                        gate.pass();
                    }
                }
                if write_fails.load(std::sync::atomic::Ordering::SeqCst) {
                    return Err(());
                }
                k2.lock().unwrap().insert(id.to_string(), fp.to_string());
                Ok(())
            }),
            delete: Arc::new(move |id: &str| {
                k3.lock().unwrap().remove(id);
                Ok(())
            }),
        };
        Probe {
            store: Arc::new(store),
            keyring,
            writes,
        }
    }

    fn no_failure() -> Arc<std::sync::atomic::AtomicBool> {
        Arc::new(std::sync::atomic::AtomicBool::new(false))
    }

    /// `load_or_store` on a thread of its own; its answer arrives on the channel.
    fn decide_on_thread(
        store: &Arc<KeyringPinStore>,
        identity: &str,
        presented: &str,
    ) -> mpsc::Receiver<PinDecision> {
        let (tx, rx) = mpsc::channel();
        let (store, identity, presented) = (
            Arc::clone(store),
            identity.to_string(),
            presented.to_string(),
        );
        std::thread::spawn(move || {
            let _ = tx.send(store.load_or_store(&identity, &presented));
        });
        rx
    }

    const ANSWER: Duration = Duration::from_secs(5);

    #[test]
    fn a_hung_keyring_read_does_not_hold_up_a_pinned_identity() {
        let (gate, open, entered) = Gate::new();
        let p = probe(Some(("x.example".into(), gate)), None, false, no_failure());
        p.store.remember("y.example", FP_A);
        let hung = decide_on_thread(&p.store, "x.example", FP_A);
        entered.recv_timeout(ANSWER).unwrap();

        let pinned = decide_on_thread(&p.store, "y.example", FP_A);
        assert_eq!(pinned.recv_timeout(ANSWER).unwrap(), PinDecision::Trust);
        open.send(()).unwrap();
        assert_eq!(hung.recv_timeout(ANSWER).unwrap(), PinDecision::Capture);
    }

    #[test]
    fn two_first_contacts_of_one_identity_still_pin_once() {
        let (gate, open, entered) = Gate::new();
        let p = probe(None, Some(("x.example".into(), gate)), false, no_failure());
        let first = decide_on_thread(&p.store, "x.example", FP_A);
        entered.recv_timeout(ANSWER).unwrap();
        let second = decide_on_thread(&p.store, "x.example", FP_B);
        assert!(
            second.recv_timeout(Duration::from_millis(300)).is_err(),
            "the second first contact decided while the first was storing"
        );

        open.send(()).unwrap();
        assert_eq!(first.recv_timeout(ANSWER).unwrap(), PinDecision::Capture);
        assert_eq!(second.recv_timeout(ANSWER).unwrap(), PinDecision::Reject);
        assert_eq!(p.store.cached("x.example").as_deref(), Some(FP_A));
        assert_eq!(p.writes.load(std::sync::atomic::Ordering::SeqCst), 1);
    }

    #[test]
    fn an_unreadable_keyring_pins_nothing() {
        let p = probe(None, None, true, no_failure());
        assert_eq!(
            p.store.load_or_store("x.example", FP_A),
            PinDecision::Unavailable
        );
        assert_eq!(p.store.cached("x.example"), None);
        assert_eq!(p.writes.load(std::sync::atomic::Ordering::SeqCst), 0);
    }

    #[test]
    fn a_failed_first_use_store_is_retried_on_the_next_contact() {
        let fails = Arc::new(std::sync::atomic::AtomicBool::new(true));
        let p = probe(None, None, false, Arc::clone(&fails));
        assert_eq!(
            p.store.load_or_store("x.example", FP_A),
            PinDecision::Unavailable
        );
        assert_eq!(p.store.cached("x.example"), None);

        fails.store(false, std::sync::atomic::Ordering::SeqCst);
        assert_eq!(
            p.store.load_or_store("x.example", FP_A),
            PinDecision::Capture
        );
        assert_eq!(p.writes.load(std::sync::atomic::Ordering::SeqCst), 2);
        assert_eq!(
            p.keyring
                .lock()
                .unwrap()
                .get("x.example")
                .map(String::as_str),
            Some(FP_A)
        );
    }

    #[test]
    fn forgetting_waits_for_a_first_contact_that_is_storing() {
        let (gate, open, entered) = Gate::new();
        let p = probe(None, Some(("x.example".into(), gate)), false, no_failure());
        let first = decide_on_thread(&p.store, "x.example", FP_A);
        entered.recv_timeout(ANSWER).unwrap();

        let (done_tx, done) = mpsc::channel();
        let store = Arc::clone(&p.store);
        std::thread::spawn(move || {
            store.forget("x.example").unwrap();
            let _ = done_tx.send(());
        });
        assert!(
            done.recv_timeout(Duration::from_millis(300)).is_err(),
            "forget returned while the first contact was storing"
        );
        open.send(()).unwrap();
        assert_eq!(first.recv_timeout(ANSWER).unwrap(), PinDecision::Capture);
        done.recv_timeout(ANSWER).unwrap();
        assert_eq!(p.store.cached("x.example"), None);
        assert!(p.keyring.lock().unwrap().get("x.example").is_none());
    }

    #[test]
    fn forgetting_waits_for_a_load_that_is_reading() {
        let (gate, open, entered) = Gate::new();
        let p = probe(Some(("x.example".into(), gate)), None, false, no_failure());
        p.keyring
            .lock()
            .unwrap()
            .insert("x.example".into(), FP_A.into());
        let (loaded_tx, loaded) = mpsc::channel();
        let store = Arc::clone(&p.store);
        std::thread::spawn(move || {
            let _ = loaded_tx.send(store.load("x.example"));
        });
        entered.recv_timeout(ANSWER).unwrap();

        let (done_tx, done) = mpsc::channel();
        let store = Arc::clone(&p.store);
        std::thread::spawn(move || {
            store.forget("x.example").unwrap();
            let _ = done_tx.send(());
        });
        assert!(
            done.recv_timeout(Duration::from_millis(300)).is_err(),
            "forget returned while a load was reading"
        );
        open.send(()).unwrap();
        assert_eq!(
            loaded.recv_timeout(ANSWER).unwrap().unwrap().as_deref(),
            Some(FP_A)
        );
        done.recv_timeout(ANSWER).unwrap();
        assert_eq!(p.store.cached("x.example"), None);
        assert!(p.keyring.lock().unwrap().get("x.example").is_none());
    }

    #[test]
    fn a_hung_first_use_store_does_not_hold_up_a_pinned_identity() {
        let (gate, open, entered) = Gate::new();
        let p = probe(None, Some(("x.example".into(), gate)), false, no_failure());
        p.store.remember("y.example", FP_B);
        let hung = decide_on_thread(&p.store, "x.example", FP_A);
        entered.recv_timeout(ANSWER).unwrap();

        let pinned = decide_on_thread(&p.store, "y.example", FP_B);
        assert_eq!(pinned.recv_timeout(ANSWER).unwrap(), PinDecision::Trust);
        open.send(()).unwrap();
        assert_eq!(hung.recv_timeout(ANSWER).unwrap(), PinDecision::Capture);
    }

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
        fn store(&self, identity: &str, fingerprint: &str) -> Result<(), ()> {
            self.map
                .lock()
                .unwrap()
                .insert(identity.to_string(), fingerprint.to_string());
            Ok(())
        }
    }

    /// A store whose load() always reports a read failure — models a locked/
    /// unavailable keyring so the fail-closed path is unit-testable (3.60).
    struct FailingPinStore;
    impl PinStore for FailingPinStore {
        fn load(&self, _identity: &str) -> Result<Option<String>, ()> {
            Err(())
        }
        fn store(&self, _identity: &str, _fingerprint: &str) -> Result<(), ()> {
            panic!("store must not be called when the pin store is unreadable");
        }
    }

    /// A store that reads "no pin" but cannot store one — a keyring that answers
    /// reads but refuses writes.
    struct UnwritablePinStore;
    impl PinStore for UnwritablePinStore {
        fn load(&self, _identity: &str) -> Result<Option<String>, ()> {
            Ok(None)
        }
        fn store(&self, _identity: &str, _fingerprint: &str) -> Result<(), ()> {
            Err(())
        }
    }

    fn cached(identity: &str) -> bool {
        cache()
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .contains_key(identity)
    }

    /// Run the verifier for `identity` over `store` with cert A and return the
    /// message of the expected `TlsError::General`.
    fn rejection_message(identity: &str, store: Arc<dyn PinStore>) -> String {
        let verifier = TofuVerifier {
            identity: identity.to_string(),
            store,
            provider: ring_provider(),
        };
        let cert_a = CertificateDer::from(CERT_A.to_vec());
        let name = ServerName::try_from("localhost").unwrap();
        match verifier.verify_server_cert(&cert_a, &[], &name, &[], UnixTime::now()) {
            Err(TlsError::General(msg)) => msg,
            other => panic!("expected a General rejection, got: {other:?}"),
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
        assert_eq!(
            store.load_or_store("h:8443", FP_A),
            PinDecision::Unavailable
        );

        // Rejected as before, but not as a certificate change: resetting the pin,
        // which the login offers on ERR_TOFU_PIN_MISMATCH, does not help here.
        let msg = rejection_message("unreadable.example:443", Arc::new(FailingPinStore));
        assert!(msg.contains("unreadable.example:443"), "{msg}");
        assert!(msg.contains("keyring"), "{msg}");
        assert!(!msg.contains("ERR_TOFU_PIN_MISMATCH"), "{msg}");
    }

    #[test]
    fn load_or_store_refuses_a_first_use_whose_pin_cannot_be_stored() {
        assert_eq!(
            UnwritablePinStore.load_or_store("unwritable.example:443", FP_A),
            PinDecision::Unavailable
        );

        let msg = rejection_message("unwritable.example:443", Arc::new(UnwritablePinStore));
        assert!(msg.contains("unwritable.example:443"), "{msg}");
        assert!(msg.contains("keyring"), "{msg}");
        assert!(!msg.contains("ERR_TOFU_PIN_MISMATCH"), "{msg}");
    }

    #[test]
    fn keyring_store_refuses_a_first_use_it_cannot_store_and_caches_nothing() {
        // No keyring_store::memory() guard: in a test build `set` fails and
        // `try_get` finds nothing, like a keyring that cannot be written.
        let identity = "keyring-unstored.example:443";
        assert_eq!(
            KeyringPinStore::production().load_or_store(identity, FP_A),
            PinDecision::Unavailable
        );
        assert!(!cached(identity), "an unstored pin must not be cached");
        // Still no pin: the next connection is refused again, not trusted from the cache.
        assert_eq!(
            KeyringPinStore::production().load_or_store(identity, FP_A),
            PinDecision::Unavailable
        );
        assert!(!cached(identity), "an unstored pin must not be cached");

        assert_eq!(KeyringPinStore::production().store(identity, FP_A), Err(()));
        assert!(!cached(identity), "an unstored pin must not be cached");
    }

    #[test]
    fn keyring_store_captures_into_the_keyring_then_trusts_and_rejects() {
        let _keyring = crate::keyring_store::memory();
        let identity = "keyring-stored.example:443";
        assert_eq!(
            KeyringPinStore::production().load_or_store(identity, FP_A),
            PinDecision::Capture
        );
        assert_eq!(
            crate::keyring_store::get(&format!("tofu|cert|{identity}")).as_deref(),
            Some(FP_A)
        );
        assert_eq!(
            KeyringPinStore::production().load_or_store(identity, FP_A),
            PinDecision::Trust
        );
        assert_eq!(
            KeyringPinStore::production().load_or_store(identity, FP_B),
            PinDecision::Reject
        );
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
        // until restart. Without a keyring_store::memory() guard a test build deletes successfully,
        // so this needs no keyring backend.
        let identity = pin_identity("https://forget-test.example:443/");
        cache()
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .insert(identity.clone(), FP_A.to_string());

        // A different spelling (no explicit port, trailing path) that normalizes to the same identity.
        forget_pin("https://forget-test.example/api").unwrap();

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
    fn forget_pin_reports_a_pin_the_keyring_could_not_delete_and_still_clears_the_cache() {
        // R-0748: the reset reported success while the old pin stayed in the keyring, and
        // after the next start the connection was refused again.
        let identity = pin_identity("https://forget-fails.example:443/");
        cache()
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .insert(identity.clone(), FP_A.to_string());

        let asked = Arc::new(Mutex::new(None));
        let seen = Arc::clone(&asked);
        let err = forget_pin_with("https://forget-fails.example/api", move |id| {
            *seen.lock().unwrap() = Some(id.to_string());
            Err(AppError::Keyring("collection is locked".to_string()))
        })
        .unwrap_err();

        assert_eq!(asked.lock().unwrap().as_deref(), Some(identity.as_str()));
        let msg = err.to_string();
        assert!(
            matches!(&err, AppError::Keyring(_))
                && msg.contains("the pinned certificate could not be removed from the keyring")
                && msg.contains("collection is locked"),
            "{err:?}"
        );
        assert!(!msg.contains(FP_A), "{msg}");
        assert!(
            !cached(&identity),
            "a failed keyring delete must not leave the pin in the process cache"
        );
    }

    #[test]
    fn forget_pin_succeeds_when_the_keyring_deletes_the_pin() {
        let identity = pin_identity("https://forget-ok.example/");
        cache()
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .insert(identity.clone(), FP_A.to_string());

        assert!(forget_pin_with("https://forget-ok.example", |_| Ok(())).is_ok());
        assert!(!cached(&identity));
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
            store.store("pin-test", FP_A).unwrap();
            let store: Arc<dyn PinStore> = store;

            // Server now presents cert B under the same identity: must be rejected.
            let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let port = listener.local_addr().unwrap().port();
            tokio::spawn(serve_once(listener, server_config(CERT_B, KEY_B)));
            let client = pinning_client_for("pin-test", store);
            assert_eq!(get(&client, port).await, Err(()));
        }

        #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
        async fn changed_cert_refuses_with_the_tofu_code() {
            let store = Arc::new(InMemoryPinStore::default());
            store.store("pin-test", FP_A).unwrap();
            let store: Arc<dyn PinStore> = store;

            let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let port = listener.local_addr().unwrap().port();
            tokio::spawn(serve_once(listener, server_config(CERT_B, KEY_B)));
            let client = pinning_client_for("pin-test", store);
            let err = client
                .get(format!("https://127.0.0.1:{port}/"))
                .send()
                .await
                .expect_err("a changed certificate must be refused");
            assert_eq!(AppError::from(err).code(), "ERR_TOFU_PIN_MISMATCH");
        }

        #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
        async fn first_use_is_refused_when_the_pin_cannot_be_stored() {
            let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let port = listener.local_addr().unwrap().port();
            tokio::spawn(serve_once(listener, server_config(CERT_A, KEY_A)));
            let client = pinning_client_for("unwritable.example:443", Arc::new(UnwritablePinStore));
            assert_eq!(get(&client, port).await, Err(()));
        }
    }
}
