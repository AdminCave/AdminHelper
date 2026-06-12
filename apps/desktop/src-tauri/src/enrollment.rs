// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! Desktop mTLS enrollment (ADR 0001 §3.3 / A5).
//!
//! After login the desktop mints an access-scoped enrollment token at the server
//! (`POST /api/enrollment/token`, JWT-gated), generates an ECDSA P-256 keypair +
//! CSR **on-device** (the private key never leaves the host), and redeems the
//! token at the gateway's certless enroll plane. The ca-issuer signs an
//! access-scoped client leaf; the desktop pins the returned CA chain and presents
//! the cert on every later request (mTLS + CA-pinning in `build_client`), renews
//! it at ~50% lifetime, and can export a long-lived browser cert as a PKCS12.

use std::sync::Arc;

use rustls::client::danger::{HandshakeSignatureValid, ServerCertVerified, ServerCertVerifier};
use rustls::client::WebPkiServerVerifier;
use rustls::pki_types::{CertificateDer, PrivateKeyDer, ServerName, UnixTime};
use rustls::{
    CertificateError, DigitallySignedStruct, Error as TlsError, RootCertStore, SignatureScheme,
};
use serde::{Deserialize, Serialize};
use url::Url;

use crate::error::AppError;

/// Keyring service shared with `auth.rs` / `tofu.rs`.
const KEYRING_SERVICE: &str = "com.adminhelper.app";
// Three small entries (ECDSA fits the Windows 2560-byte limit, D10/V4) — the key
// is the only secret; cert/ca are public but kept in the same secure store so
// `build_client` can load the identity without an AppHandle.
const KEYRING_KEY: &str = "enroll|key"; // the EC private key (PKCS#8 PEM)
const KEYRING_CERT: &str = "enroll|cert"; // fullchain: leaf + access intermediate
const KEYRING_CA: &str = "enroll|ca"; // chain: access intermediate + root

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

