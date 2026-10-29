// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use serde::Deserialize;

use crate::error::AppError;
use crate::keyring_store;
use crate::models::AuthSession;
use crate::session::{Renewed, SessionState, SignedIn};

/// Where earlier versions kept the session; it lives in the process now (R-0430), and the
/// start removes these entries ([`forget_keyring_session`]).
const KEYRING_JWT_KEY: &str = "auth|jwt";
const KEYRING_REFRESH_KEY: &str = "auth|refresh";
const KEYRING_SERVER_URL_KEY: &str = "auth|server_url";

#[derive(Deserialize)]
struct LoginResponse {
    access_token: String,
    refresh_token: String,
}

#[derive(Deserialize)]
struct RefreshResponse {
    access_token: String,
    refresh_token: String,
}

#[derive(Deserialize)]
struct MeResponse {
    username: String,
    #[serde(default)]
    is_admin: bool,
}

/// What the gateway answers a client without a device certificate under enforced
/// mTLS: nginx turns its own error 496 ("a client has not presented the required
/// certificate") into status 400 with this standard page (`ngx_http_error_496_page`
/// in nginx's `src/http/ngx_http_special_response.c`). ADR 0001 recorded this answer
/// against the running stack (A8 enforcement, 2026-06-12); not re-checked since.
const NGINX_NO_CLIENT_CERT: &str = "No required SSL certificate was sent";

/// The error a failed login reports. The gateway's no-certificate page becomes a
/// stable code the login screen keys its hint off (ERR_* pattern, Login.svelte,
/// like ERR_TLS_UNKNOWN_ISSUER in error.rs): the prose may change, the code must
/// not (R-0222). Any other answer is the server's refusal (`AppError::http`).
fn login_failure(status: reqwest::StatusCode, body: &str) -> AppError {
    if status == reqwest::StatusCode::BAD_REQUEST && body.contains(NGINX_NO_CLIENT_CERT) {
        return AppError::MtlsCertRequired;
    }
    AppError::http(status.as_u16(), body)
}

/// Signs in and keeps the session in `session`, together with `allow_self_signed`: every
/// request and renewal of the session builds its client with that choice, so a change of
/// the setting takes effect at the next sign-in. The answer names who signed in where; the
/// tokens stay in the session.
pub async fn login(
    session: &SessionState,
    server_url: &str,
    username: &str,
    password: &str,
    allow_self_signed: bool,
) -> Result<AuthSession, AppError> {
    let url = format!("{}/api/auth/login", server_url.trim_end_matches('/'));
    let client = crate::http_client::build_client(server_url, allow_self_signed)?;
    let body = serde_json::json!({
        "username": username,
        "password": password,
    });

    let response = client.post(&url).json(&body).send().await?;

    if !response.status().is_success() {
        let status = response.status();
        let text = response.text().await.unwrap_or_default();
        return Err(login_failure(status, &text));
    }

    let login_resp: LoginResponse = response.json().await?;

    let me = fetch_me(server_url, &login_resp.access_token, allow_self_signed).await?;

    let user = AuthSession {
        server_url: server_url.trim_end_matches('/').to_string(),
        username: me.username,
        is_admin: me.is_admin,
    };
    session
        .set(
            user.server_url.clone(),
            login_resp.access_token,
            login_resp.refresh_token,
            user.username.clone(),
            allow_self_signed,
        )
        .await;

    // Opportunistic auto-renew of the enrolled mTLS cert (~50% lifetime).
    // Best-effort: a transient failure must not break a successful login. This
    // is the only renew trigger now that startup re-authenticates with a fresh
    // login instead of silently restoring the session from the keyring.
    // Best-effort, but log a failure: login is the ONLY renew trigger, so a renew that fails for
    // weeks (ca-issuer down, broken route) would otherwise be silent until the client cert expires
    // and locks the user out under enforced mTLS. The warning lands in the diagnostics report
    // (4.92).
    if let Err(e) = crate::enrollment::maybe_renew(&user.server_url).await {
        log::warn!("mTLS-Zertifikat-Renew fehlgeschlagen (best-effort, naechster Versuch beim naechsten Login): {e}");
    }

    Ok(user)
}

