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
//! This module currently provides the pure, unit-tested core (keygen + CSR, the
//! wire types, the enroll-URL derivation). The HTTP orchestration + keyring/file
//! storage + the mTLS `build_client` wiring follow in the next increment — until
//! then these items are exercised only by the unit tests, so the staged-work
//! allow below keeps `clippy -D warnings` clean. The next increment removes it.
#![allow(dead_code)]

use serde::{Deserialize, Serialize};
use url::Url;

use crate::error::AppError;

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

/// What `/enroll` (and later `/renew`) returns.
///
/// * `cert`      the leaf alone
/// * `fullchain` leaf + access intermediate (what we present in mTLS)
/// * `chain`     access intermediate + root (what we pin and verify against)
#[derive(Debug, Deserialize)]
pub struct IssuedIdentity {
    pub cert: String,
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