/// Generate an ECDSA P-256 keypair and a CSR for `common_name` (D10: fits the
/// Windows keyring limit, modern, ideal for short-lived certs).
pub fn generate_key_and_csr(common_name: &str) -> Result<KeyAndCsr, AppError> {
    use rcgen::{CertificateParams, DistinguishedName, DnType, KeyPair, PKCS_ECDSA_P256_SHA256};

    let key_pair = KeyPair::generate_for(&PKCS_ECDSA_P256_SHA256)
        .map_err(|e| AppError::Validation(format!("Schlüssel erzeugen: {e}")))?;

    let mut params =
        CertificateParams::new(vec![]).map_err(|e| AppError::Validation(format!("CSR: {e}")))?;
    let mut dn = DistinguishedName::new();
    dn.push(DnType::CommonName, common_name);
    params.distinguished_name = dn;

    let csr = params
        .serialize_request(&key_pair)
        .map_err(|e| AppError::Validation(format!("CSR signieren: {e}")))?;
    let csr_pem = csr
        .pem()
        .map_err(|e| AppError::Validation(format!("CSR-PEM: {e}")))?;

    Ok(KeyAndCsr {
        key_pem: key_pair.serialize_pem(),
        csr_pem,
    })
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

#[cfg(unix)]
fn keyring_set(key: &str, value: &str) -> Result<(), AppError> {
    use keyring::Entry;
    Entry::new(KEYRING_SERVICE, key)
        .and_then(|entry| entry.set_password(value))
        .map_err(|e| AppError::Keyring(e.to_string()))
}

#[cfg(target_os = "windows")]
fn keyring_set(key: &str, value: &str) -> Result<(), AppError> {
    crate::password::windows_store_credential(key, "adminhelper", value)
}

#[cfg(not(any(unix, target_os = "windows")))]
fn keyring_set(_key: &str, _value: &str) -> Result<(), AppError> {
    Err(AppError::Keyring("Plattform nicht unterstützt".to_string()))
}

/// Persist the enrolled identity: key + fullchain + pinned CA chain. The private
/// key is written first, so a partial failure cannot leave a cert without a key.
fn store_identity(key_pem: &str, issued: &IssuedIdentity) -> Result<(), AppError> {
    keyring_set(KEYRING_KEY, key_pem)?;
    keyring_set(KEYRING_CERT, &issued.fullchain)?;
    keyring_set(KEYRING_CA, &issued.chain)?;
    Ok(())
}

#[cfg(unix)]
fn keyring_get(key: &str) -> Option<String> {
    use keyring::Entry;
    Entry::new(KEYRING_SERVICE, key).ok()?.get_password().ok()
}

#[cfg(target_os = "windows")]
fn keyring_get(key: &str) -> Option<String> {
    crate::password::windows_read_credential(key)
        .ok()
        .filter(|v| !v.is_empty())
}

#[cfg(not(any(unix, target_os = "windows")))]
fn keyring_get(_key: &str) -> Option<String> {
    None
}

#[cfg(unix)]
fn keyring_del(key: &str) {
    use keyring::Entry;
    if let Ok(entry) = Entry::new(KEYRING_SERVICE, key) {
        let _ = entry.delete_credential();
    }
}

#[cfg(target_os = "windows")]
fn keyring_del(key: &str) {
    let _ = crate::password::windows_delete_credential(key);
}

#[cfg(not(any(unix, target_os = "windows")))]
fn keyring_del(_key: &str) {}

/// The stored identity as `(key_pem, fullchain_pem, ca_pem)`, if enrolled.
fn load_identity() -> Option<(String, String, String)> {
    Some((
        keyring_get(KEYRING_KEY)?,
        keyring_get(KEYRING_CERT)?,
        keyring_get(KEYRING_CA)?,
    ))
}

/// Whether this device has an enrolled mTLS identity (key + cert present).
pub fn is_enrolled() -> bool {
    keyring_get(KEYRING_KEY).is_some() && keyring_get(KEYRING_CERT).is_some()
}

/// Forget the enrolled identity (on logout). The next login re-enrolls.
pub fn clear_identity() {
    keyring_del(KEYRING_KEY);
    keyring_del(KEYRING_CERT);
    keyring_del(KEYRING_CA);
}

// ── Enrollment orchestration ──────────────────────────────────────────────

/// Run the full enrollment: mint an access-scoped token (JWT), generate an
/// on-device key + CSR, redeem it at the gateway enroll plane, and store the
/// issued identity. The TLS trust for both calls is the same the login used
/// (the TOFU-pinned gateway cert — the enroll plane presents the same leaf).
pub async fn enroll(server_url: &str, jwt: &str, allow_self_signed: bool) -> Result<(), AppError> {
    let grant = mint_token(server_url, jwt, allow_self_signed, false).await?;
    // The desktop is a human client — refuse anything but an access-scoped grant.
    if grant.scope != "access" {
        return Err(AppError::Validation(format!(
            "Unerwarteter Enrollment-Scope '{}' (erwartet 'access')",
            grant.scope
        )));
    }
    let key_and_csr = generate_key_and_csr(&grant.subject_id)?;
    let endpoint = enroll_endpoint(server_url, grant.enroll_port)?;
    let issued = redeem(
        &endpoint,
        &grant.token,
        &key_and_csr.csr_pem,
        server_url,
        allow_self_signed,
    )
    .await?;
    store_identity(&key_and_csr.key_pem, &issued)
}

/// Decoupled enrollment (ADR 0003): enroll with a one-time token an admin minted
/// out-of-band (`POST /api/enrollment/token/for`) and handed over — **without** a
/// prior login. Skips `mint_token` (the token already exists), so it works under
/// enforced mTLS where a certless client cannot reach the login on `:443`. The
/// issuer dictates the cert CN from the token's subject (issuer.py:
/// `subject_cn=grant.subject_id`), so the CSR CN here is only a placeholder.
/// TLS trust is TOFU-pinned on first contact with the enroll plane (same gateway
/// leaf as `:443`), like the agent's first enrollment. Assumes the default enroll
/// port; a non-default port must be reachable under that name.
pub async fn enroll_with_token(
    server_url: &str,
    token: &str,
    allow_self_signed: bool,
) -> Result<(), AppError> {
    let key_and_csr = generate_key_and_csr("adminhelper-enrollment")?;
    let endpoint = enroll_endpoint(server_url, DEFAULT_ENROLL_PORT)?;
    let issued = redeem(
        &endpoint,
        token,
        &key_and_csr.csr_pem,
        server_url,
        allow_self_signed,
    )
    .await?;
    store_identity(&key_and_csr.key_pem, &issued)
}

async fn mint_token(
    server_url: &str,
    jwt: &str,
    allow_self_signed: bool,
    browser: bool,
) -> Result<EnrollGrant, AppError> {
    let client = crate::auth::build_client(server_url, allow_self_signed)?;
    let base = server_url.trim_end_matches('/');
    let url = if browser {
        format!("{base}/api/enrollment/token?browser=true")
    } else {
        format!("{base}/api/enrollment/token")
    };
    let resp = client
        .post(&url)
        .header("Authorization", format!("Bearer {jwt}"))
        .send()
        .await?;
    if !resp.status().is_success() {
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        return Err(AppError::Validation(format!(
            "Enrollment-Token anfordern fehlgeschlagen ({status}): {text}"
        )));
    }
    Ok(resp.json().await?)
}

async fn redeem(
    endpoint: &str,
    token: &str,
    csr_pem: &str,
    server_url: &str,
    allow_self_signed: bool,
) -> Result<IssuedIdentity, AppError> {
    // build_client pins by the login host; the gateway presents the same leaf on
    // the enroll plane, so that pin applies to this call too.
    let client = crate::auth::build_client(server_url, allow_self_signed)?;
    let resp = client
        .post(endpoint)
        .json(&EnrollRequest {
            token,
            csr: csr_pem,
        })
        .send()
        .await?;
    if !resp.status().is_success() {
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
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
    let leaf = rustls_pemfile::certs(&mut cert_pem.as_bytes())
        .next()
        .ok_or_else(|| AppError::Validation("Kein Zertifikat im PEM".to_string()))?
        .map_err(|e| AppError::Validation(format!("Zertifikat nicht lesbar: {e}")))?;
    let (_, cert) = x509_parser::parse_x509_certificate(&leaf)
        .map_err(|e| AppError::Validation(format!("Zertifikat parsen: {e}")))?;
    let not_before = cert.validity().not_before.timestamp();
    let not_after = cert.validity().not_after.timestamp();
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
    let key_and_csr = generate_key_and_csr("renew")?;
    let url = format!("{}/ca/renew", server_url.trim_end_matches('/'));
    let resp = client
        .post(&url)
        .json(&RenewRequest {
            csr: &key_and_csr.csr_pem,
        })
        .send()
        .await?;
    if !resp.status().is_success() {
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
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
    store_identity(&key_and_csr.key_pem, &issued)
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
    for cert in rustls_pemfile::certs(&mut ca_pem.as_bytes()) {
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
        rustls_pemfile::certs(&mut cert_pem.as_bytes())
            .collect::<Result<_, _>>()
            .map_err(|e| AppError::Validation(format!("Client-Zertifikat nicht lesbar: {e}")))?;
    let client_key: PrivateKeyDer<'static> = rustls_pemfile::private_key(&mut key_pem.as_bytes())
        .map_err(|e| AppError::Validation(format!("Client-Schlüssel nicht lesbar: {e}")))?
        .ok_or_else(|| AppError::Validation("Kein Client-Schlüssel im PEM".to_string()))?;

    let tls = rustls::ClientConfig::builder_with_provider(crate::tofu::ring_provider())
        .with_safe_default_protocol_versions()
        .map_err(|e| AppError::Connection(format!("TLS-Konfiguration: {e}")))?
        .dangerous()
        .with_custom_certificate_verifier(Arc::new(CaPinVerifier { inner: verifier }))
        .with_client_auth_cert(client_certs, client_key)
        .map_err(|e| AppError::Validation(format!("Client-Auth: {e}")))?;

    reqwest::Client::builder()
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
fn package_pkcs12(
    key_pem: &str,
    cert_pem: &str,
    password: &str,
    friendly_name: &str,
) -> Result<Vec<u8>, AppError> {
    let cert = rustls_pemfile::certs(&mut cert_pem.as_bytes())
        .next()
        .ok_or_else(|| AppError::Validation("Kein Zertifikat im PEM".to_string()))?
        .map_err(|e| AppError::Validation(format!("Zertifikat nicht lesbar: {e}")))?;
    let key = rustls_pemfile::private_key(&mut key_pem.as_bytes())
        .map_err(|e| AppError::Validation(format!("Schlüssel nicht lesbar: {e}")))?
        .ok_or_else(|| AppError::Validation("Kein Schlüssel im PEM".to_string()))?;
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

/// Enroll a long-lived browser cert (D5: the browser cannot auto-renew) and
/// return it as a PKCS12 blob for the user to import. Does NOT touch the
/// desktop's own keyring identity — this is a cert FOR the browser.
pub async fn export_browser_p12(
    server_url: &str,
    jwt: &str,
    password: &str,
    allow_self_signed: bool,
) -> Result<Vec<u8>, AppError> {
    let grant = mint_token(server_url, jwt, allow_self_signed, true).await?;
    if grant.scope != "access" {
        return Err(AppError::Validation(format!(
            "Unerwarteter Enrollment-Scope '{}' (erwartet 'access')",
            grant.scope
        )));
    }
    let key_and_csr = generate_key_and_csr(&grant.subject_id)?;
    let endpoint = enroll_endpoint(server_url, grant.enroll_port)?;
    let issued = redeem(
        &endpoint,
        &grant.token,
        &key_and_csr.csr_pem,
        server_url,
        allow_self_signed,
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

        let der =
            package_pkcs12(&key.serialize_pem(), &cert.pem(), "s3cret", "AdminHelper").unwrap();

        // The .p12 must round-trip: MAC valid under the password (and only it),
        // and both the cert and the (EC) key extractable.
        let pfx = p12::PFX::parse(&der).unwrap();
        assert!(pfx.verify_mac("s3cret"));
        assert!(!pfx.verify_mac("wrong"));
        assert_eq!(pfx.cert_x509_bags("s3cret").unwrap().len(), 1);
        assert_eq!(pfx.key_bags("s3cret").unwrap().len(), 1);
    }

    // Real-handshake proof of the enrolled mTLS client: an in-process TLS server
    // that REQUIRES a client cert (trusting a test CA) and presents a server cert
    // under the same CA. The client built by build_mtls_client must present its
    // cert, accept the server because it chains to the pinned CA — even when the
    // hostname does not match (connect by IP, server SAN is "localhost") — and
    // reject a server cert under a foreign CA.
    mod mtls {
        use super::*;
        use std::time::Duration;

        use rcgen::{
            BasicConstraints, CertificateParams, DnType, ExtendedKeyUsagePurpose, IsCa, KeyPair,
            PKCS_ECDSA_P256_SHA256,
        };
        use rustls::server::WebPkiClientVerifier;
        use rustls::ServerConfig;
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        use tokio::net::TcpListener;
        use tokio_rustls::TlsAcceptor;

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
                rustls_pemfile::certs(&mut srv_cert_pem.as_bytes())
                    .collect::<Result<_, _>>()
                    .unwrap();
            let key = rustls_pemfile::private_key(&mut srv_key_pem.as_bytes())
                .unwrap()
                .unwrap();
            let config = ServerConfig::builder_with_provider(crate::tofu::ring_provider())
                .with_safe_default_protocol_versions()
                .unwrap()
                .with_client_cert_verifier(verifier)
                .with_single_cert(certs, key)
                .unwrap();
            Arc::new(config)
        }

        async fn serve_once(listener: TcpListener, config: Arc<ServerConfig>) {
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

        async fn get(client: &reqwest::Client, port: u16) -> Result<reqwest::StatusCode, ()> {
            // Connect by IP, not the server cert's "localhost" SAN — proves the
            // CA-pin path does not enforce the hostname.
            let url = format!("https://127.0.0.1:{port}/");
            match tokio::time::timeout(Duration::from_secs(5), client.get(url).send()).await {
                Ok(Ok(resp)) => Ok(resp.status()),
                _ => Err(()),
            }
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
    }
}
