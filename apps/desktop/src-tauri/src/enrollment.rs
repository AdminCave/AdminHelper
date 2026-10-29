// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! Desktop mTLS enrollment (ADR 0001 §3.3 / A5).
//!
//! The desktop enrolls with a one-time token an admin minted out-of-band
//! (`POST /api/enrollment/token/for`, ADR 0003) — no prior login, so it works under
//! enforced mTLS. It generates an ECDSA P-256 keypair + CSR **on-device** (the
//! private key never leaves the host) and redeems the token at the gateway's
//! certless enroll plane. The ca-issuer signs an access-scoped client leaf; the
//! desktop pins the returned CA chain and presents the cert on every later request
//! (mTLS + CA-pinning in `build_client`), renews it at ~50% lifetime, and — after
//! login — can export a long-lived browser cert as a PKCS12.

use std::sync::Arc;

use rustls::client::danger::{HandshakeSignatureValid, ServerCertVerified, ServerCertVerifier};
use rustls::client::WebPkiServerVerifier;
use rustls::pki_types::pem::PemObject;
use rustls::pki_types::{CertificateDer, PrivateKeyDer, ServerName, UnixTime};
use rustls::{
    CertificateError, DigitallySignedStruct, Error as TlsError, RootCertStore, SignatureScheme,
};
use serde::{Deserialize, Serialize};
use url::Url;

use crate::error::AppError;
use crate::keyring_store;
use crate::models::DeviceIdentity;
use crate::session::{SessionState, SignedIn};

// Three small entries (ECDSA fits the Windows 2560-byte limit, D10/V4) — the key
// is the only secret; cert/ca are public but kept in the same secure store so
// `build_client` can load the identity without an AppHandle. Each workspace has
// its own identity: the entries lie behind its keyring prefix (`keyring_key`).
const KEYRING_KEY: &str = "enroll|key"; // the EC private key (PKCS#8 PEM)
const KEYRING_CERT: &str = "enroll|cert"; // fullchain: leaf + access intermediate
const KEYRING_CA: &str = "enroll|ca"; // chain: access intermediate + root

/// The fingerprint of a leaf this device reset while the server could not revoke
/// it (R-0224): the next enrollment names it as replaced, so its line goes then.
const KEYRING_REPLACES: &str = "enroll|replaces";

/// The grant the server returns from `POST /api/enrollment/token`. The host is
/// not carried — the desktop reuses the (already TLS-trusted) server URL it is
/// logged into + `enroll_port`, mirroring the Go agent.
#[derive(Debug, Deserialize)]
pub struct EnrollGrant {
    pub token: String,
    #[serde(rename = "subjectId")]
    pub subject_id: String,
    pub scope: String,
    #[serde(rename = "enrollPort")]
    pub enroll_port: u16,
}

/// Body for the ca-issuer `/enroll` (token + PEM CSR).
#[derive(Debug, Serialize)]
pub struct EnrollRequest<'a> {
    pub token: &'a str,
    pub csr: &'a str,
    /// Fingerprint of the certificate this device held before (R-0224): the issuer
    /// revokes its device line. Never sent for a browser export, which is a device
    /// of its own.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub replaces: Option<&'a str>,
}

/// Body for `/ca/renew` (CSR only; the issuer derives the identity from the
/// presented client cert, verified by the gateway — not from the CSR).
#[derive(Debug, Serialize)]
struct RenewRequest<'a> {
    csr: &'a str,
}

/// Renew once the leaf is half through its lifetime (ADR 0001 §3.3) — overlap so
/// a briefly unreachable issuer never locks the user out.
const RENEWAL_FRACTION: f64 = 0.5;

/// The gateway's certless enroll-plane port (ADR 0001 §3.2 / D11). The coupled
/// flow learns it from the server grant; the decoupled flow (ADR 0003) assumes
/// this default — matching the server's `ENROLL_PORT` default and the Go agent.
const DEFAULT_ENROLL_PORT: u16 = 8444;

/// What `/enroll` (and later `/renew`) returns (the bare `cert` leaf is ignored —
/// we present and pin chains).
///
/// * `fullchain` leaf + access intermediate (what we present in mTLS)
/// * `chain`     access intermediate + root (what we pin and verify against)
#[derive(Debug, Deserialize)]
pub struct IssuedIdentity {
    pub fullchain: String,
    pub chain: String,
}

/// A freshly generated on-device key (PKCS#8 PEM) and its CSR (PEM). The issuer
/// dictates the real identity (CN + scope) from the server-minted grant, so the
/// CSR subject is only cosmetic — a client cannot widen its identity via the CSR.
pub struct KeyAndCsr {
    pub key_pem: String,
    pub csr_pem: String,
}

/// Serialize a PEM CSR for `common_name` signed by `key_pair`. The issuer
/// dictates the real identity, so the CSR subject is only cosmetic.
fn build_csr(key_pair: &rcgen::KeyPair, common_name: &str) -> Result<String, AppError> {
    use rcgen::{CertificateParams, DistinguishedName, DnType};

    let mut params =
        CertificateParams::new(vec![]).map_err(|e| AppError::Validation(format!("CSR: {e}")))?;
    let mut dn = DistinguishedName::new();
    dn.push(DnType::CommonName, common_name);
    params.distinguished_name = dn;

    let csr = params
        .serialize_request(key_pair)
        .map_err(|e| AppError::Validation(format!("CSR signieren: {e}")))?;
    csr.pem()
        .map_err(|e| AppError::Validation(format!("CSR-PEM: {e}")))
}

/// Generate an ECDSA P-256 keypair and a CSR for `common_name` (D10: fits the
/// Windows keyring limit, modern, ideal for short-lived certs).
pub fn generate_key_and_csr(common_name: &str) -> Result<KeyAndCsr, AppError> {
    use rcgen::{KeyPair, PKCS_ECDSA_P256_SHA256};

    let key_pair = KeyPair::generate_for(&PKCS_ECDSA_P256_SHA256)
        .map_err(|e| AppError::Validation(format!("Schlüssel erzeugen: {e}")))?;
    let csr_pem = build_csr(&key_pair, common_name)?;

    Ok(KeyAndCsr {
        key_pem: key_pair.serialize_pem(),
        csr_pem,
    })
}

/// Build a CSR for an EXISTING on-device key (renewal reuses the key). Reusing
/// the key is what keeps the keyring swap crash-safe: the keyring cannot
/// atomically replace a key+cert pair, so minting a fresh key would risk leaving
/// a new key paired with the old cert if interrupted between the two writes — a
/// mismatch that breaks mTLS and locks the device out (F5 / ADR 0001 §3.3).
fn csr_for_existing_key(key_pem: &str, common_name: &str) -> Result<String, AppError> {
    let key_pair = rcgen::KeyPair::from_pem(key_pem)
        .map_err(|e| AppError::Validation(format!("Vorhandenen Schlüssel laden: {e}")))?;
    build_csr(&key_pair, common_name)
}

/// Derive the gateway enroll endpoint from the trusted server URL + the enroll
/// port (the server has no reliable view of its own public address).
pub fn enroll_endpoint(server_url: &str, port: u16) -> Result<String, AppError> {
    let mut url = Url::parse(server_url)
        .map_err(|e| AppError::Validation(format!("Server-URL ungültig: {e}")))?;
    url.set_port(Some(port))
        .map_err(|_| AppError::Validation("Enroll-Port nicht setzbar".to_string()))?;
    url.set_path("/enroll");
    url.set_query(None);
    Ok(url.to_string())
}

// ── Identity storage (keyring) ────────────────────────────────────────────

/// The keyring prefix of the workspace of this process (R-0431). The launcher
/// has no workspace and so no identity: an error, never a key without a prefix.
fn keyring_prefix() -> Result<String, AppError> {
    Ok(crate::workspace::current()?.keyring_prefix())
}

/// The keyring key of the identity entry `entry` in the workspace of this process.
fn keyring_key(entry: &str) -> Result<String, AppError> {
    Ok(format!("{}{entry}", keyring_prefix()?))
}

/// The identity entry `entry` of the workspace of this process; none in the launcher.
fn read(entry: &str) -> Option<String> {
    keyring_store::get(&keyring_key(entry).ok()?)
}

// ── The identity as read once (R-0644) ────────────────────────────────────
//
// Every request built a client and read key, cert and CA chain from the system keyring
// for it; a keyring that answered slowly slowed every request, and one that failed once
// made requests go out without the device certificate. The entries are read once per
// process (per thread in test builds, like keyring_store::memory) and again only after
// enrolling, renewing or resetting the identity, through `reload_identity`.

/// Key, fullchain and CA chain of the workspace behind `prefix`, as read.
#[derive(Clone)]
struct HeldIdentity {
    prefix: String,
    key: Option<String>,
    cert: Option<String>,
    ca: Option<String>,
}

/// The held identity with the generation it was read in; a reload bumps the generation,
/// so a read that a reload overlapped does not keep its result.
#[derive(Default)]
struct IdentityCell {
    generation: u64,
    held: Option<HeldIdentity>,
}

#[cfg(not(test))]
fn with_cell<T>(f: impl FnOnce(&mut IdentityCell) -> T) -> T {
    static CELL: std::sync::Mutex<IdentityCell> = std::sync::Mutex::new(IdentityCell {
        generation: 0,
        held: None,
    });
    f(&mut CELL.lock().unwrap_or_else(|e| e.into_inner()))
}

// Per thread and per in-memory keyring: a test thread runs many tests, each with a keyring
// of its own, and what one held must not reach the next.
#[cfg(test)]
fn with_cell<T>(f: impl FnOnce(&mut IdentityCell) -> T) -> T {
    thread_local! {
        static CELL: std::cell::RefCell<(u64, IdentityCell)> =
            std::cell::RefCell::new((0, IdentityCell::default()));
    }
    CELL.with(|cell| {
        let mut cell = cell.borrow_mut();
        let epoch = keyring_store::memory_epoch();
        if cell.0 != epoch {
            *cell = (epoch, IdentityCell::default());
        }
        f(&mut cell.1)
    })
}

/// The identity of the workspace of this process, read once; none in the launcher and
/// none for a call whose keyring read failed (warned once, not held, read again next time).
fn held_identity() -> Option<HeldIdentity> {
    held_identity_with(keyring_store::try_get)
}

