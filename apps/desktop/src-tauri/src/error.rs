// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use serde::Serialize;

/// Whether a reqwest error chain bottoms out in rustls'
/// `InvalidCertificate(UnknownIssuer)` — the server cert chains to no trusted
/// root, i.e. the public-CA path met a self-signed / own-PKI server (the
/// standard install's gateway leaf). Only that path can produce this variant:
/// the TOFU and enrolled-CA verifiers return their own General messages (a
/// changed pin with a stable `ERR_*` code, an unusable keyring without one) and
/// never `UnknownIssuer`, so matching it is unambiguous.
fn is_unknown_issuer(err: &reqwest::Error) -> bool {
    find_rustls(std::error::Error::source(err), &|e| {
        matches!(
            e,
            rustls::Error::InvalidCertificate(rustls::CertificateError::UnknownIssuer)
        )
        .then_some(())
    })
    .is_some()
}

/// The codes the TOFU verifier (tofu.rs) and the enrolled-CA pin (enrollment.rs) put in
/// front of their `General` refusal when the server's certificate changed.
const PIN_MISMATCH_CODES: [&str; 2] = ["ERR_TOFU_PIN_MISMATCH", "ERR_CA_PIN_MISMATCH"];

/// The pin-mismatch code a TLS failure in the chain from `source` on carries as prefix.
fn pin_mismatch_code(source: Option<&(dyn std::error::Error + 'static)>) -> Option<&'static str> {
    find_rustls(source, &|e| match e {
        rustls::Error::General(msg) => PIN_MISMATCH_CODES.into_iter().find(|code| {
            msg.strip_prefix(code)
                .is_some_and(|rest| rest.starts_with(": "))
        }),
        _ => None,
    })
}

/// The first answer of `f` for a rustls error in the chain from `source` on.
fn find_rustls<T>(
    mut source: Option<&(dyn std::error::Error + 'static)>,
    f: &dyn Fn(&rustls::Error) -> Option<T>,
) -> Option<T> {
    fn at<T>(
        cause: &(dyn std::error::Error + 'static),
        f: &dyn Fn(&rustls::Error) -> Option<T>,
    ) -> Option<T> {
        if let Some(found) = cause.downcast_ref::<rustls::Error>().and_then(f) {
            return Some(found);
        }
        // io::Error::source() skips the wrapped error (it forwards to the
        // inner error's OWN source), so the rustls error inside the TLS
        // connect failure never shows up as a chain element — it is only
        // reachable through get_ref().
        cause
            .downcast_ref::<std::io::Error>()
            .and_then(|io| io.get_ref())
            .and_then(|inner| at(inner, f))
    }

    while let Some(cause) = source {
        if let Some(found) = at(cause, f) {
            return Some(found);
        }
        source = cause.source();
    }
    None
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
    /// The gateway refused a login without a device certificate under enforced mTLS
    /// (`auth::login_failure`).
    MtlsCertRequired,
    /// A non-2xx answer of the server: `code` only in the form the server promises,
    /// `message` the redacted text of its `detail` (`AppError::http`).
    Http {
        status: u16,
        code: Option<String>,
        message: String,
    },
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
            AppError::MtlsCertRequired => write!(
                f,
                "ERR_MTLS_CERT_REQUIRED: The server requires a device certificate (mTLS is \
                 enforced). Enroll this device with a one-time enrollment token from your \
                 administrator."
            ),
            AppError::Http {
                status, message, ..
            } if *message == http_fallback(*status) => write!(f, "{message}"),
            AppError::Http {
                status, message, ..
            } => write!(f, "HTTP {status}: {message}"),
        }
    }
}

fn http_fallback(status: u16) -> String {
    format!("HTTP {status}")
}

/// The form of a code the server promises (R-0664): `^ERR_[A-Z0-9_]{1,64}$`.
fn is_error_code(code: &str) -> bool {
    code.strip_prefix("ERR_").is_some_and(|rest| {
        (1..=64).contains(&rest.len())
            && rest
                .bytes()
                .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || b == b'_')
    })
}

/// The text of an error body's `detail`, read like `errorDetail` in the web client: a
/// string as is, a list of validation errors as its `msg` texts.
fn detail_text(body: &serde_json::Value) -> Option<String> {
    match body.get("detail")? {
        serde_json::Value::String(text) => Some(text.clone()),
        serde_json::Value::Array(items) => {
            let msgs: Vec<&str> = items
                .iter()
                .filter_map(|item| item.get("msg")?.as_str())
                .collect();
            (!msgs.is_empty()).then(|| msgs.join("; "))
        }
        _ => None,
    }
}

/// Codes only the client gives (a TLS failure, the gateway's no-certificate page): a
/// server that sends one must not open the trust dialog or offer the pin reset.
const CLIENT_CODES: [&str; 4] = [
    "ERR_TLS_UNKNOWN_ISSUER",
    "ERR_TOFU_PIN_MISMATCH",
    "ERR_CA_PIN_MISMATCH",
    "ERR_MTLS_CERT_REQUIRED",
];

/// The certificate codes a server before R-0664 writes only as prefix of `detail`
/// (`identity.py`). Goes once no supported server answers without `code`.
const PREFIX_ONLY_CODES: [&str; 3] = [
    "ERR_CERT_REVOKED",
    "ERR_CERT_USER_MISMATCH",
    "ERR_CERT_SERVER_MISMATCH",
];

impl AppError {
    /// The refusal of a non-2xx answer with the raw `body`: the server's text is shown,
    /// never the raw body (an HTML page, a JSON object), and it is redacted, since an
    /// endpoint can echo a token back.
    pub fn http(status: u16, body: &str) -> AppError {
        let json = serde_json::from_str::<serde_json::Value>(body).ok();
        let code = json
            .as_ref()
            .and_then(|value| value.get("code")?.as_str())
            .filter(|code| is_error_code(code) && !CLIENT_CODES.contains(code))
            .or_else(|| {
                let detail = json.as_ref()?.get("detail")?.as_str()?;
                PREFIX_ONLY_CODES.into_iter().find(|code| {
                    detail
                        .strip_prefix(code)
                        .is_some_and(|rest| rest.starts_with(": "))
                })
            })
            .map(str::to_string);
        let mut text = json.as_ref().and_then(detail_text).unwrap_or_default();
        // The server keeps the code as prefix of the detail for clients that read the
        // text; with the code at hand the message is the text alone.
        if let Some(rest) = code
            .as_deref()
            .and_then(|code| text.strip_prefix(code)?.strip_prefix(": "))
        {
            text = rest.to_string();
        }
        let message = if text.trim().is_empty() {
            http_fallback(status)
        } else {
            crate::diagnostics::redact_body(&text)
        };
        AppError::Http {
            status,
            code,
            message,
        }
    }

    /// The stable code of the error: the UI branches on it, never on the message.
    pub fn code(&self) -> &str {
        match self {
            AppError::Validation(_) => "ERR_VALIDATION",
            AppError::Io(_) => "ERR_IO",
            AppError::Network(err) if is_unknown_issuer(err) => "ERR_TLS_UNKNOWN_ISSUER",
            AppError::Network(err) => {
                pin_mismatch_code(std::error::Error::source(err)).unwrap_or("ERR_NETWORK")
            }
            AppError::Connection(_) => "ERR_CONNECTION",
            AppError::Keyring(_) => "ERR_KEYRING",
            AppError::Json(_) => "ERR_JSON",
            AppError::SessionExpired => "ERR_SESSION_EXPIRED",
            AppError::MtlsCertRequired => "ERR_MTLS_CERT_REQUIRED",
            AppError::Http { code, .. } => code.as_deref().unwrap_or("ERR_HTTP"),
        }
    }
}

#[derive(Serialize)]
struct Refusal<'a> {
    code: &'a str,
    message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    status: Option<u16>,
}

