// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! HTTP transport for the generic API proxy and the server-cert probe. This
//! logic used to live inline in the Tauri command layer (`commands.rs`), which
//! made `api_proxy`/`check_server_cert` the only commands carrying their own
//! HTTP/TLS handling instead of delegating one-liner-style like every other
//! command. Keeping it here puts the token-destination pin, method dispatch and
//! status/body mapping beside the rest of the network code.

use crate::error::AppError;
use crate::session::SessionState;

/// Map an HTTP method to a request builder, rejecting unknown verbs instead of
/// silently falling back to GET: a frontend typo ("post") or an unsupported verb
/// ("PATCH") would otherwise turn a mutation into a read that "vanishes" with no
/// error to diagnose.
fn build_request(
    client: &reqwest::Client,
    method: &str,
    url: &str,
) -> Result<reqwest::RequestBuilder, AppError> {
    match method {
        "GET" => Ok(client.get(url)),
        "POST" => Ok(client.post(url)),
        "PUT" => Ok(client.put(url)),
        "DELETE" => Ok(client.delete(url)),
        other => Err(AppError::Validation(format!(
            "Nicht unterstuetzte HTTP-Methode: {other}"
        ))),
    }
}

/// Forward a JSON API call to the signed-in server, through
/// [`crate::session::authed_send`]: the session's access token and certificate choice, at
/// most one renewal on a 401. Works around WebView TLS restrictions for self-signed certs
/// by going through the shared reqwest client factory.
pub async fn forward(
    session: &SessionState,
    method: &str,
    path: &str,
    body: Option<String>,
) -> Result<serde_json::Value, AppError> {
    let (response, _) = crate::session::authed_send(session, |server_url, allow_self_signed| {
        // Token-destination pin: `path` comes from the webview, and one that
        // rewrites the URL authority (leading `@`, `\`, `://`) would carry the
        // session JWT to a foreign host; TOFU would happily pin the attacker's
        // cert on first use for it. Refused here before anything is built;
        // `authed_send` pins the request as built as well.
        crate::validation::validate_proxy_path(server_url, path, server_url)?;
        let client = crate::http_client::build_client(server_url, allow_self_signed)?;
        let url = format!("{}{}", server_url.trim_end_matches('/'), path);
        let req = build_request(&client, method, &url)?;
        Ok(match &body {
            Some(b) => req
                .header("Content-Type", "application/json")
                .body(b.clone()),
            None => req,
        })
    })
    .await?;
    let status = response.status();

    if status == reqwest::StatusCode::NO_CONTENT {
        return Ok(serde_json::Value::Null);
    }

    if !status.is_success() {
        let text = response.text().await.unwrap_or_default();
        return Err(AppError::http(status.as_u16(), &text));
    }

    // An empty 2xx body (no JSON payload) stays Null; an actually malformed
    // body is a real error and must not be silently mapped to Null.
    let text = response.text().await?;
    if text.is_empty() {
        return Ok(serde_json::Value::Null);
    }
    let value: serde_json::Value = serde_json::from_str(&text)?;
    Ok(value)
}

