// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use serde::Serialize;

/// Whether a reqwest error chain bottoms out in rustls'
/// `InvalidCertificate(UnknownIssuer)` — the server cert chains to no trusted
/// root, i.e. the public-CA path met a self-signed / own-PKI server (the
/// standard install's gateway leaf). Only that path can produce this variant:
/// the TOFU and enrolled-CA verifiers map it to their own `ERR_*` General
/// messages before it ever reaches reqwest, so matching it is unambiguous.
fn is_unknown_issuer(err: &reqwest::Error) -> bool {
    fn matches(cause: &(dyn std::error::Error + 'static)) -> bool {
        if let Some(rustls::Error::InvalidCertificate(rustls::CertificateError::UnknownIssuer)) =
            cause.downcast_ref::<rustls::Error>()
        {
            return true;
        }
        // io::Error::source() skips the wrapped error (it forwards to the
        // inner error's OWN source), so the rustls error inside the TLS
        // connect failure never shows up as a chain element — it is only
        // reachable through get_ref().
        cause
            .downcast_ref::<std::io::Error>()
            .and_then(|io| io.get_ref())
            .is_some_and(|inner| matches(inner))
    }

    let mut source = std::error::Error::source(err);
    while let Some(cause) = source {
        if matches(cause) {
            return true;
        }
        source = cause.source();
    }
    false
}

#[derive(Debug)]
pub enum AppError {
    Validation(String),
    Io(std::io::Error),
    Network(reqwest::Error),
    Connection(String),
    Keyring(String),
    Json(serde_json::Error),
    /// The session could not be renewed and is gone (`session::authed_send`).
    SessionExpired,
}

impl std::fmt::Display for AppError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AppError::Validation(msg) => write!(f, "{msg}"),
            AppError::Io(err) => write!(f, "{err}"),
            AppError::Network(err) => {
                // A raw "invalid peer certificate: UnknownIssuer" is a dead end for
                // the user, and with the standard install (own PKI on the gateway)
                // it is the EXPECTED first-contact failure while "allow self-signed
                // certificates" is off. Replace it with a stable code the login
                // screen keys its trust dialog off (ERR_* pattern, Login.svelte)
                // plus prose naming the way out; the prose may change/localize,
                // the code must not.
                if is_unknown_issuer(err) {
                    return write!(
                        f,
                        "ERR_TLS_UNKNOWN_ISSUER: AdminHelper: Das Server-Zertifikat stammt \
                         nicht von einer öffentlich vertrauenswürdigen CA. Bei einer \
                         Standard-Installation (AdminHelper-eigene PKI) ist das zu erwarten — \
                         in den Einstellungen \"Selbstsignierte Zertifikate erlauben\" \
                         aktivieren (das Zertifikat wird beim ersten Kontakt gepinnt) und \
                         erneut versuchen."
                    );
                }
                // reqwest's top-level message is generic ("error sending request");
                // walk the source chain so the real cause — e.g. the TOFU
                // pin-mismatch message from the rustls verifier — reaches the user.
                write!(f, "{err}")?;
                let mut source = std::error::Error::source(err);
                while let Some(cause) = source {
                    write!(f, ": {cause}")?;
                    source = cause.source();
                }
                Ok(())
            }
            AppError::Connection(msg) => write!(f, "{msg}"),
            AppError::Keyring(msg) => write!(f, "{msg}"),
            AppError::Json(err) => write!(f, "{err}"),
            AppError::SessionExpired => write!(f, "Session expired, please sign in again"),
        }
    }
}

impl Serialize for AppError {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.to_string())
    }
}

impl From<std::io::Error> for AppError {
    fn from(err: std::io::Error) -> Self {
        AppError::Io(err)
    }
}

impl From<reqwest::Error> for AppError {
    /// The only way a reqwest error becomes an `AppError`: reqwest names the request URL in
    /// its message, path and query included, and that text reaches the UI and the log, while
    /// some URLs are user-entered (the sync URL). Only the URL goes; the cause chain stays.
    fn from(err: reqwest::Error) -> Self {
        AppError::Network(err.without_url())
    }
}

impl From<serde_json::Error> for AppError {
    fn from(err: serde_json::Error) -> Self {
        AppError::Json(err)
    }
}