// Tauri rejects the command's promise with exactly this value; the UI branches on `code`
// only (IpcError in bridge/index.ts), the message is for the user.
impl Serialize for AppError {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let (message, status) = match self {
            AppError::Http {
                status, message, ..
            } => (message.clone(), Some(*status)),
            _ => (self.to_string(), None),
        };
        Refusal {
            code: self.code(),
            message,
            status,
        }
        .serialize(serializer)
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

        let err = AppError::from(err);
        assert_eq!(err.code(), "ERR_TLS_UNKNOWN_ISSUER");
        assert_eq!(
            serde_json::to_value(&err).unwrap()["code"],
            "ERR_TLS_UNKNOWN_ISSUER"
        );
        let msg = err.to_string();
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

        let err = AppError::from(err);
        assert_eq!(err.code(), "ERR_NETWORK");
        let msg = err.to_string();
        assert!(
            !msg.contains("ERR_TLS_UNKNOWN_ISSUER"),
            "False positive: {msg}"
        );
    }

    #[test]
    fn a_refusal_is_the_code_and_the_message() {
        let json = serde_json::from_str::<serde_json::Value>("{").unwrap_err();
        let cases = [
            (AppError::Validation("bad".into()), "ERR_VALIDATION"),
            (AppError::Io(std::io::Error::other("disk")), "ERR_IO"),
            (AppError::Connection("down".into()), "ERR_CONNECTION"),
            (AppError::Keyring("locked".into()), "ERR_KEYRING"),
            (AppError::Json(json), "ERR_JSON"),
            (AppError::SessionExpired, "ERR_SESSION_EXPIRED"),
            (AppError::MtlsCertRequired, "ERR_MTLS_CERT_REQUIRED"),
        ];
        for (err, code) in cases {
            assert_eq!(
                serde_json::to_value(&err).unwrap(),
                serde_json::json!({ "code": code, "message": err.to_string() }),
                "{err:?}"
            );
        }
    }

    /// Status, code and message of `AppError::http(status, body)`.
    fn http_of(status: u16, body: &str) -> (u16, String, String) {
        let err = AppError::http(status, body);
        let code = err.code().to_string();
        let AppError::Http {
            status, message, ..
        } = err
        else {
            panic!("not an Http error: {err:?}");
        };
        (status, code, message)
    }

    #[test]
    fn http_takes_the_text_from_detail() {
        assert_eq!(
            http_of(409, r#"{"detail":"Template already assigned"}"#),
            (409, "ERR_HTTP".into(), "Template already assigned".into())
        );
        let list = r#"{"detail":[{"loc":["body","a"],"msg":"first"},{"loc":["body","b"],"msg":"second"}]}"#;
        assert_eq!(http_of(422, list).2, "first; second");
        assert_eq!(
            http_of(422, r#"{"detail":[{"loc":["body"]}]}"#).2,
            "HTTP 422"
        );
        for body in ["", r#"{"detail":""}"#, r#"{"other":1}"#, "null"] {
            assert_eq!(http_of(500, body).2, "HTTP 500", "{body}");
        }
    }

    #[test]
    fn http_shows_no_html_page() {
        let (_, code, message) = http_of(502, "<html><body>Bad Gateway</body></html>");
        assert_eq!(message, "HTTP 502");
        assert_eq!(code, "ERR_HTTP");
    }

    #[test]
    fn http_takes_the_server_code_and_drops_its_prefix() {
        assert_eq!(
            http_of(
                403,
                r#"{"detail":"ERR_CERT_REVOKED: This device certificate is no longer valid.","code":"ERR_CERT_REVOKED"}"#
            ),
            (
                403,
                "ERR_CERT_REVOKED".into(),
                "This device certificate is no longer valid.".into()
            )
        );
    }

    #[test]
    fn http_takes_the_certificate_codes_of_an_older_server_from_the_text() {
        for code in [
            "ERR_CERT_REVOKED",
            "ERR_CERT_USER_MISMATCH",
            "ERR_CERT_SERVER_MISMATCH",
        ] {
            let body = serde_json::json!({ "detail": format!("{code}: the text") }).to_string();
            assert_eq!(http_of(403, &body), (403, code.into(), "the text".into()));
        }
        for detail in [
            "ERR_TOFU_PIN_MISMATCH: x",
            "x ERR_CERT_REVOKED: y",
            "ERR_CERT_REVOKED",
            "ERR_CERT_REVOKEDx: y",
        ] {
            let body = serde_json::json!({ "detail": detail }).to_string();
            assert_eq!(
                http_of(403, &body),
                (403, "ERR_HTTP".into(), detail.into()),
                "{detail}"
            );
        }
        let body = serde_json::json!({
            "detail": "ERR_CERT_REVOKED: the text",
            "code": "ERR_CERT_USER_MISMATCH"
        })
        .to_string();
        assert_eq!(http_of(403, &body).1, "ERR_CERT_USER_MISMATCH");
    }

    #[test]
    fn http_takes_no_code_only_the_client_gives() {
        for code in [
            "ERR_TLS_UNKNOWN_ISSUER",
            "ERR_TOFU_PIN_MISMATCH",
            "ERR_CA_PIN_MISMATCH",
            "ERR_MTLS_CERT_REQUIRED",
        ] {
            let body = serde_json::json!({ "detail": "x", "code": code }).to_string();
            assert_eq!(
                http_of(403, &body),
                (403, "ERR_HTTP".into(), "x".into()),
                "{code}"
            );
        }
    }

    #[test]
    fn http_takes_no_code_of_another_form() {
        let long = format!("ERR_{}", "A".repeat(65));
        for code in [
            serde_json::json!("err_x"),
            serde_json::json!(5),
            serde_json::json!(long),
        ] {
            let detail = format!("{}: text", code.as_str().unwrap_or("5"));
            let body = serde_json::json!({ "detail": detail, "code": code }).to_string();
            assert_eq!(http_of(403, &body), (403, "ERR_HTTP".into(), detail));
        }
        let longest = format!("ERR_{}", "A".repeat(64));
        let body = serde_json::json!({ "detail": "x", "code": longest }).to_string();
        assert_eq!(http_of(403, &body).1, longest);
    }

    #[test]
    fn http_redacts_a_token_in_the_text() {
        let jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhZG1pbiJ9.c2lnbmF0dXJlLXZhbHVl";
        let body = serde_json::json!({ "detail": format!("token {jwt}") }).to_string();
        let (_, _, message) = http_of(400, &body);
        assert!(message.contains("<redacted-jwt>"), "{message}");
        assert!(!message.contains(jwt), "{message}");
    }

    #[test]
    fn http_names_its_status_once() {
        assert_eq!(
            AppError::http(409, r#"{"detail":"taken"}"#).to_string(),
            "HTTP 409: taken"
        );
        assert_eq!(AppError::http(502, "<html></html>").to_string(), "HTTP 502");
    }

    #[test]
    fn only_an_http_refusal_carries_a_status() {
        assert_eq!(
            serde_json::to_value(AppError::http(409, r#"{"detail":"taken"}"#)).unwrap(),
            serde_json::json!({ "code": "ERR_HTTP", "message": "taken", "status": 409 })
        );
        let value = serde_json::to_value(AppError::Validation("bad".into())).unwrap();
        assert!(value.get("status").is_none(), "{value}");
    }

    fn pin_code_of(text: &str) -> Option<&'static str> {
        let io = std::io::Error::other(rustls::Error::General(text.to_string()));
        pin_mismatch_code(Some(&io))
    }

    #[test]
    fn the_pin_codes_are_found_behind_the_io_error() {
        assert_eq!(
            pin_code_of("ERR_CA_PIN_MISMATCH: x"),
            Some("ERR_CA_PIN_MISMATCH")
        );
        assert_eq!(
            pin_code_of("ERR_TOFU_PIN_MISMATCH: x"),
            Some("ERR_TOFU_PIN_MISMATCH")
        );
        // The keyring refusal of the TOFU verifier carries no code (tofu.rs).
        assert_eq!(
            pin_code_of(
                "AdminHelper TOFU: The certificate pin for h could not be read from or stored \
                 in the system keyring, so the connection was refused."
            ),
            None
        );
        assert_eq!(pin_code_of("x ERR_CA_PIN_MISMATCH: y"), None);
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