async fn fetch_me(
    server_url: &str,
    token: &str,
    allow_self_signed: bool,
) -> Result<MeResponse, AppError> {
    let url = format!("{}/api/auth/me", server_url.trim_end_matches('/'));
    let client = crate::http_client::build_client(server_url, allow_self_signed)?;
    let response = client
        .get(&url)
        .header("Authorization", format!("Bearer {token}"))
        .send()
        .await?;

    if !response.status().is_success() {
        return Err(AppError::Validation("Session ungültig".to_string()));
    }

    Ok(response.json().await?)
}

/// Exchanges the refresh token for new access and refresh tokens. Only the pair: the user
/// stays the one who signed in, and a `/me` failing after the server has rotated would
/// throw the new pair away. The error lands in the log (`session::authed_send`), so it names
/// the status at most, never the answer.
pub async fn try_refresh(
    server_url: &str,
    refresh_token: &str,
    allow_self_signed: bool,
) -> Result<Renewed, AppError> {
    let url = format!("{}/api/auth/refresh", server_url.trim_end_matches('/'));
    let client = crate::http_client::build_client(server_url, allow_self_signed)?;
    let body = serde_json::json!({ "refresh_token": refresh_token });

    let response = client.post(&url).json(&body).send().await?;
    let status = response.status();
    if !status.is_success() {
        return Err(AppError::Validation(format!(
            "Refresh fehlgeschlagen ({status})"
        )));
    }

    // Not the decode error itself: serde quotes the value it could not take, and the answer
    // carries tokens.
    let resp: RefreshResponse = response
        .json()
        .await
        .map_err(|_| AppError::Validation("Refresh answer unreadable".to_string()))?;

    Ok(Renewed {
        access: resp.access_token,
        refresh: resp.refresh_token,
    })
}

/// Authenticated GET of `path` on the signed-in server, through
/// [`crate::session::authed_send`]: the session's access token and certificate choice, at
/// most one renewal on a 401. The answer comes with the user it was sent for; a caller that
/// takes it over checks [`SessionState::ensure_signed_in`] first.
pub async fn authenticated_get(
    session: &SessionState,
    path: &str,
) -> Result<(reqwest::Response, SignedIn), AppError> {
    crate::session::authed_send(session, |server_url, allow_self_signed| {
        let client = crate::http_client::build_client(server_url, allow_self_signed)?;
        Ok(client.get(format!("{}{}", server_url.trim_end_matches('/'), path)))
    })
    .await
}

/// Signs out. The session leaves the state first, so no request sends or renews its tokens
/// any more; then the server blacklists them, reached with the session's certificate
/// choice. That call is best effort (offline, server down, …): the session is gone either
/// way.
pub async fn logout(session: &SessionState) -> Result<(), AppError> {
    if let Some(ended) = session.take().await {
        let _ = notify_server_logout(
            &ended.server_url,
            &ended.access,
            &ended.refresh,
            ended.allow_self_signed,
        )
        .await;
    }
    // Keep the enrolled mTLS cert: it is a DEVICE credential, not a session
    // artifact, and under enforced mTLS it is required to even reach the login
    // endpoint — clearing it here would lock the user out of logging back in.
    // Only the session tokens are dropped; resetting the device identity is a
    // separate, explicit action (`enrollment::clear_identity`).
    Ok(())
}

async fn notify_server_logout(
    server_url: &str,
    token: &str,
    refresh_token: &str,
    allow_self_signed: bool,
) -> Result<(), AppError> {
    let url = format!("{}/api/auth/logout", server_url.trim_end_matches('/'));
    let client = crate::http_client::build_client(server_url, allow_self_signed)?;
    let body = serde_json::json!({ "refresh_token": refresh_token });
    let _ = client
        .post(&url)
        .header("Authorization", format!("Bearer {token}"))
        .json(&body)
        .send()
        .await?;
    Ok(())
}

