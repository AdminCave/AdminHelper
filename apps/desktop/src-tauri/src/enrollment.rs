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
//! the cert on every later request.
//!
//! The mTLS `build_client` wiring + CA-pinning (presenting the stored cert) is
//! the next increment; this one obtains and stores the identity.

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

// ── Enrollment orchestration ──────────────────────────────────────────────

/// Run the full enrollment: mint an access-scoped token (JWT), generate an
/// on-device key + CSR, redeem it at the gateway enroll plane, and store the
/// issued identity. The TLS trust for both calls is the same the login used
/// (the TOFU-pinned gateway cert — the enroll plane presents the same leaf).
pub async fn enroll(server_url: &str, jwt: &str, allow_self_signed: bool) -> Result<(), AppError> {
    let grant = mint_token(server_url, jwt, allow_self_signed).await?;
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

async fn mint_token(
    server_url: &str,
    jwt: &str,
    allow_self_signed: bool,
) -> Result<EnrollGrant, AppError> {
    let client = crate::auth::build_client(server_url, allow_self_signed)?;
    let url = format!("{}/api/enrollment/token", server_url.trim_end_matches('/'));
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
    fn enroll_grant_deserializes_server_response() {
        let grant: EnrollGrant = serde_json::from_str(
            r#"{"token":"t","subjectId":"admin","scope":"access","enrollPort":8444}"#,
        )
        .unwrap();
        assert_eq!(grant.subject_id, "admin");
        assert_eq!(grant.scope, "access");
        assert_eq!(grant.enroll_port, 8444);
    }
}