fn held_identity_with(
    read: impl Fn(&str) -> Result<Option<String>, AppError>,
) -> Option<HeldIdentity> {
    let prefix = keyring_prefix().ok()?;
    let (generation, held) = with_cell(|cell| (cell.generation, cell.held.clone()));
    if let Some(held) = held.filter(|held| held.prefix == prefix) {
        return Some(held);
    }
    // No lock across the keyring: it may take its time, and the cell only guards itself.
    let entry = |name: &str| read(&format!("{prefix}{name}"));
    let read_all = || -> Result<HeldIdentity, AppError> {
        Ok(HeldIdentity {
            prefix: prefix.clone(),
            key: entry(KEYRING_KEY)?,
            cert: entry(KEYRING_CERT)?,
            ca: entry(KEYRING_CA)?,
        })
    };
    match read_all() {
        Ok(held) => {
            with_cell(|cell| {
                if cell.generation == generation {
                    cell.held = Some(held.clone());
                }
            });
            Some(held)
        }
        Err(e) => {
            static WARNED: std::sync::atomic::AtomicBool =
                std::sync::atomic::AtomicBool::new(false);
            if !WARNED.swap(true, std::sync::atomic::Ordering::Relaxed) {
                log::warn!("reading the device identity from the keyring failed, requests go without it for now: {e}");
            }
            None
        }
    }
}

/// Drop the held identity and the cached http client (it bakes in the trust anchor), so the
/// next use reads what the keyring holds now: after enrolling, renewing and resetting.
pub(crate) fn reload_identity() {
    with_cell(|cell| {
        cell.generation += 1;
        cell.held = None;
    });
    crate::http_client::invalidate_client_cache();
}

/// Delete the identity entry `entry` of the workspace of this process, best effort;
/// the launcher has none to delete.
fn forget(entry: &str) {
    if let Ok(key) = keyring_key(entry) {
        let _ = keyring_store::delete(&key);
    }
}

/// Persist a renewed identity: key + fullchain + pinned CA chain. On renew the
/// key is unchanged (the cert is re-issued for the same key, see `renew`), so a
/// partial write can never produce a key/cert mismatch — the keyring's lack of
/// an atomic multi-entry swap is thereby moot. A new enrollment brings a new key
/// and goes through `replace_identity` instead.
fn store_identity(key_pem: &str, issued: &IssuedIdentity) -> Result<(), AppError> {
    let prefix = keyring_prefix()?;
    keyring_store::set(&format!("{prefix}{KEYRING_KEY}"), key_pem)?;
    keyring_store::set(&format!("{prefix}{KEYRING_CERT}"), &issued.fullchain)?;
    keyring_store::set(&format!("{prefix}{KEYRING_CA}"), &issued.chain)?;
    // The held identity and the cached http client (it bakes in the previous trust anchor) go,
    // so the next build_client picks up the newly enrolled identity (5.1).
    reload_identity();
    Ok(())
}

/// Replace whatever identity the keyring holds with a freshly enrolled one
/// (R-0220). Unlike `renew`, an enrollment brings a NEW key: written over an old
/// identity it would sit next to the OLD cert until the cert write lands, and a
/// crash in between is a mismatch that locks the device out under enforced mTLS.
/// So the old entries go first — the cert first, so the device stops counting as
/// enrolled (`is_enrolled`) before anything else changes — and a failed delete
/// stops before anything is written. The new cert goes last, so the device counts
/// as enrolled only once key, CA chain and cert are all in place. Every state a
/// crash can leave is the old identity untouched, no identity, or the new one.
/// The keyring calls come in as parameters, so a test can fail any one of them;
/// they get the entry names, the caller puts the workspace's prefix in front.
fn replace_identity(
    key_pem: &str,
    issued: &IssuedIdentity,
    mut delete: impl FnMut(&str) -> Result<(), AppError>,
    mut set: impl FnMut(&str, &str) -> Result<(), AppError>,
) -> Result<(), AppError> {
    for entry in [KEYRING_CERT, KEYRING_KEY, KEYRING_CA] {
        delete(entry)?;
    }
    set(KEYRING_KEY, key_pem)?;
    set(KEYRING_CA, &issued.chain)?;
    set(KEYRING_CERT, &issued.fullchain)
}

/// The stored identity of the workspace of this process as `(key_pem,
/// fullchain_pem, ca_pem)`, if enrolled; none in the launcher. Used
/// internally and by the frpc visitor (F2) to present the desktop's access cert
/// on the frp plane (frps trusts the access intermediate).
pub(crate) fn load_identity() -> Option<(String, String, String)> {
    let held = held_identity()?;
    Some((held.key?, held.cert?, held.ca?))
}

/// Whether the workspace of this process has an enrolled mTLS identity (key +
/// cert present); the launcher never has one.
pub fn is_enrolled() -> bool {
    held_identity().is_some_and(|held| held.key.is_some() && held.cert.is_some())
}

/// Whether the keyring holds an entry of the identity behind `prefix`, the keyring
/// prefix of a workspace this process does not serve: for the launcher, before the
/// URL of a workspace names another server. Not the leaf a reset remembers
/// (`enroll|replaces`): without an identity, a purge asks no server. A keyring
/// that does not answer is an error, as then no one can tell.
pub fn holds_identity(prefix: &str) -> Result<bool, AppError> {
    for entry in [KEYRING_KEY, KEYRING_CERT, KEYRING_CA] {
        if keyring_store::try_get(&format!("{prefix}{entry}"))?.is_some() {
            return Ok(true);
        }
    }
    Ok(false)
}

/// SHA-256 (lowercase hex) of the pinned access-intermediate CA — the FIRST
/// certificate of the enrolled chain (`enroll|ca` = intermediate + root). The
/// provisioning tab embeds it as the agent's `--ca-fp`, turning the agent's
/// first contact into a verified handshake instead of blind TOFU: the gateway
/// presents exactly this intermediate in its TLS chain (fullchain = leaf +
/// intermediate), so the value survives leaf rotation. `None` until enrolled.
pub fn pinned_ca_fingerprint() -> Option<String> {
    ca_fingerprint_of_chain(&held_identity()?.ca?)
}

/// The fingerprint of the first PEM certificate in `chain_pem`. Split out so it
/// is unit-testable without a keyring.
fn ca_fingerprint_of_chain(chain_pem: &str) -> Option<String> {
    let cert = CertificateDer::pem_slice_iter(chain_pem.as_bytes())
        .next()?
        .ok()?;
    Some(crate::tofu::fingerprint(cert.as_ref()))
}

/// SHA-256 (lowercase hex) of the stored leaf: the fullchain begins with it.
fn leaf_fingerprint() -> Option<String> {
    ca_fingerprint_of_chain(&held_identity()?.cert?)
}

/// What the settings and the renewal read from a leaf: its common name, if it
/// carries a readable one, and its validity in seconds since the epoch.
struct Leaf {
    common_name: Option<String>,
    not_before: i64,
    not_after: i64,
}

/// Parse the leaf, the first certificate of `cert_pem` (a fullchain begins with it).
fn parse_leaf(cert_pem: &str) -> Result<Leaf, AppError> {
    let leaf = CertificateDer::pem_slice_iter(cert_pem.as_bytes())
        .next()
        .ok_or_else(|| AppError::Validation("Kein Zertifikat im PEM".to_string()))?
        .map_err(|e| AppError::Validation(format!("Zertifikat nicht lesbar: {e}")))?;
    let (_, cert) = x509_parser::parse_x509_certificate(&leaf)
        .map_err(|e| AppError::Validation(format!("Zertifikat parsen: {e}")))?;
    let common_name = cert
        .subject()
        .iter_common_name()
        .next()
        .and_then(|cn| cn.as_str().ok())
        .map(str::to_owned);
    Ok(Leaf {
        common_name,
        not_before: cert.validity().not_before.timestamp(),
        not_after: cert.validity().not_after.timestamp(),
    })
}

/// Name and expiry of the device certificate in `cert_pem`. The name is the
/// leaf's CN, which the issuer sets to the enrolled subject.
fn identity_of(cert_pem: &str) -> Result<DeviceIdentity, AppError> {
    let leaf = parse_leaf(cert_pem)?;
    let name = leaf
        .common_name
        .ok_or_else(|| AppError::Validation("device certificate has no common name".to_string()))?;
    let not_after = chrono::DateTime::from_timestamp(leaf.not_after, 0)
        .ok_or_else(|| AppError::Validation("device certificate expiry out of range".to_string()))?
        .to_rfc3339();
    Ok(DeviceIdentity { name, not_after })
}

/// Name and expiry of this device's enrolled certificate for the settings.
/// `None` without key or cert (the rule of `is_enrolled`); an error when the
/// stored cert does not parse or has no CN.
pub fn device_identity() -> Result<Option<DeviceIdentity>, AppError> {
    let Some(held) = held_identity() else {
        return Ok(None);
    };
    let (Some(_), Some(cert_pem)) = (held.key, held.cert) else {
        return Ok(None);
    };
    identity_of(&cert_pem).map(Some)
}

/// What an enrollment is for: this device's own identity, or a browser
/// certificate exported from it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum EnrollmentKind {
    Device,
    Browser,
}

/// What an enrollment names as replaced (R-0224). The device's own enrollment
/// replaces the leaf it holds, else one it reset while the server was out of reach.
/// A browser certificate is a device of its own and replaces nothing — naming the
/// desktop's leaf there would revoke the desktop.
fn replaces_for(
    kind: EnrollmentKind,
    held: Option<String>,
    pending: Option<String>,
) -> Option<String> {
    match kind {
        EnrollmentKind::Device => held.or(pending),
        EnrollmentKind::Browser => None,
    }
}

/// What an enrollment of `kind` names as replaced, read from the keyring.
fn pending_replaces(kind: EnrollmentKind) -> Option<String> {
    replaces_for(kind, leaf_fingerprint(), read(KEYRING_REPLACES))
}

/// Once the new identity is stored, the remembered leaf has been named and is done
/// with; after a failed store it stays for the next enrollment.
fn settle_replaces(stored: &Result<(), AppError>) {
    if stored.is_ok() {
        forget(KEYRING_REPLACES);
    }
}

/// How resetting the device identity went (R-0224).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum ResetOutcome {
    /// The server revoked the device (or had already refused its certificate).
    Revoked,
    /// Deleted here only: the server could not be asked. The next enrollment of
    /// this device names the old certificate as replaced.
    LocalOnly,
    /// There was no identity to revoke.
    NotEnrolled,
}

/// Reset the device identity: revoke it at the server with this very certificate,
/// then delete it here. The revocation goes first, because without the key the
/// device can no longer prove which certificate it means.
pub async fn reset_identity(server_url: &str) -> ResetOutcome {
    reset_with(
        leaf_fingerprint(),
        || revoke_on_server(server_url),
        clear_identity,
        |fingerprint| {
            if let Ok(key) = keyring_key(KEYRING_REPLACES) {
                let _ = keyring_store::set(&key, fingerprint);
            }
        },
    )
    .await
}