/// Removes the session entries earlier versions kept in the keyring; nothing reads them
/// any more. Best effort, once per start.
pub fn forget_keyring_session() {
    for key in [KEYRING_JWT_KEY, KEYRING_REFRESH_KEY, KEYRING_SERVER_URL_KEY] {
        if let Err(e) = keyring_store::delete(key) {
            log::warn!("Old session entry {key} not removed from the keyring: {e}");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use reqwest::StatusCode;
    use std::sync::{Arc, Mutex};
    use std::time::Duration;

    /// The body nginx sends for its error 496, as in ngx_http_special_response.c.
    const NGINX_496_PAGE: &str = "<html>\r\n<head><title>400 No required SSL certificate was sent</title></head>\r\n<body>\r\n<center><h1>400 Bad Request</h1></center>\r\n<center>No required SSL certificate was sent</center>\r\n<hr><center>nginx</center>\r\n</body>\r\n</html>\r\n";

    #[test]
    fn the_gateway_no_cert_page_becomes_the_stable_code() {
        let err = login_failure(StatusCode::BAD_REQUEST, NGINX_496_PAGE);
        assert_eq!(err.code(), "ERR_MTLS_CERT_REQUIRED");
        let msg = err.to_string();
        assert!(msg.starts_with("ERR_MTLS_CERT_REQUIRED: "), "{msg}");
        assert!(
            !msg.contains("<html>"),
            "the page leaks into the message: {msg}"
        );
    }

    /// The refusal of `login_failure(status, body)` as it crosses the IPC.
    fn refusal_of(status: StatusCode, body: &str) -> serde_json::Value {
        serde_json::to_value(login_failure(status, body)).unwrap()
    }

    #[test]
    fn other_failures_carry_status_code_and_detail() {
        assert_eq!(
            refusal_of(StatusCode::BAD_REQUEST, r#"{"detail":"bad request"}"#),
            serde_json::json!({ "code": "ERR_HTTP", "message": "bad request", "status": 400 })
        );
        assert_eq!(
            refusal_of(
                StatusCode::UNAUTHORIZED,
                r#"{"detail":"Invalid credentials"}"#
            ),
            serde_json::json!({ "code": "ERR_HTTP", "message": "Invalid credentials", "status": 401 })
        );
        assert_eq!(
            refusal_of(
                StatusCode::FORBIDDEN,
                r#"{"detail":"ERR_CERT_USER_MISMATCH: The client certificate belongs to another user.","code":"ERR_CERT_USER_MISMATCH"}"#
            ),
            serde_json::json!({
                "code": "ERR_CERT_USER_MISMATCH",
                "message": "The client certificate belongs to another user.",
                "status": 403
            })
        );
        // The page text under another status is not the gateway's 496 answer.
        for (status, text) in [
            (StatusCode::FORBIDDEN, "HTTP 403"),
            (StatusCode::INTERNAL_SERVER_ERROR, "HTTP 500"),
        ] {
            assert_eq!(
                refusal_of(status, NGINX_496_PAGE),
                serde_json::json!({ "code": "ERR_HTTP", "message": text, "status": status.as_u16() })
            );
        }
    }

    #[test]
    fn other_failures_still_redact_the_body() {
        let jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl";
        let body = serde_json::json!({ "detail": format!("token {jwt}") }).to_string();
        let msg = login_failure(StatusCode::UNAUTHORIZED, &body).to_string();
        assert!(msg.contains("<redacted-jwt>"), "{msg}");
        assert!(!msg.contains(jwt), "{msg}");
        let msg = login_failure(StatusCode::UNAUTHORIZED, &format!("token {jwt}")).to_string();
        assert_eq!(msg, "HTTP 401");
    }

    const SERVER: &str = "https://adminhelper.example:8443";

    const RENEWED: &str = r#"{"access_token":"renewed","refresh_token":"refresh-2"}"#;
    const ME: &str = r#"{"username":"ops-admin","is_admin":true}"#;

    /// A session as a login leaves it: `ops-admin` on `server_url` with the access token
    /// `access` and the refresh token `refresh`.
    async fn signed_in(server_url: &str, access: &str) -> Arc<SessionState> {
        let session = Arc::new(SessionState::default());
        session
            .set(
                server_url.to_string(),
                access.to_string(),
                "refresh".to_string(),
                "ops-admin".to_string(),
                false,
            )
            .await;
        session
    }

    fn reply(status: &str, body: &str) -> String {
        format!(
            "HTTP/1.1 {status}\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
            body.len()
        )
    }

    /// Read one request: the head and as many body bytes as its `content-length` names.
    async fn read_request(tcp: &mut tokio::net::TcpStream) -> String {
        use tokio::io::AsyncReadExt;

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
        use tokio::io::AsyncWriteExt;

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

    /// Take the next connection on `listener` and read its request.
    async fn next_request(listener: &tokio::net::TcpListener) -> (tokio::net::TcpStream, String) {
        let (mut tcp, _) = listener.accept().await.unwrap();
        let request = read_request(&mut tcp).await;
        (tcp, request)
    }

    async fn respond(mut tcp: tokio::net::TcpStream, response: String) {
        use tokio::io::AsyncWriteExt;

        tcp.write_all(response.as_bytes()).await.unwrap();
        let _ = tcp.shutdown().await;
    }

    #[tokio::test]
    async fn login_fills_the_session() {
        let _keyring = keyring_store::memory();
        let (server, log) = serve(|request| {
            if request.starts_with("POST /api/auth/login ") {
                reply(
                    "200 OK",
                    r#"{"access_token":"access-1","refresh_token":"refresh-1"}"#,
                )
            } else if request.starts_with("GET /api/auth/me ") {
                reply("200 OK", ME)
            } else {
                reply("404 Not Found", "")
            }
        })
        .await;
        let session = SessionState::default();

        let user = login(&session, &format!("{server}/"), "ops-admin", "pw", false)
            .await
            .unwrap();

        assert_eq!(
            (
                user.server_url.as_str(),
                user.username.as_str(),
                user.is_admin
            ),
            (server.as_str(), "ops-admin", true)
        );
        let now = session.current().await.expect("a session");
        assert_eq!(
            (
                now.server_url.as_str(),
                now.access.as_str(),
                now.refresh.as_str(),
                now.username.as_str()
            ),
            (server.as_str(), "access-1", "refresh-1", "ops-admin")
        );
        assert_eq!(
            request_lines(&log),
            ["POST /api/auth/login HTTP/1.1", "GET /api/auth/me HTTP/1.1"]
        );
        // Nothing of it in the keyring.
        for key in [KEYRING_JWT_KEY, KEYRING_REFRESH_KEY, KEYRING_SERVER_URL_KEY] {
            assert_eq!(keyring_store::get(key), None, "{key}");
        }
    }

    #[tokio::test]
    async fn login_hands_the_webview_no_token() {
        let _keyring = keyring_store::memory();
        let (server, _log) = serve(|request| {
            if request.starts_with("POST /api/auth/login ") {
                reply(
                    "200 OK",
                    r#"{"access_token":"access-1","refresh_token":"refresh-1"}"#,
                )
            } else {
                reply("200 OK", ME)
            }
        })
        .await;
        let session = SessionState::default();

        let user = login(&session, &server, "ops-admin", "pw", false)
            .await
            .unwrap();

        // The answer as it crosses IPC: who signed in where, and nothing more.
        assert_eq!(
            serde_json::to_value(&user).unwrap(),
            serde_json::json!({
                "serverUrl": server,
                "username": "ops-admin",
                "isAdmin": true,
            })
        );
    }

    #[tokio::test]
    async fn login_keeps_the_certificate_choice_in_the_session() {
        let _keyring = keyring_store::memory();
        for choice in [false, true] {
            let (server, _log) = serve(|request| {
                if request.starts_with("POST /api/auth/login ") {
                    reply(
                        "200 OK",
                        r#"{"access_token":"access-1","refresh_token":"refresh-1"}"#,
                    )
                } else {
                    reply("200 OK", ME)
                }
            })
            .await;
            let session = SessionState::default();

            login(&session, &server, "ops-admin", "pw", choice)
                .await
                .unwrap();

            let now = session.current().await.expect("a session");
            assert_eq!(now.allow_self_signed, choice);
        }
    }

    #[tokio::test]
    async fn a_failed_login_keeps_no_session() {
        let (server, _log) = serve(|_| reply("401 Unauthorized", "")).await;
        let session = SessionState::default();

        assert!(login(&session, &server, "ops-admin", "wrong", false)
            .await
            .is_err());
        assert!(session.current().await.is_none());
    }

    #[tokio::test]
    async fn logout_signs_out_at_the_server_and_empties_the_session() {
        let (server, log) = serve(|_| reply("200 OK", "")).await;
        let session = signed_in(&server, "access").await;

        logout(&session).await.unwrap();

        assert!(session.current().await.is_none());
        let requests = log.lock().unwrap().clone();
        assert_eq!(request_lines(&log), ["POST /api/auth/logout HTTP/1.1"]);
        assert_eq!(authorization(&requests[0]), Some("Bearer access"));
        assert!(
            requests[0].ends_with(r#"{"refresh_token":"refresh"}"#),
            "{}",
            requests[0]
        );
    }

    #[tokio::test]
    async fn logout_empties_the_session_with_the_server_unreachable() {
        // Held, not freed: a freed port can go to a parallel test's server.
        let (_reserved, port) = crate::test_tls::refused_port();
        let session = signed_in(&format!("http://127.0.0.1:{port}"), "access").await;

        logout(&session).await.unwrap();

        assert!(session.current().await.is_none());
    }

    #[test]
    fn the_start_removes_the_old_keyring_session() {
        let _keyring = keyring_store::memory();
        for key in [KEYRING_JWT_KEY, KEYRING_REFRESH_KEY, KEYRING_SERVER_URL_KEY] {
            keyring_store::set(key, "from-an-earlier-version").unwrap();
        }
        // The device identity is no session entry.
        keyring_store::set("enroll|cert", "the-identity").unwrap();

        forget_keyring_session();

        for key in [KEYRING_JWT_KEY, KEYRING_REFRESH_KEY, KEYRING_SERVER_URL_KEY] {
            assert_eq!(keyring_store::get(key), None, "{key}");
        }
        assert_eq!(
            keyring_store::get("enroll|cert").as_deref(),
            Some("the-identity")
        );
    }

    #[tokio::test]
    async fn authenticated_get_sends_nothing_without_a_session() {
        let session = SessionState::default();

        let result = authenticated_get(&session, "/api/frp/tunnels").await;

        let message = result.err().map(|e| e.to_string()).unwrap_or_default();
        assert!(message.starts_with("Keine aktive Sitzung"), "{message}");
    }

    #[tokio::test]
    async fn authenticated_get_sends_the_session_access_token() {
        let (server, log) = serve(|_| reply("200 OK", "")).await;
        let session = signed_in(&server, "current").await;

        let (response, user) = authenticated_get(&session, "/api/frp/tunnels")
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(request_lines(&log), ["GET /api/frp/tunnels HTTP/1.1"]);
        let request = log.lock().unwrap()[0].clone();
        assert_eq!(authorization(&request), Some("Bearer current"));
        assert_eq!(
            (user.server_url, user.username.as_str()),
            (server, "ops-admin")
        );
    }

    #[tokio::test]
    async fn authenticated_get_sends_no_access_token_off_the_logged_in_server() {
        let (server, log) = serve(|_| reply("200 OK", "")).await;
        let (foreign, foreign_log) = serve(|_| reply("200 OK", "")).await;
        let session = signed_in(&server, "current").await;

        // Behind the session's URL, a path that starts with `@` names another authority.
        let path = format!("@{}/api/frp/tunnels", foreign.trim_start_matches("http://"));
        let result = authenticated_get(&session, &path).await;

        let message = result.err().map(|e| e.to_string()).unwrap_or_default();
        assert!(message.contains("not the signed-in server"), "{message}");
        assert_eq!(request_lines(&foreign_log), Vec::<String>::new());
        assert_eq!(request_lines(&log), Vec::<String>::new());
    }

    #[tokio::test]
    async fn a_401_renews_the_session_the_request_was_sent_with() {
        let (server, log) = serve(|request| {
            if request.starts_with("POST /api/auth/refresh ") {
                reply("200 OK", RENEWED)
            } else if authorization(request) == Some("Bearer renewed") {
                reply("200 OK", "")
            } else {
                reply("401 Unauthorized", "")
            }
        })
        .await;
        let session = signed_in(&server, "expired").await;

        let (response, user) = authenticated_get(&session, "/api/frp/tunnels")
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);
        // Only the token pair is renewed: no `/me` after the rotation, whose failure could
        // throw the new pair away.
        assert_eq!(
            request_lines(&log),
            [
                "GET /api/frp/tunnels HTTP/1.1",
                "POST /api/auth/refresh HTTP/1.1",
                "GET /api/frp/tunnels HTTP/1.1",
            ]
        );
        let refresh = log.lock().unwrap()[1].clone();
        assert!(
            refresh.ends_with(r#"{"refresh_token":"refresh"}"#),
            "{refresh}"
        );
        let now = session.current().await.unwrap();
        assert_eq!(
            (now.access.as_str(), now.refresh.as_str()),
            ("renewed", "refresh-2")
        );
        assert_eq!(
            (now.server_url.as_str(), now.username.as_str()),
            (server.as_str(), "ops-admin")
        );
        assert_eq!(
            (user.server_url.as_str(), user.username.as_str()),
            (server.as_str(), "ops-admin")
        );
    }

    #[tokio::test]
    async fn a_session_changed_while_the_renewal_runs_is_not_overwritten() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let server = format!("http://127.0.0.1:{}", listener.local_addr().unwrap().port());
        let session = signed_in(&server, "expired").await;

        let serve = async {
            let (tcp, first) = next_request(&listener).await;
            assert_eq!(authorization(&first), Some("Bearer expired"));
            respond(tcp, reply("401 Unauthorized", "")).await;

            let (tcp, refresh) = next_request(&listener).await;
            assert!(refresh.starts_with("POST /api/auth/refresh "), "{refresh}");
            // A sign-in elsewhere while the renewal is under way waits for it.
            let mut sign_in = std::pin::pin!(session.set(
                SERVER.to_string(),
                "next".to_string(),
                "next-refresh".to_string(),
                "ops-admin".to_string(),
                false,
            ));
            assert!(
                tokio::time::timeout(Duration::from_millis(100), sign_in.as_mut())
                    .await
                    .is_err(),
                "the sign-in did not wait for the renewal"
            );
            respond(tcp, reply("200 OK", RENEWED)).await;

            let (tcp, retry) = next_request(&listener).await;
            respond(tcp, reply("200 OK", "")).await;
            sign_in.await;
            retry
        };
        let ((response, user), retry) = tokio::time::timeout(Duration::from_secs(10), async {
            let (fetched, retry) =
                tokio::join!(authenticated_get(&session, "/api/frp/tunnels"), serve);
            (fetched.unwrap(), retry)
        })
        .await
        .expect("a request more than expected");

        // The request goes again with the renewed token, the session it belonged to then.
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(authorization(&retry), Some("Bearer renewed"));
        // The renewal did not overwrite the sign-in after it, and the answer it got belongs
        // to a session that is gone by now.
        let now = session.current().await.unwrap();
        assert_eq!(
            (now.server_url.as_str(), now.access.as_str()),
            (SERVER, "next")
        );
        assert!(session.ensure_signed_in(&user).await.is_err());
    }

    #[tokio::test]
    async fn a_renewal_error_carries_no_answer() {
        let jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl";
        // The error ends up in the log: neither a refusal nor an answer it cannot read may
        // bring the body along.
        for (status, body) in [
            ("401 Unauthorized", format!(r#"{{"detail":"{jwt}"}}"#)),
            ("200 OK", format!(r#""{jwt}""#)),
            ("200 OK", format!(r#"{{"access_token":"{jwt}"}}"#)),
        ] {
            let answer = body.clone();
            let (server, _log) = serve(move |_| reply(status, &answer)).await;

            let result = try_refresh(&server, "refresh", false).await;

            let message = result.err().map(|e| e.to_string());
            let message = message.unwrap_or_else(|| panic!("{status} {body}: no error"));
            assert!(!message.contains(jwt), "{status} {body}: {message}");
        }
    }
}