/// Probe whether the server certificate validates against the public trust
/// store. Returns true on success; a connect/TLS failure (untrusted/self-signed
/// cert) returns false → the caller's self-signed path; a timeout or any other
/// error propagates so a network problem isn't mistaken for a bad cert (4.27).
pub async fn check_server_cert(server_url: &str) -> Result<bool, AppError> {
    // Never probe a cleartext network URL (https, or http only for loopback).
    crate::validation::validate_server_url_secure(server_url)?;
    let client = crate::http_client::with_timeouts(reqwest::Client::builder())
        .danger_accept_invalid_certs(false)
        .build()
        .map_err(AppError::from)?;

    let url = format!("{}/api/auth/me", server_url.trim_end_matches('/'));
    match client.get(&url).send().await {
        Ok(_) => Ok(true),
        // Only a genuine connect/TLS failure means the cert isn't publicly trusted → false,
        // which routes the UI to the self-signed/TOFU path. A timeout (even a connect timeout)
        // is a reachability problem, not a cert problem: reporting it as "invalid cert" would
        // push the user to lower TLS strictness in response to a slow/unreachable server or a
        // typo'd host (4.27).
        Err(e) if e.is_connect() && !e.is_timeout() => Ok(false),
        Err(e) => Err(AppError::from(e)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{Arc, Mutex};

    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    const RENEWED: &str = r#"{"access_token":"renewed","refresh_token":"refresh-2"}"#;

    fn reply(status: &str, body: &str) -> String {
        format!(
            "HTTP/1.1 {status}\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
            body.len()
        )
    }

    /// Read one request: the head and as many body bytes as its `content-length` names.
    async fn read_request(tcp: &mut tokio::net::TcpStream) -> String {
        let mut request = Vec::new();
        let mut buf = [0u8; 1024];
        loop {
            if let Some(end) = request.windows(4).position(|w| w == b"\r\n\r\n") {
                let head = String::from_utf8_lossy(&request[..end]).to_ascii_lowercase();
                let length = head
                    .lines()
                    .find_map(|line| line.strip_prefix("content-length:"))
                    .map_or(0, |value| value.trim().parse::<usize>().unwrap());
                if request.len() >= end + 4 + length {
                    break;
                }
            }
            let n = tcp.read(&mut buf).await.unwrap();
            if n == 0 {
                break;
            }
            request.extend_from_slice(&buf[..n]);
        }
        String::from_utf8_lossy(&request).into_owned()
    }

    /// Serve HTTP on a fresh loopback port, one request per connection: every request lands
    /// in the log, then `answer` returns the whole response to it.
    async fn serve(
        mut answer: impl FnMut(&str) -> String + Send + 'static,
    ) -> (String, Arc<Mutex<Vec<String>>>) {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://127.0.0.1:{}", listener.local_addr().unwrap().port());
        let log = Arc::new(Mutex::new(Vec::new()));
        let seen = Arc::clone(&log);
        tokio::spawn(async move {
            loop {
                let (mut tcp, _) = listener.accept().await.unwrap();
                let request = read_request(&mut tcp).await;
                seen.lock().unwrap().push(request.clone());
                tcp.write_all(answer(&request).as_bytes()).await.unwrap();
                let _ = tcp.shutdown().await;
            }
        });
        (url, log)
    }

    /// The request lines in the order the requests arrived.
    fn request_lines(log: &Mutex<Vec<String>>) -> Vec<String> {
        let log = log.lock().unwrap();
        log.iter()
            .map(|request| request.lines().next().unwrap_or_default().to_string())
            .collect()
    }

    /// The Authorization header of a request, if it has one.
    fn authorization(request: &str) -> Option<&str> {
        request.lines().find_map(|line| {
            let (name, value) = line.split_once(':')?;
            name.eq_ignore_ascii_case("authorization")
                .then_some(value.trim())
        })
    }

    /// `ops-admin` signed in on `server_url` with an access token the server no longer takes.
    async fn signed_in(server_url: &str) -> SessionState {
        let session = SessionState::default();
        session
            .set(
                server_url.to_string(),
                "expired".to_string(),
                "refresh".to_string(),
                "ops-admin".to_string(),
                false,
            )
            .await;
        session
    }

    /// Counts how often `session` announces that it ended.
    fn expiries(session: &SessionState) -> Arc<AtomicUsize> {
        let count = Arc::new(AtomicUsize::new(0));
        let heard = Arc::clone(&count);
        session.on_expiry(move || {
            heard.fetch_add(1, Ordering::Relaxed);
        });
        count
    }

    #[tokio::test]
    async fn a_401_renews_the_session_and_the_retry_answers() {
        let (server, log) = serve(|request| {
            if request.starts_with("POST /api/auth/refresh ") {
                reply("200 OK", RENEWED)
            } else if authorization(request) == Some("Bearer renewed") {
                reply("201 Created", r#"{"id":7}"#)
            } else {
                reply("401 Unauthorized", "")
            }
        })
        .await;
        let session = signed_in(&server).await;
        let expired = expiries(&session);

        let answer = forward(
            &session,
            "POST",
            "/api/servers",
            Some(r#"{"name":"web-01"}"#.to_string()),
        )
        .await
        .unwrap();

        assert_eq!(answer, serde_json::json!({"id": 7}));
        assert_eq!(
            request_lines(&log),
            [
                "POST /api/servers HTTP/1.1",
                "POST /api/auth/refresh HTTP/1.1",
                "POST /api/servers HTTP/1.1",
            ]
        );
        // The retry is the same request with the new token, body included.
        let requests = log.lock().unwrap().clone();
        for (request, token) in [
            (&requests[0], "Bearer expired"),
            (&requests[2], "Bearer renewed"),
        ] {
            assert_eq!(authorization(request), Some(token));
            assert!(
                request.ends_with(r#"{"name":"web-01"}"#),
                "the body is missing: {request}"
            );
        }
        assert_eq!(session.current().await.unwrap().access, "renewed");
        assert_eq!(expired.load(Ordering::Relaxed), 0);
    }

    /// The refusal of `forward` to a request the server answers with `status` and `body`.
    async fn refusal_of(status: &'static str, body: &'static str) -> serde_json::Value {
        let (server, _log) = serve(move |_| reply(status, body)).await;
        let session = signed_in(&server).await;
        let err = forward(&session, "POST", "/api/servers", None)
            .await
            .expect_err("a non-2xx answer must be an error");
        serde_json::to_value(err).unwrap()
    }

    #[tokio::test]
    async fn a_refusal_carries_status_code_and_detail() {
        assert_eq!(
            refusal_of("409 Conflict", r#"{"detail":"Template already assigned"}"#).await,
            serde_json::json!({
                "code": "ERR_HTTP",
                "message": "Template already assigned",
                "status": 409
            })
        );
        assert_eq!(
            refusal_of(
                "403 Forbidden",
                r#"{"detail":"ERR_CERT_REVOKED: This device certificate is no longer valid.","code":"ERR_CERT_REVOKED"}"#
            )
            .await,
            serde_json::json!({
                "code": "ERR_CERT_REVOKED",
                "message": "This device certificate is no longer valid.",
                "status": 403
            })
        );
        assert_eq!(
            refusal_of("502 Bad Gateway", "<html><body>Bad Gateway</body></html>").await,
            serde_json::json!({ "code": "ERR_HTTP", "message": "HTTP 502", "status": 502 })
        );
    }

    #[tokio::test]
    async fn a_refused_renewal_ends_the_session_and_announces_it() {
        let (server, log) = serve(|_| reply("401 Unauthorized", "")).await;
        let session = signed_in(&server).await;
        let expired = expiries(&session);

        let result = forward(&session, "GET", "/api/servers", None).await;

        assert!(
            matches!(result, Err(AppError::SessionExpired)),
            "{result:?}"
        );
        assert!(session.current().await.is_none());
        assert_eq!(expired.load(Ordering::Relaxed), 1);
        // No retry without a token.
        assert_eq!(
            request_lines(&log),
            [
                "GET /api/servers HTTP/1.1",
                "POST /api/auth/refresh HTTP/1.1"
            ]
        );
    }

    #[tokio::test]
    async fn a_path_that_moves_the_authority_is_refused_before_sending() {
        let (server, log) = serve(|_| reply("200 OK", "{}")).await;
        let (foreign, foreign_log) = serve(|_| reply("200 OK", "{}")).await;
        let session = signed_in(&server).await;
        let expired = expiries(&session);
        let foreign_host = foreign.trim_start_matches("http://");

        for path in [
            format!("@{foreign_host}/api/servers"),
            format!("/\\{foreign_host}/api/servers"),
            format!("/x://{foreign_host}/api/servers"),
            "api/servers".to_string(),
        ] {
            let result = forward(&session, "GET", &path, None).await;

            assert!(
                matches!(result, Err(AppError::Validation(_))),
                "{path}: {result:?}"
            );
        }
        assert_eq!(request_lines(&foreign_log), Vec::<String>::new());
        assert_eq!(request_lines(&log), Vec::<String>::new());
        assert_eq!(session.current().await.unwrap().access, "expired");
        assert_eq!(expired.load(Ordering::Relaxed), 0);
    }

    #[tokio::test]
    async fn without_a_session_the_proxy_refuses_with_the_known_error() {
        let session = SessionState::default();
        let expired = expiries(&session);

        let result = forward(&session, "GET", "/api/servers", None).await;

        let message = result.err().map(|e| e.to_string()).unwrap_or_default();
        assert_eq!(message, "Keine aktive Sitzung — Anfrage abgelehnt");
        // No session to end: a sign-out is no expiry.
        assert_eq!(expired.load(Ordering::Relaxed), 0);
    }

    #[test]
    fn build_request_rejects_unknown_methods() {
        let client = reqwest::Client::new();
        for m in ["GET", "POST", "PUT", "DELETE"] {
            assert!(
                build_request(&client, m, "https://x/y").is_ok(),
                "{m} should be ok"
            );
        }
        // A typo or unsupported verb is rejected, not silently sent as GET.
        for m in ["PATCH", "post", "HEAD", ""] {
            assert!(
                matches!(
                    build_request(&client, m, "https://x/y"),
                    Err(AppError::Validation(_))
                ),
                "{m:?} should be rejected"
            );
        }
    }
}