/// The order of `reset_identity`, with the keyring and the server call as
/// parameters, so a test can see the order and choose the server's answer.
async fn reset_with<F, Fut>(
    fingerprint: Option<String>,
    revoke: F,
    clear: impl FnOnce(),
    remember: impl FnOnce(&str),
) -> ResetOutcome
where
    F: FnOnce() -> Fut,
    Fut: std::future::Future<Output = Result<bool, AppError>>,
{
    let Some(fingerprint) = fingerprint else {
        clear();
        return ResetOutcome::NotEnrolled;
    };
    let revoked = matches!(revoke().await, Ok(true));
    clear();
    if revoked {
        ResetOutcome::Revoked
    } else {
        remember(&fingerprint);
        ResetOutcome::LocalOnly
    }
}

/// `POST /api/enrollment/self/revoke` with the enrolled mTLS client: the
/// certificate is the proof, no JWT. The CA pin keeps the call on our server.
async fn revoke_on_server(server_url: &str) -> Result<bool, AppError> {
    // Only over https, on loopback too: over plain http anyone on the path, or any
    // program of this machine on that port, could answer "revoked" without the CA
    // pin, and the leaf would not be remembered. The reset is then LocalOnly.
    crate::validation::validate_https_url(server_url)?;
    let client = enrolled_client()?;
    let url = format!(
        "{}/api/enrollment/self/revoke",
        server_url.trim_end_matches('/')
    );
    let resp = client.post(&url).send().await?;
    let status = resp.status().as_u16();
    let body = resp.text().await.unwrap_or_default();
    Ok(revoked_by(status, &body))
}

/// Whether the server's answer means the device is revoked: done now (2xx), or
/// refused already as revoked (403 whose `code` is ERR_CERT_REVOKED).
fn revoked_by(status: u16, body: &str) -> bool {
    (200..300).contains(&status)
        || (status == 403 && AppError::http(status, body).code() == "ERR_CERT_REVOKED")
}

/// Forget the enrolled mTLS identity. NOT called on logout (that would lock the
/// user out under enforced mTLS — the cert is needed to reach the login). Invoked
/// by the explicit "reset device identity" settings action (`reset_device_identity`)
/// — the recovery path after a server reinstall / PKI re-creation.
pub fn clear_identity() {
    forget(KEYRING_KEY);
    forget(KEYRING_CERT);
    forget(KEYRING_CA);
    // Drop the held identity and the cached mTLS client so the next build_client falls back to
    // the non-enrolled path (5.1).
    reload_identity();
}

/// Forget every identity entry of the workspace of this process, the leaf it
/// remembers for its next enrollment (`enroll|replaces`) too: for the purge of
/// the workspace (R-0431), after which no enrollment of it follows. Unlike
/// `clear_identity`, a delete that fails is an error, so the purge stops while
/// the workspace is still there to delete again; the launcher has no entries.
pub fn purge_identity() -> Result<(), AppError> {
    for entry in [KEYRING_CERT, KEYRING_KEY, KEYRING_CA, KEYRING_REPLACES] {
        keyring_store::delete(&keyring_key(entry)?)?;
    }
    reload_identity();
    Ok(())
}

// ── Enrollment orchestration ──────────────────────────────────────────────

/// Decoupled enrollment (ADR 0003): enroll with a one-time token an admin minted
/// out-of-band (`POST /api/enrollment/token/for`) and handed over — **without** a
/// prior login. Skips `mint_token` (the token already exists), so it works under
/// enforced mTLS where a certless client cannot reach the login on `:443`. The
/// issuer dictates the cert CN from the token's subject (issuer.py:
/// `subject_cn=grant.subject_id`), so the CSR CN here is only a placeholder.
/// TLS trust follows the same setting as the login: with `allow_self_signed`
/// the first contact TOFU-pins the gateway leaf (same leaf as `:443`), like the
/// agent's first enrollment; without it the public-CA path applies — against
/// the standard install's own-PKI gateway that fails as ERR_TLS_UNKNOWN_ISSUER
/// (error.rs), which the login screen answers with its trust dialog (retry with
/// the setting on). Assumes the default enroll port; a non-default port must be
/// reachable under that name.
pub async fn enroll_with_token(
    server_url: &str,
    token: &str,
    allow_self_signed: bool,
) -> Result<(), AppError> {
    // Before the token reaches the server: the launcher has nowhere to keep an
    // identity, and a redeemed one-time token is spent.
    let prefix = keyring_prefix()?;
    let key_and_csr = generate_key_and_csr("adminhelper-enrollment")?;
    let endpoint = enroll_endpoint(server_url, DEFAULT_ENROLL_PORT)?;
    let replaces = pending_replaces(EnrollmentKind::Device);
    let issued = redeem(
        &endpoint,
        token,
        &key_and_csr.csr_pem,
        replaces.as_deref(),
        server_url,
        allow_self_signed,
    )
    .await?;
    let stored = replace_identity(
        &key_and_csr.key_pem,
        &issued,
        |entry| keyring_store::delete(&format!("{prefix}{entry}")),
        |entry, value| keyring_store::set(&format!("{prefix}{entry}"), value),
    );
    // Even a failed replace may have deleted the old entries: drop the held identity and the
    // cached client either way, so the next build_client sees what is there (5.1).
    reload_identity();
    settle_replaces(&stored);
    stored
}

/// Mint the long-lived browser grant (`?browser=true`, D5) with the session's token —
/// the only token the desktop mints itself; its own identity comes from a
/// one-time token an admin handed over (`enroll_with_token`, ADR 0003). The grant
/// comes with the session it was minted for: its server, where the certificate is
/// enrolled, and the certificate choice of that sign-in.
async fn mint_token(session: &SessionState) -> Result<(EnrollGrant, SignedIn), AppError> {
    // Through authed_send: the session's server, token and certificate choice, never a
    // URL or a trust setting from the webview, so no frontend can carry the bearer token
    // to a foreign host (3.18) — nor have build_client pin a foreign cert on first use
    // (TOFU) before the first enrollment. A 401 renews the session once, like every other
    // request.
    let (resp, minted_for) =
        crate::session::authed_send(session, |server_url, allow_self_signed| {
            let client = crate::http_client::build_client(server_url, allow_self_signed)?;
            let base = server_url.trim_end_matches('/');
            Ok(client.post(format!("{base}/api/enrollment/token?browser=true")))
        })
        .await?;
    if !resp.status().is_success() {
        let status = resp.status();
        let text = crate::diagnostics::redact_body(&resp.text().await.unwrap_or_default());
        return Err(AppError::Validation(format!(
            "Enrollment-Token anfordern fehlgeschlagen ({status}): {text}"
        )));
    }
    Ok((resp.json().await?, minted_for))
}

async fn redeem(
    endpoint: &str,
    token: &str,
    csr_pem: &str,
    replaces: Option<&str>,
    server_url: &str,
    allow_self_signed: bool,
) -> Result<IssuedIdentity, AppError> {
    // build_client pins by the login host; the gateway presents the same leaf on
    // the enroll plane, so that pin applies to this call too.
    let client = crate::http_client::build_client(server_url, allow_self_signed)?;
    let resp = client
        .post(endpoint)
        .json(&EnrollRequest {
            token,
            csr: csr_pem,
            replaces,
        })
        .send()
        .await?;
    if !resp.status().is_success() {
        let status = resp.status();
        let text = crate::diagnostics::redact_body(&resp.text().await.unwrap_or_default());
        return Err(AppError::Validation(format!(
            "Enrollment am ca-issuer fehlgeschlagen ({status}): {text}"
        )));
    }
    let issued: IssuedIdentity = resp.json().await?;
    if issued.fullchain.is_empty() || issued.chain.is_empty() {
        return Err(AppError::Validation(
            "Unvollständige Enrollment-Antwort (fullchain/chain fehlt)".to_string(),
        ));
    }
    Ok(issued)
}

// ── Renewal ────────────────────────────────────────────────────────────────

/// Whether the leaf in `cert_pem` is past `fraction` of its lifetime at
/// `now_unix` (seconds since the epoch). `now` is a parameter so the decision is
/// deterministically testable.
fn needs_renewal(cert_pem: &str, fraction: f64, now_unix: i64) -> Result<bool, AppError> {
    let Leaf {
        not_before,
        not_after,
        ..
    } = parse_leaf(cert_pem)?;
    let total = not_after - not_before;
    if total <= 0 {
        return Ok(true); // malformed / already expired -> renew
    }
    Ok((now_unix - not_before) as f64 >= total as f64 * fraction)
}

fn now_unix() -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// Renew the enrolled identity: present the CURRENT cert (mTLS) to
/// `<server_url>/ca/renew` with a fresh CSR, then store the new key + cert. The
/// issuer re-uses the presented cert's identity, so the CSR subject is cosmetic.
async fn renew(server_url: &str) -> Result<(), AppError> {
    let client = enrolled_client()?;
    // Reuse the existing private key (see `csr_for_existing_key`): the keyring
    // cannot atomically swap a key+cert pair, so keeping the key stable means
    // every crash state stays consistent — the cert always matches the key.
    let (key_pem, _, _) =
        load_identity().ok_or_else(|| AppError::Keyring("Keine enrollte Identität".to_string()))?;
    let csr_pem = csr_for_existing_key(&key_pem, "renew")?;
    let url = format!("{}/ca/renew", server_url.trim_end_matches('/'));
    let resp = client
        .post(&url)
        .json(&RenewRequest { csr: &csr_pem })
        .send()
        .await?;
    if !resp.status().is_success() {
        let status = resp.status();
        let text = crate::diagnostics::redact_body(&resp.text().await.unwrap_or_default());
        return Err(AppError::Validation(format!(
            "Zertifikat-Renew fehlgeschlagen ({status}): {text}"
        )));
    }
    let issued: IssuedIdentity = resp.json().await?;
    if issued.fullchain.is_empty() || issued.chain.is_empty() {
        return Err(AppError::Validation(
            "Unvollständige Renew-Antwort".to_string(),
        ));
    }
    // Same key, new cert + chain — the pair stays consistent through the write.
    store_identity(&key_pem, &issued)
}

/// Renew the enrolled identity if it is due. Returns whether a renewal happened.
/// A no-op when not enrolled. Best-effort at the call site — a transient issuer
/// outage must not lock the user out (the current cert is still valid).
pub async fn maybe_renew(server_url: &str) -> Result<bool, AppError> {
    let Some((_, cert_pem, _)) = load_identity() else {
        return Ok(false);
    };
    if !needs_renewal(&cert_pem, RENEWAL_FRACTION, now_unix())? {
        return Ok(false);
    }
    renew(server_url).await?;
    Ok(true)
}

// ── mTLS client (CA-pinning, hostname-agnostic) ───────────────────────────

/// Server verifier that pins the enrolled CA chain: it accepts a server cert
/// that chains to the pinned CA but, unlike standard validation, does NOT check
/// the hostname — the pin is the CA, the way TOFU treats the leaf as the
/// identity. So an enrolled device never breaks because it reaches the server by
/// a host/IP outside the gateway leaf's SANs, while still rejecting any cert that
/// does not chain to our CA (and surviving gateway leaf rotation, D2).
#[derive(Debug)]
struct CaPinVerifier {
    inner: Arc<WebPkiServerVerifier>,
}