impl From<url::ParseError> for AppError {
    fn from(err: url::ParseError) -> Self {
        AppError::Validation(err.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;

    use tokio::net::TcpListener;

    use crate::test_tls::serve_once;

    /// A server presenting a self-signed leaf — what the standard install's
    /// own-PKI gateway looks like to a client that only trusts public roots.
    fn own_pki_server_config() -> Arc<rustls::ServerConfig> {
        use rcgen::{CertificateParams, KeyPair, PKCS_ECDSA_P256_SHA256};
        use rustls::pki_types::{PrivateKeyDer, PrivatePkcs8KeyDer};

        let key = KeyPair::generate_for(&PKCS_ECDSA_P256_SHA256).unwrap();
        let cert = CertificateParams::new(vec!["localhost".to_string()])
            .unwrap()
            .self_signed(&key)
            .unwrap();
        let key = PrivateKeyDer::Pkcs8(PrivatePkcs8KeyDer::from(key.serialize_der()));
        let config = rustls::ServerConfig::builder_with_provider(crate::tofu::ring_provider())
            .with_safe_default_protocol_versions()
            .unwrap()
            .with_no_client_auth()
            .with_single_cert(vec![cert.der().clone()], key)
            .unwrap();
        Arc::new(config)
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn unknown_issuer_maps_to_stable_code_and_names_the_setting() {
        // Reproduces the fresh-install bootstrap failure 1:1: the default
        // (public-CA) reqwest client against a server whose cert chains to no
        // public root. The surfaced message must carry the stable code the
        // login screen keys its trust dialog off AND name the setting.
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        tokio::spawn(serve_once(listener, own_pki_server_config()));

        let client = crate::http_client::with_timeouts(reqwest::Client::builder())
            .build()
            .unwrap();
        let err = client
            .get(format!("https://127.0.0.1:{port}/"))
            .send()
            .await
            .expect_err("Handshake gegen selbstsigniertes Zertifikat muss scheitern");

        let msg = AppError::from(err).to_string();
        assert!(msg.contains("ERR_TLS_UNKNOWN_ISSUER"), "Code fehlt: {msg}");
        assert!(
            msg.contains("Selbstsignierte Zertifikate erlauben"),
            "Hinweis auf die Einstellung fehlt: {msg}"
        );
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn non_tls_network_errors_keep_the_raw_chain() {
        // Connection refused has no rustls error in its chain — it must NOT be
        // rewritten into the unknown-issuer hint.
        // Held, not freed: a freed port can go to a parallel test's TLS server.
        let (_reserved, port) = crate::test_tls::refused_port();

        let client = crate::http_client::with_timeouts(reqwest::Client::builder())
            .build()
            .unwrap();
        let err = client
            .get(format!("https://127.0.0.1:{port}/"))
            .send()
            .await
            .expect_err("Verbindung auf geschlossenen Port muss scheitern");

        let mut refused = false;
        let mut source = std::error::Error::source(&err);
        while let Some(cause) = source {
            refused |= cause
                .downcast_ref::<std::io::Error>()
                .is_some_and(|io| io.kind() == std::io::ErrorKind::ConnectionRefused);
            source = cause.source();
        }
        assert!(refused, "no ConnectionRefused in the chain: {err:?}");

        let msg = AppError::from(err).to_string();
        assert!(
            !msg.contains("ERR_TLS_UNKNOWN_ISSUER"),
            "False positive: {msg}"
        );
    }

    const URL_PASSWORD: &str = "pw-9d41c7";
    const URL_PATH: &str = "private-path-3b8e";
    const URL_MARKER: &str = "marker-5f2a06";

    /// A request URL with user info, a path and a query, as a user-entered sync URL can carry.
    fn url_with_secrets(scheme: &str, port: u16) -> String {
        format!("{scheme}://u:{URL_PASSWORD}@127.0.0.1:{port}/{URL_PATH}?k={URL_MARKER}")
    }

    /// Neither the message nor the debug form may name any part of the request URL.
    fn assert_names_no_url(err: &AppError) {
        for text in [err.to_string(), format!("{err:?}")] {
            for part in [URL_PASSWORD, URL_PATH, URL_MARKER] {
                assert!(!text.contains(part), "{part} in the error: {text}");
            }
        }
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn network_errors_name_no_url_but_keep_the_cause() {
        // Held, not freed: a freed port can go to a parallel test's TLS server.
        let (_reserved, port) = crate::test_tls::refused_port();

        let client = crate::http_client::with_timeouts(reqwest::Client::builder())
            .build()
            .unwrap();
        let err = client
            .get(url_with_secrets("https", port))
            .send()
            .await
            .expect_err("Verbindung auf geschlossenen Port muss scheitern");

        let err = AppError::from(err);
        assert_names_no_url(&err);

        let AppError::Network(inner) = &err else {
            panic!("not a network error: {err:?}");
        };
        let mut refused = None;
        let mut source = std::error::Error::source(inner);
        while let Some(cause) = source {
            if let Some(io) = cause.downcast_ref::<std::io::Error>() {
                if io.kind() == std::io::ErrorKind::ConnectionRefused {
                    refused = Some(io.to_string());
                }
            }
            source = cause.source();
        }
        let refused =
            refused.unwrap_or_else(|| panic!("no ConnectionRefused in the chain: {err:?}"));
        let msg = err.to_string();
        assert!(msg.contains(&refused), "cause missing: {msg}");
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn status_errors_name_no_url() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};

        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        tokio::spawn(async move {
            let (mut tcp, _) = listener.accept().await.unwrap();
            // Read the whole request head first: closing on unread bytes resets the
            // connection, and the client would see that instead of the 500.
            let mut request = Vec::new();
            let mut buf = [0u8; 1024];
            while !request.windows(4).any(|w| w == b"\r\n\r\n") {
                let n = tcp.read(&mut buf).await.unwrap();
                if n == 0 {
                    break;
                }
                request.extend_from_slice(&buf[..n]);
            }
            tcp.write_all(
                b"HTTP/1.1 500 Internal Server Error\r\ncontent-length: 0\r\nconnection: close\r\n\r\n",
            )
            .await
            .unwrap();
            let _ = tcp.shutdown().await;
        });

        let client = crate::http_client::with_timeouts(reqwest::Client::builder())
            .build()
            .unwrap();
        let response = client
            .get(url_with_secrets("http", port))
            .send()
            .await
            .unwrap();
        let err = response
            .error_for_status()
            .expect_err("eine 500-Antwort muss ein Fehler sein");

        let err = AppError::from(err);
        assert_names_no_url(&err);
        let msg = err.to_string();
        assert!(msg.contains("500"), "status missing: {msg}");
    }
}