impl ServerCertVerifier for CaPinVerifier {
    fn verify_server_cert(
        &self,
        end_entity: &CertificateDer<'_>,
        intermediates: &[CertificateDer<'_>],
        server_name: &ServerName<'_>,
        ocsp_response: &[u8],
        now: UnixTime,
    ) -> Result<ServerCertVerified, TlsError> {
        match self.inner.verify_server_cert(
            end_entity,
            intermediates,
            server_name,
            ocsp_response,
            now,
        ) {
            Ok(verified) => Ok(verified),
            // webpki validates the chain to a trust anchor BEFORE the name, so a
            // name error means the chain already validated against our pinned CA —
            // accept it (hostname intentionally not enforced). rustls 0.23 reports
            // this as either NotValidForName or the richer NotValidForNameContext.
            Err(TlsError::InvalidCertificate(
                CertificateError::NotValidForName | CertificateError::NotValidForNameContext { .. },
            )) => Ok(ServerCertVerified::assertion()),
            // The presented cert does NOT chain to the CA pinned at enrollment:
            // no path to the pinned anchor (UnknownIssuer) or the leaf signature
            // does not verify against it (BadSignature — what a single-leaf chain
            // under a foreign CA actually yields). Either an on-path attacker, or
            // the server's PKI was re-created (a reinstall) — we cannot tell the
            // two apart, so fail closed with an explicit, danger-aware message
            // that names the recovery action, mirroring the TOFU leaf-pin message.
            // Temporal errors (Expired/NotYetValid) fall through unchanged — a
            // different problem the identity reset would not fix.
            Err(TlsError::InvalidCertificate(
                CertificateError::UnknownIssuer | CertificateError::BadSignature,
            )) => Err(TlsError::General(
                // ERR_CA_PIN_MISMATCH is the stable contract the login screen keys
                // the "reset device identity" recovery off (Login.svelte), so that
                // action never depends on the German prose below staying verbatim.
                "ERR_CA_PIN_MISMATCH: AdminHelper: Das Server-Zertifikat wird nicht mehr von der \
                     bei der Geräte-Registrierung gepinnten CA gedeckt (mögliche MITM-Attacke). \
                     Wurde der Server neu installiert oder die PKI neu erzeugt, in den \
                     Einstellungen die Geräte-Identität zurücksetzen und neu registrieren."
                    .to_string(),
            )),
            Err(err) => Err(err),
        }
    }

    fn verify_tls12_signature(
        &self,
        message: &[u8],
        cert: &CertificateDer<'_>,
        dss: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, TlsError> {
        self.inner.verify_tls12_signature(message, cert, dss)
    }

    fn verify_tls13_signature(
        &self,
        message: &[u8],
        cert: &CertificateDer<'_>,
        dss: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, TlsError> {
        self.inner.verify_tls13_signature(message, cert, dss)
    }

    fn supported_verify_schemes(&self) -> Vec<SignatureScheme> {
        self.inner.supported_verify_schemes()
    }
}

/// Build the mTLS client from PEM material: present the client cert and verify
/// the server against the pinned CA (hostname-agnostic, ring provider matched to
/// the rest of the app). Split out from `enrolled_client` so it is unit-testable
/// without a keyring.
fn build_mtls_client(
    key_pem: &str,
    cert_pem: &str,
    ca_pem: &str,
) -> Result<reqwest::Client, AppError> {
    let mut roots = RootCertStore::empty();
    for cert in CertificateDer::pem_slice_iter(ca_pem.as_bytes()) {
        let cert = cert.map_err(|e| AppError::Validation(format!("CA-Kette nicht lesbar: {e}")))?;
        roots
            .add(cert)
            .map_err(|e| AppError::Validation(format!("CA ungültig: {e}")))?;
    }
    let verifier =
        WebPkiServerVerifier::builder_with_provider(Arc::new(roots), crate::tofu::ring_provider())
            .build()
            .map_err(|e| AppError::Validation(format!("CA-Verifier: {e}")))?;

    let client_certs: Vec<CertificateDer<'static>> =
        CertificateDer::pem_slice_iter(cert_pem.as_bytes())
            .collect::<Result<_, _>>()
            .map_err(|e| AppError::Validation(format!("Client-Zertifikat nicht lesbar: {e}")))?;
    let client_key: PrivateKeyDer<'static> = PrivateKeyDer::from_pem_slice(key_pem.as_bytes())
        .map_err(|e| AppError::Validation(format!("Client-Schlüssel nicht lesbar: {e}")))?;

    let tls = rustls::ClientConfig::builder_with_provider(crate::tofu::ring_provider())
        .with_safe_default_protocol_versions()
        .map_err(|e| AppError::Connection(format!("TLS-Konfiguration: {e}")))?
        .dangerous()
        .with_custom_certificate_verifier(Arc::new(CaPinVerifier { inner: verifier }))
        .with_client_auth_cert(client_certs, client_key)
        .map_err(|e| AppError::Validation(format!("Client-Auth: {e}")))?;

    crate::http_client::with_timeouts(reqwest::Client::builder())
        .use_preconfigured_tls(tls)
        .build()
        .map_err(AppError::from)
}

/// The reqwest client for the enrolled state: present our client cert + CA-pin
/// the server. Loads the identity from the keyring (no AppHandle needed).
pub fn enrolled_client() -> Result<reqwest::Client, AppError> {
    let (key_pem, cert_pem, ca_pem) =
        load_identity().ok_or_else(|| AppError::Keyring("Keine enrollte Identität".to_string()))?;
    build_mtls_client(&key_pem, &cert_pem, &ca_pem)
}

// ── Browser PKCS12 export (A5c) ───────────────────────────────────────────

/// Package a leaf cert + its PKCS#8 key as a password-protected PKCS12 (.p12)
/// for import into a browser's certificate store. The key is opaque PKCS8 bytes
/// to the builder, so the ECDSA leaf packages fine. Split out for a structural
/// round-trip test.
/// The p12 crate emits a classic PKCS12 container (PBE-SHA1/RC2, low iteration count),
/// so the .p12's key-encryption KDF is weak. The file carries a long-lived browser
/// client key and is written to disk, so a short/weak export password would be a
/// realistic offline brute-force target if the file leaks — require a strong one to
/// keep the wrapping robust despite the weak KDF (3.58).
fn check_export_password(password: &str) -> Result<(), AppError> {
    if password.chars().count() < 12 {
        return Err(AppError::Validation(
            "Export-Passwort zu kurz (mindestens 12 Zeichen)".to_string(),
        ));
    }
    Ok(())
}

fn package_pkcs12(
    key_pem: &str,
    cert_pem: &str,
    password: &str,
    friendly_name: &str,
) -> Result<Vec<u8>, AppError> {
    check_export_password(password)?; // defense in depth; export_browser_p12 checks early
    let cert = CertificateDer::pem_slice_iter(cert_pem.as_bytes())
        .next()
        .ok_or_else(|| AppError::Validation("Kein Zertifikat im PEM".to_string()))?
        .map_err(|e| AppError::Validation(format!("Zertifikat nicht lesbar: {e}")))?;
    let key = PrivateKeyDer::from_pem_slice(key_pem.as_bytes())
        .map_err(|e| AppError::Validation(format!("Schlüssel nicht lesbar: {e}")))?;
    let pfx = p12::PFX::new(
        cert.as_ref(),
        key.secret_der(),
        None,
        password,
        friendly_name,
    )
    .ok_or_else(|| AppError::Validation("PKCS12 erstellen fehlgeschlagen".to_string()))?;
    Ok(pfx.to_der())
}

/// Enroll a long-lived browser cert (D5: the browser cannot auto-renew) at the
/// signed-in server and return it as a PKCS12 blob for the user to import. Does
/// NOT touch the desktop's own keyring identity — this is a cert FOR the browser.
/// The enrollment reaches the server with the certificate choice of the sign-in.
pub async fn export_browser_p12(
    session: &SessionState,
    password: &str,
) -> Result<Vec<u8>, AppError> {
    // Fail fast before minting + enrolling a throwaway long-lived cert (3.58).
    check_export_password(password)?;
    let (grant, minted_for) = mint_token(session).await?;
    if grant.scope != "access" {
        return Err(AppError::Validation(format!(
            "Unerwarteter Enrollment-Scope '{}' (erwartet 'access')",
            grant.scope
        )));
    }
    let key_and_csr = generate_key_and_csr(&grant.subject_id)?;
    let endpoint = enroll_endpoint(&minted_for.server_url, grant.enroll_port)?;
    let replaces = pending_replaces(EnrollmentKind::Browser);
    let issued = redeem(
        &endpoint,
        &grant.token,
        &key_and_csr.csr_pem,
        replaces.as_deref(),
        &minted_for.server_url,
        minted_for.allow_self_signed,
    )
    .await?;
    package_pkcs12(
        &key_and_csr.key_pem,
        &issued.fullchain,
        password,
        &grant.subject_id,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::workspace::{self, Workspace, WorkspaceId};

    #[test]
    fn generate_key_and_csr_yields_ec_key_and_csr_pem() {
        let a = generate_key_and_csr("user-01").unwrap();
        assert!(
            a.key_pem.contains("PRIVATE KEY"),
            "kein Key-PEM: {}",
            a.key_pem
        );
        assert!(
            a.csr_pem.contains("CERTIFICATE REQUEST"),
            "kein CSR-PEM: {}",
            a.csr_pem
        );
    }

    #[test]
    fn each_keypair_is_fresh() {
        // No two on-device keys may be identical.
        let a = generate_key_and_csr("x").unwrap();
        let b = generate_key_and_csr("x").unwrap();
        assert_ne!(a.key_pem, b.key_pem);
    }

    #[test]
    fn renew_reuses_the_existing_key() {
        // F5: renewal must NOT mint a new key — the CSR it submits must carry the
        // SAME public key as the stored key, so a crash during the keyring write
        // can never leave a new key paired with the old cert (mismatch → lockout).
        use x509_parser::prelude::FromDer;

        let original = generate_key_and_csr("device").unwrap();
        let want_spki = rcgen::KeyPair::from_pem(&original.key_pem)
            .unwrap()
            .public_key_der();

        let csr_pem = csr_for_existing_key(&original.key_pem, "renew").unwrap();
        let (pem, _) =
            x509_parser::pem::Pem::read(std::io::Cursor::new(csr_pem.as_bytes())).unwrap();
        let (_, csr) =
            x509_parser::certification_request::X509CertificationRequest::from_der(&pem.contents)
                .unwrap();
        let got_spki = csr.certification_request_info.subject_pki.raw;

        assert_eq!(
            got_spki,
            want_spki.as_slice(),
            "Renew muss den vorhandenen Schlüssel wiederverwenden, nicht neu erzeugen"
        );
    }

    /// A keyring double for `replace_identity`: the entries plus a budget of
    /// calls after which every call fails — a crash between two writes.
    struct FakeKeyring {
        entries: std::collections::HashMap<String, String>,
        budget: usize,
    }

    impl FakeKeyring {
        fn with(entries: &[(&str, &str)], budget: usize) -> std::cell::RefCell<Self> {
            std::cell::RefCell::new(Self {
                entries: entries
                    .iter()
                    .map(|(k, v)| (k.to_string(), v.to_string()))
                    .collect(),
                budget,
            })
        }

        fn spend(&mut self) -> Result<(), AppError> {
            if self.budget == 0 {
                return Err(AppError::Keyring("simulated crash".to_string()));
            }
            self.budget -= 1;
            Ok(())
        }
    }

    const OLD: [(&str, &str); 3] = [
        (KEYRING_KEY, "old-key"),
        (KEYRING_CERT, "old-cert"),
        (KEYRING_CA, "old-ca"),
    ];

    fn replace_on(store: &std::cell::RefCell<FakeKeyring>) -> Result<(), AppError> {
        let issued = IssuedIdentity {
            fullchain: "new-cert".to_string(),
            chain: "new-ca".to_string(),
        };
        replace_identity(
            "new-key",
            &issued,
            |k| {
                let mut s = store.borrow_mut();
                s.spend()?;
                // A missing entry is success, as in keyring_store::delete.
                s.entries.remove(k);
                Ok(())
            },
            |k, v| {
                let mut s = store.borrow_mut();
                s.spend()?;
                s.entries.insert(k.to_string(), v.to_string());
                Ok(())
            },
        )
    }

    #[test]
    fn replace_identity_never_pairs_a_new_key_with_the_old_cert() {
        // R-0220: whatever call the crash hits, the keyring holds the old identity,
        // no identity, or the new one — never a key of one identity next to the
        // cert of the other, which locks the device out under enforced mTLS, and
        // never key and cert (is_enrolled) without the CA chain load_identity needs.
        for budget in 0..=6 {
            let store = FakeKeyring::with(&OLD, budget);
            let result = replace_on(&store);
            let s = store.borrow();
            let key = s.entries.get(KEYRING_KEY).map(String::as_str);
            let cert = s.entries.get(KEYRING_CERT).map(String::as_str);
            let ca = s.entries.get(KEYRING_CA).map(String::as_str);
            if (1..=5).contains(&budget) {
                // The first delete went through and the new identity is not complete.
                assert!(
                    key.is_none() || cert.is_none(),
                    "budget {budget}: an identity is left, key {key:?}, cert {cert:?}"
                );
            }
            if let (Some(key), Some(cert)) = (key, cert) {
                let identity = cert.split('-').next();
                assert_eq!(
                    key.split('-').next(),
                    identity,
                    "budget {budget}: key {key} next to cert {cert}"
                );
                assert_eq!(
                    ca.and_then(|ca| ca.split('-').next()),
                    identity,
                    "budget {budget}: cert {cert} next to CA {ca:?}"
                );
            }
            assert_eq!(result.is_ok(), budget >= 6, "budget {budget}");
        }
    }

    #[test]
    fn replace_identity_writes_nothing_when_a_delete_fails() {
        // Only the delete fails here and every write would go through: a failed
        // delete has to stop the replace before the first write, whichever entry
        // it hits — else the old cert could stay next to the new key.
        let issued = IssuedIdentity {
            fullchain: "new-cert".to_string(),
            chain: "new-ca".to_string(),
        };
        for failing in [KEYRING_CERT, KEYRING_KEY, KEYRING_CA] {
            let mut writes: Vec<String> = Vec::new();
            let result = replace_identity(
                "new-key",
                &issued,
                |k| {
                    if k == failing {
                        Err(AppError::Keyring("delete failed".to_string()))
                    } else {
                        Ok(())
                    }
                },
                |k, _| {
                    writes.push(k.to_string());
                    Ok(())
                },
            );
            assert!(result.is_err(), "{failing}: the replace went on");
            assert!(writes.is_empty(), "{failing}: wrote {writes:?}");
        }
    }

    #[test]
    fn replace_identity_without_an_old_identity_stores_the_new_one() {
        let store = FakeKeyring::with(&[], 6);
        replace_on(&store).unwrap();
        let s = store.borrow();
        assert_eq!(
            s.entries.get(KEYRING_KEY).map(String::as_str),
            Some("new-key")
        );
        assert_eq!(
            s.entries.get(KEYRING_CERT).map(String::as_str),
            Some("new-cert")
        );
        assert_eq!(
            s.entries.get(KEYRING_CA).map(String::as_str),
            Some("new-ca")
        );
    }

    // ── R-0224: replaces and the reset ─────────────────────────────────────

    #[test]
    fn the_enroll_body_names_the_replaced_certificate_only_when_there_is_one() {
        let with = serde_json::to_value(EnrollRequest {
            token: "t",
            csr: "c",
            replaces: Some("ab12"),
        })
        .unwrap();
        assert_eq!(with["replaces"], "ab12");
        let without = serde_json::to_value(EnrollRequest {
            token: "t",
            csr: "c",
            replaces: None,
        })
        .unwrap();
        assert!(without.get("replaces").is_none(), "{without}");
    }

    #[test]
    fn an_enrollment_replaces_the_held_leaf_before_a_remembered_one() {
        let held = Some("held".to_string());
        let remembered = Some("remembered".to_string());
        let device = EnrollmentKind::Device;
        assert_eq!(replaces_for(device, held.clone(), remembered.clone()), held);
        assert_eq!(replaces_for(device, None, remembered.clone()), remembered);
        assert_eq!(replaces_for(device, None, None), None);
    }

    #[test]
    fn a_browser_export_replaces_nothing_even_while_the_desktop_holds_a_leaf() {
        let held = Some("desktop-leaf".to_string());
        let remembered = Some("remembered".to_string());
        assert_eq!(
            replaces_for(EnrollmentKind::Browser, held, remembered),
            None
        );
    }

    #[test]
    fn the_server_answer_counts_as_revoked_when_done_or_already_refused() {
        assert!(revoked_by(204, ""));
        assert!(revoked_by(
            403,
            r#"{"detail":"ERR_CERT_REVOKED: no longer valid","code":"ERR_CERT_REVOKED"}"#
        ));
        // Only the field `code` counts, not the code somewhere in the text.
        assert!(!revoked_by(
            403,
            r#"{"detail":"server ERR_CERT_REVOKED","code":"ERR_CERT_USER_MISMATCH"}"#
        ));
        // A server without `code` (before R-0664) names it as prefix of `detail`.
        assert!(revoked_by(
            403,
            r#"{"detail":"ERR_CERT_REVOKED: no longer valid"}"#
        ));
        assert!(!revoked_by(
            403,
            r#"{"detail":"Kein gültiges Client-Zertifikat"}"#
        ));
        assert!(!revoked_by(409, "no device"));
        assert!(!revoked_by(502, ""));
    }

    #[tokio::test]
    async fn a_reset_revokes_at_the_server_before_it_deletes_here() {
        let calls = std::cell::RefCell::new(Vec::new());
        let outcome = reset_with(
            Some("fp".to_string()),
            || async {
                calls.borrow_mut().push("revoke");
                Ok(true)
            },
            || calls.borrow_mut().push("clear"),
            |_| calls.borrow_mut().push("remember"),
        )
        .await;
        assert_eq!(outcome, ResetOutcome::Revoked);
        assert_eq!(*calls.borrow(), vec!["revoke", "clear"]);
    }

    #[tokio::test]
    async fn a_reset_the_server_did_not_take_deletes_and_remembers_the_leaf() {
        for answer in [
            Ok(false),
            Err(AppError::Connection("unreachable".to_string())),
        ] {
            let calls = std::cell::RefCell::new(Vec::new());
            let remembered = std::cell::RefCell::new(None);
            let outcome = reset_with(
                Some("fp".to_string()),
                || async { answer },
                || calls.borrow_mut().push("clear"),
                |fp: &str| *remembered.borrow_mut() = Some(fp.to_string()),
            )
            .await;
            assert_eq!(outcome, ResetOutcome::LocalOnly);
            assert_eq!(*calls.borrow(), vec!["clear"]);
            assert_eq!(remembered.borrow().as_deref(), Some("fp"));
        }
    }

    #[tokio::test]
    async fn a_reset_without_an_identity_asks_no_server() {
        let calls = std::cell::RefCell::new(Vec::new());
        let outcome = reset_with(
            None,
            || async {
                calls.borrow_mut().push("revoke");
                Ok(true)
            },
            || calls.borrow_mut().push("clear"),
            |_| calls.borrow_mut().push("remember"),
        )
        .await;
        assert_eq!(outcome, ResetOutcome::NotEnrolled);
        assert_eq!(*calls.borrow(), vec!["clear"]);
    }

    #[test]
    fn the_reset_outcome_reaches_the_ui_in_camel_case() {
        assert_eq!(
            serde_json::to_value(ResetOutcome::LocalOnly).unwrap(),
            "localOnly"
        );
        assert_eq!(
            serde_json::to_value(ResetOutcome::NotEnrolled).unwrap(),
            "notEnrolled"
        );
        assert_eq!(
            serde_json::to_value(ResetOutcome::Revoked).unwrap(),
            "revoked"
        );
    }

    #[test]
    fn ca_fingerprint_is_the_first_chain_cert() {
        use rcgen::{CertificateParams, KeyPair, PKCS_ECDSA_P256_SHA256};

        // The provisioning tab hands out the INTERMEDIATE's fingerprint — the
        // cert the gateway actually presents — i.e. the FIRST cert of the
        // stored chain (intermediate + root), never the root's.
        let make = || {
            let key = KeyPair::generate_for(&PKCS_ECDSA_P256_SHA256).unwrap();
            CertificateParams::new(vec![])
                .unwrap()
                .self_signed(&key)
                .unwrap()
        };
        let inter = make();
        let root = make();
        let chain = format!("{}{}", inter.pem(), root.pem());

        let got = ca_fingerprint_of_chain(&chain).unwrap();
        assert_eq!(got, crate::tofu::fingerprint(inter.der()));
        assert_ne!(got, crate::tofu::fingerprint(root.der()));
        assert_eq!(ca_fingerprint_of_chain("kein pem"), None);
    }

    #[test]
    fn enroll_endpoint_swaps_port_and_path() {
        assert_eq!(
            enroll_endpoint("https://srm.example:443/api", 8444).unwrap(),
            "https://srm.example:8444/enroll"
        );
        assert_eq!(
            enroll_endpoint("https://srm.example", 8444).unwrap(),
            "https://srm.example:8444/enroll"
        );
    }

    #[test]
    fn decoupled_enroll_targets_the_default_enroll_plane() {
        // ADR 0003: the token-direct flow has no server grant, so it must derive
        // the enroll plane from the default port — the certless :8444 /enroll.
        assert_eq!(DEFAULT_ENROLL_PORT, 8444);
        assert_eq!(
            enroll_endpoint("https://srm.example", DEFAULT_ENROLL_PORT).unwrap(),
            "https://srm.example:8444/enroll"
        );
    }

    #[test]
    fn enroll_grant_deserializes_server_response() {
        let grant: EnrollGrant = serde_json::from_str(
            r#"{"token":"t","subjectId":"admin","scope":"access","enrollPort":8444}"#,
        )
        .unwrap();
        assert_eq!(grant.subject_id, "admin");
        assert_eq!(grant.scope, "access");
        assert_eq!(grant.enroll_port, 8444);
    }

    /// Answer one request on a fresh loopback port with `response`; the handle yields the
    /// request head.
    async fn answer_once(response: String) -> (String, tokio::task::JoinHandle<String>) {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://127.0.0.1:{}", listener.local_addr().unwrap().port());
        let request = tokio::spawn(async move {
            let (mut tcp, _) = listener.accept().await.unwrap();
            let mut head = Vec::new();
            let mut buf = [0u8; 1024];
            while !head.windows(4).any(|w| w == b"\r\n\r\n") {
                let n = tcp.read(&mut buf).await.unwrap();
                if n == 0 {
                    break;
                }
                head.extend_from_slice(&buf[..n]);
            }
            tcp.write_all(response.as_bytes()).await.unwrap();
            let _ = tcp.shutdown().await;
            String::from_utf8_lossy(&head).into_owned()
        });
        (url, request)
    }

    #[tokio::test]
    async fn the_browser_grant_is_minted_on_the_session_server_with_its_token() {
        let grant = r#"{"token":"t","subjectId":"ops-admin","scope":"access","enrollPort":8444}"#;
        let (server, request) = answer_once(format!(
            "HTTP/1.1 200 OK\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{grant}",
            grant.len()
        ))
        .await;
        let session = SessionState::default();
        session
            .set(
                server.clone(),
                "access-1".to_string(),
                "refresh-1".to_string(),
                "ops-admin".to_string(),
                true,
            )
            .await;

        let (minted, minted_for) = mint_token(&session).await.unwrap();

        let request = request.await.unwrap();
        assert!(
            request.starts_with("POST /api/enrollment/token?browser=true HTTP/1.1\r\n"),
            "{request}"
        );
        assert!(
            request
                .lines()
                .any(|line| line.eq_ignore_ascii_case("authorization: Bearer access-1")),
            "{request}"
        );
        assert_eq!(minted.subject_id, "ops-admin");
        // The certificate is enrolled where the grant was minted, with the certificate
        // choice of that sign-in.
        assert_eq!(minted_for.server_url, server);
        assert!(minted_for.allow_self_signed);
    }

    #[tokio::test]
    async fn minting_without_a_session_is_refused_with_the_known_error() {
        let result = mint_token(&SessionState::default()).await;

        let message = result.err().map(|e| e.to_string());
        assert_eq!(
            message.as_deref(),
            Some("Keine aktive Sitzung — Anfrage abgelehnt")
        );
    }

    #[test]
    fn needs_renewal_decides_by_lifetime_fraction() {
        use rcgen::{date_time_ymd, CertificateParams, KeyPair, PKCS_ECDSA_P256_SHA256};

        let make = |nb, na| -> String {
            let key = KeyPair::generate_for(&PKCS_ECDSA_P256_SHA256).unwrap();
            let mut p = CertificateParams::new(vec![]).unwrap();
            p.not_before = nb;
            p.not_after = na;
            p.self_signed(&key).unwrap().pem()
        };

        let nb = date_time_ymd(2026, 1, 1);
        let na = date_time_ymd(2026, 12, 31); // ~1 year
        let cert = make(nb, na);

        // ~9 % elapsed -> not due.
        assert!(!needs_renewal(&cert, 0.5, date_time_ymd(2026, 2, 1).unix_timestamp()).unwrap());
        // ~58 % elapsed -> due.
        assert!(needs_renewal(&cert, 0.5, date_time_ymd(2026, 8, 1).unix_timestamp()).unwrap());
        // Degenerate window (not_before == not_after) -> due.
        let degen = make(nb, nb);
        assert!(needs_renewal(&degen, 0.5, nb.unix_timestamp()).unwrap());
    }

    #[test]
    fn package_pkcs12_roundtrips_ec_key_with_password() {
        use rcgen::{CertificateParams, DnType, KeyPair, PKCS_ECDSA_P256_SHA256};

        // A self-signed EC leaf — enough to exercise the PKCS12 packaging.
        let key = KeyPair::generate_for(&PKCS_ECDSA_P256_SHA256).unwrap();
        let mut p = CertificateParams::new(vec![]).unwrap();
        p.distinguished_name.push(DnType::CommonName, "user-01");
        let cert = p.self_signed(&key).unwrap();

        let der = package_pkcs12(
            &key.serialize_pem(),
            &cert.pem(),
            "s3cret-p4ssw0rd",
            "AdminHelper",
        )
        .unwrap();

        // The .p12 must round-trip: MAC valid under the password (and only it),
        // and both the cert and the (EC) key extractable.
        let pfx = p12::PFX::parse(&der).unwrap();
        assert!(pfx.verify_mac("s3cret-p4ssw0rd"));
        assert!(!pfx.verify_mac("wrong"));
        assert_eq!(pfx.cert_x509_bags("s3cret-p4ssw0rd").unwrap().len(), 1);
        assert_eq!(pfx.key_bags("s3cret-p4ssw0rd").unwrap().len(), 1);
    }

    #[test]
    fn package_pkcs12_rejects_short_password() {
        use rcgen::{CertificateParams, KeyPair, PKCS_ECDSA_P256_SHA256};

        // 3.58: the weak PKCS12 KDF makes a short export password an offline
        // brute-force target, so it is refused before packaging. Use VALID PEM so only
        // the length check can error — otherwise the test would pass vacuously (old
        // code without the check would fail on the bogus PEM with the same error kind).
        let key = KeyPair::generate_for(&PKCS_ECDSA_P256_SHA256).unwrap();
        let cert = CertificateParams::new(vec![])
            .unwrap()
            .self_signed(&key)
            .unwrap();
        let err =
            package_pkcs12(&key.serialize_pem(), &cert.pem(), "short", "AdminHelper").unwrap_err();
        assert!(matches!(err, AppError::Validation(_)));
    }

    // Real-handshake proof of the enrolled mTLS client: an in-process TLS server
    // that REQUIRES a client cert (trusting a test CA) and presents a server cert
    // under the same CA. The client built by build_mtls_client must present its
    // cert, accept the server because it chains to the pinned CA — even when the
    // hostname does not match (connect by IP, server SAN is "localhost") — and
    // reject a server cert under a foreign CA.
    mod mtls {
        use super::*;

        use rcgen::{
            BasicConstraints, CertificateParams, DnType, ExtendedKeyUsagePurpose, IsCa, KeyPair,
            PKCS_ECDSA_P256_SHA256,
        };
        use rustls::server::WebPkiClientVerifier;
        use rustls::ServerConfig;
        use tokio::net::TcpListener;

        use crate::test_tls::{get, serve_once};

        struct Ca {
            cert: rcgen::Certificate,
            key: KeyPair,
        }

        fn make_ca() -> Ca {
            let key = KeyPair::generate_for(&PKCS_ECDSA_P256_SHA256).unwrap();
            let mut params = CertificateParams::new(vec![]).unwrap();
            params.is_ca = IsCa::Ca(BasicConstraints::Unconstrained);
            params
                .distinguished_name
                .push(DnType::CommonName, "Test CA");
            let cert = params.self_signed(&key).unwrap();
            Ca { cert, key }
        }

        /// (cert_pem, key_pem) for a leaf signed by `ca`.
        fn make_leaf(
            ca: &Ca,
            cn: &str,
            sans: Vec<String>,
            eku: ExtendedKeyUsagePurpose,
        ) -> (String, String) {
            let key = KeyPair::generate_for(&PKCS_ECDSA_P256_SHA256).unwrap();
            let mut params = CertificateParams::new(sans).unwrap();
            params.distinguished_name.push(DnType::CommonName, cn);
            params.extended_key_usages.push(eku);
            let cert = params.signed_by(&key, &ca.cert, &ca.key).unwrap();
            (cert.pem(), key.serialize_pem())
        }

        fn server_config(ca: &Ca, srv_cert_pem: &str, srv_key_pem: &str) -> Arc<ServerConfig> {
            let mut roots = RootCertStore::empty();
            roots.add(ca.cert.der().clone()).unwrap();
            let verifier = WebPkiClientVerifier::builder_with_provider(
                Arc::new(roots),
                crate::tofu::ring_provider(),
            )
            .build()
            .unwrap();
            let certs: Vec<CertificateDer<'static>> =
                CertificateDer::pem_slice_iter(srv_cert_pem.as_bytes())
                    .collect::<Result<_, _>>()
                    .unwrap();
            let key = PrivateKeyDer::from_pem_slice(srv_key_pem.as_bytes()).unwrap();
            let config = ServerConfig::builder_with_provider(crate::tofu::ring_provider())
                .with_safe_default_protocol_versions()
                .unwrap()
                .with_client_cert_verifier(verifier)
                .with_single_cert(certs, key)
                .unwrap();
            Arc::new(config)
        }

        #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
        async fn presents_cert_and_pins_ca_ignoring_hostname() {
            let ca = make_ca();
            let (srv_cert, srv_key) = make_leaf(
                &ca,
                "server",
                vec!["localhost".to_string()],
                ExtendedKeyUsagePurpose::ServerAuth,
            );
            let (cli_cert, cli_key) =
                make_leaf(&ca, "user-01", vec![], ExtendedKeyUsagePurpose::ClientAuth);

            let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let port = listener.local_addr().unwrap().port();
            tokio::spawn(serve_once(
                listener,
                server_config(&ca, &srv_cert, &srv_key),
            ));

            let client = build_mtls_client(&cli_key, &cli_cert, &ca.cert.pem()).unwrap();
            assert_eq!(get(&client, port).await, Ok(reqwest::StatusCode::OK));
        }

        #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
        async fn rejects_server_cert_under_a_foreign_ca() {
            let ca = make_ca();
            let foreign = make_ca();
            // Server cert is signed by the FOREIGN CA; the client pins OUR ca.
            let (srv_cert, srv_key) = make_leaf(
                &foreign,
                "server",
                vec!["localhost".to_string()],
                ExtendedKeyUsagePurpose::ServerAuth,
            );
            // The server still trusts OUR ca for client auth, so the client cert
            // is accepted server-side; the rejection must come from the client.
            let (cli_cert, cli_key) =
                make_leaf(&ca, "user-01", vec![], ExtendedKeyUsagePurpose::ClientAuth);

            let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let port = listener.local_addr().unwrap().port();
            tokio::spawn(serve_once(
                listener,
                server_config(&ca, &srv_cert, &srv_key),
            ));

            let client = build_mtls_client(&cli_key, &cli_cert, &ca.cert.pem()).unwrap();
            assert_eq!(get(&client, port).await, Err(()));
        }

        // A cert that does NOT chain to the pinned CA (server reinstall / MITM)
        // must surface our explicit, danger-aware message — not the raw rustls
        // error — carrying the stable ERR_CA_PIN_MISMATCH code the login screen
        // keys its recovery action off.
        #[test]
        fn unpinned_ca_yields_danger_message() {
            let ca = make_ca();
            let foreign = make_ca();
            let (leaf_pem, _) = make_leaf(
                &foreign,
                "server",
                vec!["localhost".to_string()],
                ExtendedKeyUsagePurpose::ServerAuth,
            );

            let mut roots = RootCertStore::empty();
            roots.add(ca.cert.der().clone()).unwrap();
            let inner = WebPkiServerVerifier::builder_with_provider(
                Arc::new(roots),
                crate::tofu::ring_provider(),
            )
            .build()
            .unwrap();
            let verifier = CaPinVerifier { inner };

            let leaf_der = CertificateDer::pem_slice_iter(leaf_pem.as_bytes())
                .next()
                .unwrap()
                .unwrap();
            let name = ServerName::try_from("localhost").unwrap();
            let result = verifier.verify_server_cert(&leaf_der, &[], &name, &[], UnixTime::now());

            match result {
                Err(TlsError::General(msg)) => {
                    assert!(
                        msg.contains("ERR_CA_PIN_MISMATCH"),
                        "Meldung muss den stabilen Fehlercode fuer das Login-Recovery tragen, war: {msg}"
                    );
                }
                other => panic!("erwartet General-Gefahrenmeldung, war: {other:?}"),
            }
        }
    }

    // The steps of the enroll flows that touch only the keyring, against the
    // in-memory keyring (R-0294), in the migrated workspace: its entries carry no
    // prefix, so the constants are its keys.

    /// (cert_pem, key_pem, fingerprint) of a self-signed leaf.
    fn leaf() -> (String, String, String) {
        use rcgen::{CertificateParams, KeyPair, PKCS_ECDSA_P256_SHA256};
        let key = KeyPair::generate_for(&PKCS_ECDSA_P256_SHA256).unwrap();
        let cert = CertificateParams::new(vec![])
            .unwrap()
            .self_signed(&key)
            .unwrap();
        (
            cert.pem(),
            key.serialize_pem(),
            crate::tofu::fingerprint(cert.der()),
        )
    }

    #[test]
    fn a_device_enrollment_names_the_held_leaf_before_a_remembered_one() {
        let _keyring = keyring_store::memory();
        let _standard = workspace::enter(standard());
        let (cert, _, fingerprint) = leaf();
        keyring_store::set(KEYRING_CERT, &cert).unwrap();
        keyring_store::set(KEYRING_REPLACES, "remembered").unwrap();
        assert_eq!(pending_replaces(EnrollmentKind::Device), Some(fingerprint));
    }

    #[test]
    fn a_device_enrollment_without_an_identity_names_the_remembered_leaf() {
        let _keyring = keyring_store::memory();
        let _standard = workspace::enter(standard());
        keyring_store::set(KEYRING_REPLACES, "remembered").unwrap();
        assert_eq!(
            pending_replaces(EnrollmentKind::Device).as_deref(),
            Some("remembered")
        );
    }

    #[test]
    fn a_browser_export_names_nothing_from_the_keyring() {
        let _keyring = keyring_store::memory();
        let _standard = workspace::enter(standard());
        let (cert, _, _) = leaf();
        keyring_store::set(KEYRING_CERT, &cert).unwrap();
        keyring_store::set(KEYRING_REPLACES, "remembered").unwrap();
        assert_eq!(pending_replaces(EnrollmentKind::Browser), None);
    }

    #[test]
    fn only_a_stored_enrollment_drops_the_remembered_leaf() {
        let _keyring = keyring_store::memory();
        let _standard = workspace::enter(standard());
        keyring_store::set(KEYRING_REPLACES, "remembered").unwrap();
        settle_replaces(&Err(AppError::Keyring("write failed".to_string())));
        assert_eq!(
            keyring_store::get(KEYRING_REPLACES).as_deref(),
            Some("remembered")
        );
        settle_replaces(&Ok(()));
        assert_eq!(keyring_store::get(KEYRING_REPLACES), None);
    }

    #[tokio::test]
    async fn a_reset_with_the_server_out_of_reach_remembers_the_leaf_and_deletes_the_identity() {
        let _keyring = keyring_store::memory();
        let _standard = workspace::enter(standard());
        let (cert, key, fingerprint) = leaf();
        keyring_store::set(KEYRING_KEY, &key).unwrap();
        keyring_store::set(KEYRING_CERT, &cert).unwrap();
        keyring_store::set(KEYRING_CA, &cert).unwrap();
        // The identity is sound; what fails is reaching the server.
        assert!(enrolled_client().is_ok());
        // Held, not freed: nobody listens on the port, and no parallel test's
        // server can be handed it.
        let (_reserved, port) = crate::test_tls::refused_port();

        let outcome = reset_identity(&format!("https://127.0.0.1:{port}")).await;

        assert_eq!(outcome, ResetOutcome::LocalOnly);
        assert_eq!(keyring_store::get(KEYRING_REPLACES), Some(fingerprint));
        for entry in [KEYRING_KEY, KEYRING_CERT, KEYRING_CA] {
            assert_eq!(keyring_store::get(entry), None, "{entry}");
        }
    }

    // The identity line of the settings (R-0240), against the in-memory keyring.

    /// A fullchain as the issuer returns it: a leaf for `cn` (no CN at all for
    /// `None`) that expires on 2027-01-13, then the intermediate that signed it.
    fn fullchain(cn: Option<&str>) -> String {
        use rcgen::{
            date_time_ymd, BasicConstraints, CertificateParams, DistinguishedName, DnType, IsCa,
            KeyPair, PKCS_ECDSA_P256_SHA256,
        };
        let ca_key = KeyPair::generate_for(&PKCS_ECDSA_P256_SHA256).unwrap();
        let mut ca = CertificateParams::new(vec![]).unwrap();
        ca.is_ca = IsCa::Ca(BasicConstraints::Unconstrained);
        ca.distinguished_name.push(DnType::CommonName, "Access CA");
        let ca = ca.self_signed(&ca_key).unwrap();

        let key = KeyPair::generate_for(&PKCS_ECDSA_P256_SHA256).unwrap();
        let mut params = CertificateParams::new(vec![]).unwrap();
        params.distinguished_name = DistinguishedName::new();
        if let Some(cn) = cn {
            params.distinguished_name.push(DnType::CommonName, cn);
        }
        params.not_after = date_time_ymd(2027, 1, 13);
        let leaf = params.signed_by(&key, &ca, &ca_key).unwrap();
        format!("{}{}", leaf.pem(), ca.pem())
    }

    /// Store `cert` next to a key, as an enrollment does.
    fn enrolled_with(cert: &str) {
        let (_, key, _) = leaf();
        keyring_store::set(KEYRING_KEY, &key).unwrap();
        keyring_store::set(KEYRING_CERT, cert).unwrap();
    }

    #[test]
    fn the_identity_is_the_name_and_expiry_of_the_leaf_not_the_intermediate() {
        let _keyring = keyring_store::memory();
        let _standard = workspace::enter(standard());
        enrolled_with(&fullchain(Some("admin")));

        let identity = device_identity().unwrap().expect("enrolled");

        assert_eq!(identity.name, "admin");
        assert_eq!(identity.not_after, "2027-01-13T00:00:00+00:00");
    }

    #[test]
    fn a_leaf_without_a_common_name_is_an_error() {
        let _keyring = keyring_store::memory();
        let _standard = workspace::enter(standard());
        enrolled_with(&fullchain(None));
        assert!(matches!(device_identity(), Err(AppError::Validation(_))));
    }

    #[test]
    fn a_stored_cert_that_does_not_parse_is_an_error() {
        let _keyring = keyring_store::memory();
        let _standard = workspace::enter(standard());
        enrolled_with("-----BEGIN CERTIFICATE-----\nZ2FyYmFnZQ==\n-----END CERTIFICATE-----\n");
        assert!(matches!(device_identity(), Err(AppError::Validation(_))));
        enrolled_with("kein pem");
        assert!(matches!(device_identity(), Err(AppError::Validation(_))));
    }

    #[test]
    fn without_a_key_there_is_no_identity() {
        let _keyring = keyring_store::memory();
        let _standard = workspace::enter(standard());
        keyring_store::set(KEYRING_CERT, &fullchain(Some("admin"))).unwrap();
        assert!(matches!(device_identity(), Ok(None)));
    }

    #[test]
    fn without_a_cert_there_is_no_identity() {
        let _keyring = keyring_store::memory();
        let _standard = workspace::enter(standard());
        let (_, key, _) = leaf();
        keyring_store::set(KEYRING_KEY, &key).unwrap();
        assert!(matches!(device_identity(), Ok(None)));
    }

    // ── R-0431: one identity per workspace ─────────────────────────────────

    /// A migrated workspace: its keys carry no prefix, as before workspaces.
    fn standard() -> Workspace {
        Workspace {
            id: WorkspaceId::parse("standard").unwrap(),
            name: "Standard".to_string(),
            legacy_keys: true,
        }
    }

    /// A workspace created after the migration: its keys carry its id.
    fn created(id: &str) -> Workspace {
        Workspace {
            id: WorkspaceId::parse(id).unwrap(),
            name: id.to_string(),
            legacy_keys: false,
        }
    }

    const ENTRIES: [&str; 4] = [KEYRING_KEY, KEYRING_CERT, KEYRING_CA, KEYRING_REPLACES];

    /// The identity as an enrollment before workspaces left it: entries without a prefix.
    fn enrolled_before_workspaces() -> (String, String) {
        let (cert, key, _) = leaf();
        keyring_store::set(KEYRING_KEY, &key).unwrap();
        keyring_store::set(KEYRING_CERT, &cert).unwrap();
        keyring_store::set(KEYRING_CA, &cert).unwrap();
        (key, cert)
    }

    fn issued(cert: &str) -> IssuedIdentity {
        IssuedIdentity {
            fullchain: cert.to_string(),
            chain: cert.to_string(),
        }
    }

    // R-0644: the identity is read once, and again after enrolling, renewing and resetting.

    #[test]
    fn the_identity_is_read_once_not_on_every_call() {
        let _keyring = keyring_store::memory();
        let _standard = workspace::enter(standard());
        let (key, cert) = enrolled_before_workspaces();
        assert!(is_enrolled());
        let identity = device_identity().unwrap();
        // Gone from the keyring behind enrollment's back: the calls keep what they read.
        for entry in [KEYRING_KEY, KEYRING_CERT, KEYRING_CA] {
            keyring_store::delete(entry).unwrap();
        }
        assert!(is_enrolled());
        assert_eq!(load_identity(), Some((key, cert.clone(), cert)));
        assert_eq!(
            device_identity().unwrap().map(|i| i.name),
            identity.map(|i| i.name)
        );
    }

    #[test]
    fn resetting_and_storing_read_the_identity_again() {
        let _keyring = keyring_store::memory();
        let _standard = workspace::enter(standard());
        enrolled_before_workspaces();
        assert!(is_enrolled());

        clear_identity();
        assert!(!is_enrolled());

        let (cert, key, _) = leaf();
        store_identity(&key, &issued(&cert)).unwrap();
        assert_eq!(load_identity(), Some((key, cert.clone(), cert)));

        purge_identity().unwrap();
        assert!(load_identity().is_none());
    }

    #[test]
    fn a_failed_read_is_not_held_and_the_next_call_reads_again() {
        let _keyring = keyring_store::memory();
        let _standard = workspace::enter(standard());
        enrolled_before_workspaces();
        let failing = |_: &str| Err(AppError::Keyring("locked".to_string()));
        assert!(held_identity_with(failing).is_none());

        let reads = std::cell::Cell::new(0);
        let counting = |key: &str| {
            reads.set(reads.get() + 1);
            keyring_store::try_get(key)
        };
        assert!(held_identity_with(counting).is_some());
        assert_eq!(reads.get(), 3, "the failed read was held");
        assert!(held_identity_with(counting).is_some());
        assert_eq!(reads.get(), 3, "the second call read the keyring again");
    }

    #[test]
    fn a_read_that_a_reload_overlaps_is_not_held() {
        let _keyring = keyring_store::memory();
        let _standard = workspace::enter(standard());
        enrolled_before_workspaces();
        let reads = std::cell::Cell::new(0);
        let reloading = |key: &str| {
            reads.set(reads.get() + 1);
            if reads.get() == 1 {
                reload_identity();
            }
            keyring_store::try_get(key)
        };
        assert!(held_identity_with(reloading).is_some());
        let counting = |key: &str| {
            reads.set(reads.get() + 1);
            keyring_store::try_get(key)
        };
        assert!(held_identity_with(counting).is_some());
        assert_eq!(reads.get(), 6, "the overlapped read was held");
    }

    #[test]
    fn workspace_keys_standard_reads_the_identity_from_before_workspaces() {
        let _keyring = keyring_store::memory();
        let (key, cert) = enrolled_before_workspaces();
        let _standard = workspace::enter(standard());

        assert!(is_enrolled());
        assert_eq!(load_identity(), Some((key, cert.clone(), cert)));
        assert!(pinned_ca_fingerprint().is_some());
    }

    #[test]
    fn workspace_keys_a_new_workspace_stores_its_identity_behind_its_prefix() {
        let _keyring = keyring_store::memory();
        let workspace = created("w-0a1b2c3d");
        let prefix = workspace.keyring_prefix();
        let _entered = workspace::enter(workspace);
        let (cert, key, _) = leaf();

        store_identity(&key, &issued(&cert)).unwrap();

        assert!(is_enrolled());
        for entry in [KEYRING_KEY, KEYRING_CERT, KEYRING_CA] {
            assert!(
                keyring_store::get(&format!("{prefix}{entry}")).is_some(),
                "{entry}"
            );
            assert_eq!(keyring_store::get(entry), None, "{entry} without a prefix");
        }
    }

    #[test]
    fn workspace_keys_two_new_workspaces_never_see_each_others_identity() {
        let _keyring = keyring_store::memory();
        let (cert, key, _) = leaf();
        {
            let a = created("a");
            let replaces = format!("{}{KEYRING_REPLACES}", a.keyring_prefix());
            let _a = workspace::enter(a);
            store_identity(&key, &issued(&cert)).unwrap();
            keyring_store::set(&replaces, "remembered-a").unwrap();
            assert!(is_enrolled());
        }

        let _b = workspace::enter(created("b"));
        assert!(!is_enrolled());
        assert_eq!(load_identity(), None);
        assert!(matches!(device_identity(), Ok(None)));
        assert_eq!(pinned_ca_fingerprint(), None);
        assert_eq!(pending_replaces(EnrollmentKind::Device), None);
        assert!(enrolled_client().is_err());
        // Nor does the migrated workspace see it.
        let _standard = workspace::enter(standard());
        assert!(!is_enrolled());
    }

    #[test]
    fn workspace_keys_a_new_workspace_never_reads_the_identity_from_before_workspaces() {
        let _keyring = keyring_store::memory();
        enrolled_before_workspaces();
        keyring_store::set(KEYRING_REPLACES, "remembered").unwrap();
        let _entered = workspace::enter(created("w-0a1b2c3d"));

        assert!(!is_enrolled());
        assert_eq!(load_identity(), None);
        assert!(matches!(device_identity(), Ok(None)));
        assert_eq!(pending_replaces(EnrollmentKind::Device), None);
    }

    #[test]
    fn login_binding_the_launcher_sees_whether_a_workspace_holds_an_identity() {
        let _keyring = keyring_store::memory();
        let a = created("w-0000000a").keyring_prefix();
        assert!(!holds_identity(&a).unwrap());

        // The leaf a reset remembers is no identity.
        keyring_store::set(&format!("{a}{KEYRING_REPLACES}"), "remembered").unwrap();
        assert!(!holds_identity(&a).unwrap());
        // Any entry of one is, even one a crash between the writes left alone.
        for entry in [KEYRING_KEY, KEYRING_CERT, KEYRING_CA] {
            let key = format!("{a}{entry}");
            keyring_store::set(&key, "pem").unwrap();
            assert!(holds_identity(&a).unwrap(), "{entry}");
            keyring_store::delete(&key).unwrap();
        }

        // Behind its own prefix only: the identity from before workspaces is the migrated ones'.
        enrolled_before_workspaces();
        assert!(!holds_identity(&a).unwrap());
        assert!(!holds_identity(&created("w-0000000b").keyring_prefix()).unwrap());
        assert!(holds_identity(&standard().keyring_prefix()).unwrap());
    }

    #[tokio::test]
    async fn login_binding_a_reset_asks_no_server_over_plain_http() {
        let _keyring = keyring_store::memory();
        let workspace = created("w-0000000a");
        let prefix = workspace.keyring_prefix();
        let _entered = workspace::enter(workspace);
        let (cert, key, fingerprint) = leaf();
        store_identity(&key, &issued(&cert)).unwrap();
        // On loopback too: any program of this machine may listen there and say "revoked".
        let (url, request) =
            answer_once("HTTP/1.1 204 No Content\r\nconnection: close\r\n\r\n".to_string()).await;

        let outcome = reset_identity(&url).await;

        assert_eq!(outcome, ResetOutcome::LocalOnly);
        request.abort();
        assert!(
            request.await.is_err_and(|e| e.is_cancelled()),
            "the reset asked {url}"
        );
        // Gone here, and remembered for the next enrollment to name as replaced.
        for entry in [KEYRING_KEY, KEYRING_CERT, KEYRING_CA] {
            assert_eq!(keyring_store::get(&format!("{prefix}{entry}")), None);
        }
        assert_eq!(
            keyring_store::get(&format!("{prefix}{KEYRING_REPLACES}")),
            Some(fingerprint)
        );
    }

    #[tokio::test]
    async fn workspace_keys_a_reset_in_a_new_workspace_leaves_the_others_alone() {
        let _keyring = keyring_store::memory();
        let (key, cert) = enrolled_before_workspaces();
        let (_reserved, port) = crate::test_tls::refused_port();
        let workspace = created("a");
        let prefix = workspace.keyring_prefix();
        let _a = workspace::enter(workspace);
        store_identity(&key, &issued(&cert)).unwrap();

        let outcome = reset_identity(&format!("http://127.0.0.1:{port}")).await;

        assert_eq!(outcome, ResetOutcome::LocalOnly);
        for entry in [KEYRING_KEY, KEYRING_CERT, KEYRING_CA] {
            assert_eq!(keyring_store::get(&format!("{prefix}{entry}")), None);
        }
        assert!(keyring_store::get(&format!("{prefix}{KEYRING_REPLACES}")).is_some());
        // The identity from before workspaces belongs to the migrated workspace.
        assert_eq!(keyring_store::get(KEYRING_KEY), Some(key));
        assert_eq!(keyring_store::get(KEYRING_CERT), Some(cert));
        assert_eq!(keyring_store::get(KEYRING_REPLACES), None);
    }

    #[tokio::test]
    async fn workspace_keys_the_launcher_has_no_identity_and_stores_none() {
        let _keyring = keyring_store::memory();
        let (key, cert) = enrolled_before_workspaces();
        keyring_store::set(KEYRING_REPLACES, "remembered").unwrap();
        let before: Vec<_> = ENTRIES.map(keyring_store::get).into();

        assert!(!is_enrolled());
        assert_eq!(load_identity(), None);
        assert!(matches!(device_identity(), Ok(None)));
        assert_eq!(pinned_ca_fingerprint(), None);
        assert_eq!(pending_replaces(EnrollmentKind::Device), None);
        assert!(enrolled_client().is_err());
        assert!(store_identity(&key, &issued(&cert)).is_err());
        settle_replaces(&Ok(()));
        clear_identity();
        let (_reserved, port) = crate::test_tls::refused_port();
        let url = format!("http://127.0.0.1:{port}");
        assert_eq!(reset_identity(&url).await, ResetOutcome::NotEnrolled);
        // Refused before the token reaches a server: a one-time token stays unspent.
        let no_workspace = crate::workspace::current().unwrap_err().to_string();
        match enroll_with_token(&url, "one-time", false).await {
            Err(e) => assert_eq!(e.to_string(), no_workspace),
            Ok(()) => panic!("the launcher enrolled"),
        }

        // Nothing fell back to the entries without a prefix.
        assert_eq!(Vec::from(ENTRIES.map(keyring_store::get)), before);
    }

    #[test]
    fn the_identity_reaches_the_ui_in_camel_case() {
        let identity = DeviceIdentity {
            name: "admin".to_string(),
            not_after: "2027-01-13T00:00:00+00:00".to_string(),
        };
        assert_eq!(
            serde_json::to_value(identity).unwrap(),
            serde_json::json!({ "name": "admin", "notAfter": "2027-01-13T00:00:00+00:00" })
        );
    }
}
