// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use serde::Deserialize;

use crate::error::AppError;
use crate::keyring_store;
use crate::models::AuthSession;

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
/// not (R-0222). Any other answer stays the status plus the redacted body.
fn login_failure(status: reqwest::StatusCode, body: &str) -> AppError {
    if status == reqwest::StatusCode::BAD_REQUEST && body.contains(NGINX_NO_CLIENT_CERT) {
        return AppError::Validation(
            "ERR_MTLS_CERT_REQUIRED: The server requires a device certificate (mTLS is \
             enforced). Enroll this device with a one-time enrollment token from your \
             administrator."
                .to_string(),
        );
    }
    AppError::Validation(format!(
        "Login fehlgeschlagen ({}): {}",
        status,
        crate::diagnostics::redact_body(body)
    ))
}

pub async fn login(
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

    let session = AuthSession {
        server_url: server_url.trim_end_matches('/').to_string(),
        token: login_resp.access_token,
        refresh_token: login_resp.refresh_token,
        username: me.username,
        is_admin: me.is_admin,
    };

    save_session_to_keyring(&session)?;

    // Opportunistic auto-renew of the enrolled mTLS cert (~50% lifetime).
    // Best-effort: a transient failure must not break a successful login. This
    // is the only renew trigger now that startup re-authenticates with a fresh
    // login instead of silently restoring the session from the keyring.
    // Best-effort, but log a failure: login is the ONLY renew trigger, so a renew that fails for
    // weeks (ca-issuer down, broken route) would otherwise be silent until the client cert expires
    // and locks the user out under enforced mTLS. The warning lands in the diagnostics report
    // (4.92).
    if let Err(e) = crate::enrollment::maybe_renew(&session.server_url).await {
        log::warn!("mTLS-Zertifikat-Renew fehlgeschlagen (best-effort, naechster Versuch beim naechsten Login): {e}");
    }

    Ok(session)
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

/// Exchanges the refresh token for new access and refresh tokens.
async fn try_refresh(
    server_url: &str,
    refresh_token: &str,
    allow_self_signed: bool,
) -> Result<AuthSession, AppError> {
    let url = format!("{}/api/auth/refresh", server_url.trim_end_matches('/'));
    let client = crate::http_client::build_client(server_url, allow_self_signed)?;
    let body = serde_json::json!({ "refresh_token": refresh_token });

    let response = client.post(&url).json(&body).send().await?;
    if !response.status().is_success() {
        return Err(AppError::Validation("Refresh fehlgeschlagen".to_string()));
    }

    let resp: RefreshResponse = response.json().await?;
    let me = fetch_me(server_url, &resp.access_token, allow_self_signed).await?;

    Ok(AuthSession {
        server_url: server_url.trim_end_matches('/').to_string(),
        token: resp.access_token,
        refresh_token: resp.refresh_token,
        username: me.username,
        is_admin: me.is_admin,
    })
}

/// Authenticated GET with automatic token refresh on 401. It reads the active session
/// from the keyring once and sends that session's access token; `_token`, the one the
/// caller holds from its login, is not sent: a token renewed after a 401 lives only in
/// the keyring, and with the login one every poll after its expiry would refresh and
/// rotate the refresh token again.
pub async fn authenticated_get(
    server_url: &str,
    _token: &str,
    path: &str,
    allow_self_signed: bool,
) -> Result<reqwest::Response, AppError> {
    // One read of the session for the whole call: the session can change (logout, a
    // login elsewhere) while this request waits for its answer, so the pin, the access
    // token sent and a renewal all belong to the session read here.
    let session = load_session_from_keyring();
    // Same token-destination pin as api_proxy: refuse to send the JWT if the
    // FINAL composed URL (a `path` with a leading `@`/`\`/`://` can rewrite the
    // authority) drifts off the logged-in server. server_url originates from
    // frontend commands, so this is a real boundary.
    crate::validation::require_pinned_destination(
        server_url,
        path,
        session.as_ref().ok().map(|(url, _, _)| url.as_str()),
    )?;
    // The pin has refused already without a session, so this `?` never fires; the
    // tokens are used only behind the pin.
    let (stored_url, token, refresh_token) = session?;
    let client = crate::http_client::build_client(server_url, allow_self_signed)?;
    let url = format!("{}{}", server_url.trim_end_matches('/'), path);

    let response = client
        .get(&url)
        .header("Authorization", format!("Bearer {token}"))
        .send()
        .await?;

    // Renew and store only for the session this request was sent with; if the keyring
    // holds another one by now, the caller gets the 401.
    if response.status() == reqwest::StatusCode::UNAUTHORIZED
        && holds_session(&stored_url, &refresh_token)
    {
        if let Ok(new_session) = try_refresh(server_url, &refresh_token, allow_self_signed).await {
            // Checked again: the session can also change while the renewal is under way.
            if holds_session(&stored_url, &refresh_token) {
                if let Err(e) = save_session_to_keyring(&new_session) {
                    // The server has already rotated the refresh token, so the new one lives
                    // only in this retry — the keyring still holds the old, now-invalidated
                    // token, and the next 401 will refresh with a dead token and silently log the
                    // user out. Can't recover here (the keyring is the only store), but log it so
                    // the pattern is visible in the diagnostics report (4.26).
                    log::warn!("Rotiertes Session-Token nicht im Keyring gespeichert: {e}");
                }
                let retry = client
                    .get(&url)
                    .header("Authorization", format!("Bearer {}", new_session.token))
                    .send()
                    .await?;
                return Ok(retry);
            }
        }
    }

    Ok(response)
}

pub async fn logout(allow_self_signed: bool) -> Result<(), AppError> {
    // Notify the server so the access and refresh tokens get blacklisted
    // server-side. Errors are ignored: clearing the local keyring must happen
    // in every case (offline, server down, …).
    if let Ok((server_url, token, refresh_token)) = load_session_from_keyring() {
        let _ = notify_server_logout(&server_url, &token, &refresh_token, allow_self_signed).await;
    }
    // Keep the enrolled mTLS cert: it is a DEVICE credential, not a session
    // artifact, and under enforced mTLS it is required to even reach the login
    // endpoint — clearing it here would lock the user out of logging back in.
    // Only the session tokens are dropped; resetting the device identity is a
    // separate, explicit action (`enrollment::clear_identity`).
    clear_keyring()
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

// ── Keyring helpers ──────────────────────────────────────────────────

/// The server URL persisted for the active session at login, if any. Used to
/// pin `api_proxy`'s token destination: the JWT must only ever be sent to the
/// server the user actually logged into, never to a URL a (compromised) frontend
/// passes instead.
pub fn stored_server_url() -> Option<String> {
    load_session_from_keyring().ok().map(|(url, _, _)| url)
}

/// Whether the keyring still holds the session with this server URL and refresh token.
fn holds_session(server_url: &str, refresh_token: &str) -> bool {
    load_session_from_keyring()
        .is_ok_and(|(url, _, refresh)| url == server_url && refresh == refresh_token)
}

fn save_session_to_keyring(session: &AuthSession) -> Result<(), AppError> {
    keyring_store::set(KEYRING_JWT_KEY, &session.token)?;
    keyring_store::set(KEYRING_REFRESH_KEY, &session.refresh_token)?;
    keyring_store::set(KEYRING_SERVER_URL_KEY, &session.server_url)?;
    Ok(())
}

fn load_session_from_keyring() -> Result<(String, String, String), AppError> {
    // JWT and server_url are required (a missing entry is "no session"); the
    // refresh token is optional and degrades to empty.
    let token = keyring_store::get(KEYRING_JWT_KEY)
        .ok_or_else(|| AppError::Keyring("Keine Session".to_string()))?;
    let refresh_token = keyring_store::get(KEYRING_REFRESH_KEY).unwrap_or_default();
    let server_url = keyring_store::get(KEYRING_SERVER_URL_KEY)
        .ok_or_else(|| AppError::Keyring("Keine Session".to_string()))?;
    Ok((server_url, token, refresh_token))
}

fn clear_keyring() -> Result<(), AppError> {
    for key in [KEYRING_JWT_KEY, KEYRING_REFRESH_KEY, KEYRING_SERVER_URL_KEY] {
        keyring_store::delete(key)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use reqwest::StatusCode;
    use std::sync::{Arc, Mutex};

    /// The body nginx sends for its error 496, as in ngx_http_special_response.c.
    const NGINX_496_PAGE: &str = "<html>\r\n<head><title>400 No required SSL certificate was sent</title></head>\r\n<body>\r\n<center><h1>400 Bad Request</h1></center>\r\n<center>No required SSL certificate was sent</center>\r\n<hr><center>nginx</center>\r\n</body>\r\n</html>\r\n";

    #[test]
    fn the_gateway_no_cert_page_becomes_the_stable_code() {
        let msg = login_failure(StatusCode::BAD_REQUEST, NGINX_496_PAGE).to_string();
        assert!(msg.starts_with("ERR_MTLS_CERT_REQUIRED: "), "{msg}");
        assert!(
            !msg.contains("<html>"),
            "the page leaks into the message: {msg}"
        );
    }

    #[test]
    fn other_failures_keep_the_status_and_the_body() {
        for (status, body) in [
            (StatusCode::BAD_REQUEST, "{\"detail\":\"bad request\"}"),
            (
                StatusCode::UNAUTHORIZED,
                "{\"detail\":\"Invalid credentials\"}",
            ),
            // The page text under another status is not the gateway's 496 answer.
            (StatusCode::FORBIDDEN, NGINX_496_PAGE),
            (StatusCode::INTERNAL_SERVER_ERROR, NGINX_496_PAGE),
        ] {
            let msg = login_failure(status, body).to_string();
            assert!(!msg.contains("ERR_MTLS_CERT_REQUIRED"), "{status}: {msg}");
            assert!(
                msg.starts_with(&format!("Login fehlgeschlagen ({status}): ")),
                "{status}: {msg}"
            );
        }
    }

    #[test]
    fn other_failures_still_redact_the_body() {
        let jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl";
        let msg = login_failure(StatusCode::UNAUTHORIZED, &format!("token {jwt}")).to_string();
        assert!(msg.contains("<redacted-jwt>"), "{msg}");
        assert!(!msg.contains(jwt), "{msg}");
    }

    const SERVER: &str = "https://adminhelper.example:8443";

    fn session(server_url: &str, token: &str) -> AuthSession {
        AuthSession {
            server_url: server_url.to_string(),
            token: token.to_string(),
            refresh_token: "refresh".to_string(),
            username: "ops-admin".to_string(),
            is_admin: true,
        }
    }

    /// The session a user signs in to while an older request still waits for its answer.
    fn next_session(server_url: &str) -> AuthSession {
        AuthSession {
            server_url: server_url.to_string(),
            token: "next".to_string(),
            refresh_token: "next-refresh".to_string(),
            username: "ops-admin".to_string(),
            is_admin: true,
        }
    }

    fn stored(session: &AuthSession) -> (String, String, String) {
        (
            session.server_url.clone(),
            session.token.clone(),
            session.refresh_token.clone(),
        )
    }

    const RENEWED: &str = r#"{"access_token":"renewed","refresh_token":"refresh-2"}"#;
    const ME: &str = r#"{"username":"ops-admin","is_admin":true}"#;

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
    /// in the log, then `answer` returns the whole response to it. The server runs on the
    /// test's thread, so `answer` sees and changes the test's in-memory keyring.
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

    #[tokio::test]
    async fn authenticated_get_sends_nothing_without_a_session() {
        let _keyring = keyring_store::memory();
        let (server, log) = serve(|_| reply("200 OK", "")).await;

        // The caller still holds its login token; the keyring holds no session.
        assert!(
            authenticated_get(&server, "from-login", "/api/frp/tunnels", false)
                .await
                .is_err()
        );
        assert_eq!(request_lines(&log), Vec::<String>::new());
    }

    #[tokio::test]
    async fn a_401_renews_the_session_the_request_was_sent_with() {
        let _keyring = keyring_store::memory();
        let (server, log) = serve(|request| {
            if request.starts_with("POST /api/auth/refresh ") {
                reply("200 OK", RENEWED)
            } else if request.starts_with("GET /api/auth/me ") {
                reply("200 OK", ME)
            } else if request
                .to_ascii_lowercase()
                .contains("\r\nauthorization: bearer renewed\r\n")
            {
                reply("200 OK", "")
            } else {
                reply("401 Unauthorized", "")
            }
        })
        .await;
        save_session_to_keyring(&session(&server, "expired")).unwrap();

        let response = authenticated_get(&server, "from-login", "/api/frp/tunnels", false)
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            request_lines(&log),
            [
                "GET /api/frp/tunnels HTTP/1.1",
                "POST /api/auth/refresh HTTP/1.1",
                "GET /api/auth/me HTTP/1.1",
                "GET /api/frp/tunnels HTTP/1.1",
            ]
        );
        let refresh = log.lock().unwrap()[1].clone();
        assert!(
            refresh.ends_with(r#"{"refresh_token":"refresh"}"#),
            "{refresh}"
        );
        assert_eq!(
            load_session_from_keyring().unwrap(),
            (server, "renewed".to_string(), "refresh-2".to_string())
        );
    }

    #[tokio::test]
    async fn a_session_changed_while_the_request_waits_is_neither_renewed_nor_overwritten() {
        /// The session after the change, given the server the request went to.
        type Next = fn(&str) -> Option<AuthSession>;
        let cases: [(&str, Next); 3] = [
            ("signed out", |_| None),
            ("signed in to another server", |_| {
                Some(next_session(SERVER))
            }),
            ("signed in again on this server", |here| {
                Some(next_session(here))
            }),
        ];
        for (case, next) in cases {
            let _keyring = keyring_store::memory();
            let mut waiting = true;
            let (server, log) = serve(move |request| {
                if request.starts_with("POST /api/auth/refresh ") {
                    reply("200 OK", RENEWED)
                } else if request.starts_with("GET /api/auth/me ") {
                    reply("200 OK", ME)
                } else {
                    if waiting {
                        // The session changes while the first request waits for its answer.
                        waiting = false;
                        let (here, _, _) = load_session_from_keyring().unwrap();
                        match next(&here) {
                            Some(session) => save_session_to_keyring(&session).unwrap(),
                            None => clear_keyring().unwrap(),
                        }
                    }
                    reply("401 Unauthorized", "")
                }
            })
            .await;
            save_session_to_keyring(&session(&server, "expired")).unwrap();

            let response = authenticated_get(&server, "from-login", "/api/frp/tunnels", false)
                .await
                .unwrap();

            assert_eq!(response.status(), StatusCode::UNAUTHORIZED, "{case}");
            // No renewal and no retry: the request stays the only one this server sees.
            assert_eq!(
                request_lines(&log),
                ["GET /api/frp/tunnels HTTP/1.1"],
                "{case}"
            );
            assert_eq!(
                load_session_from_keyring().ok(),
                next(&server).as_ref().map(stored),
                "{case}"
            );
        }
    }

    #[tokio::test]
    async fn a_session_changed_while_the_renewal_runs_is_not_overwritten() {
        let _keyring = keyring_store::memory();
        let (server, log) = serve(|request| {
            if request.starts_with("POST /api/auth/refresh ") {
                reply("200 OK", RENEWED)
            } else if request.starts_with("GET /api/auth/me ") {
                // The refresh is answered; the session changes before the renewal is stored.
                save_session_to_keyring(&next_session(SERVER)).unwrap();
                reply("200 OK", ME)
            } else {
                reply("401 Unauthorized", "")
            }
        })
        .await;
        save_session_to_keyring(&session(&server, "expired")).unwrap();

        let response = authenticated_get(&server, "from-login", "/api/frp/tunnels", false)
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
        // No retry with the renewed token.
        assert_eq!(
            request_lines(&log),
            [
                "GET /api/frp/tunnels HTTP/1.1",
                "POST /api/auth/refresh HTTP/1.1",
                "GET /api/auth/me HTTP/1.1",
            ]
        );
        assert_eq!(
            load_session_from_keyring().unwrap(),
            stored(&next_session(SERVER))
        );
    }

    /// Answer one HTTP request on a fresh loopback port with 200; the task yields the request
    /// head as received.
    async fn serve_one() -> (String, tokio::task::JoinHandle<String>) {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://127.0.0.1:{}", listener.local_addr().unwrap().port());
        let task = tokio::spawn(async move {
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
            tcp.write_all(b"HTTP/1.1 200 OK\r\ncontent-length: 0\r\nconnection: close\r\n\r\n")
                .await
                .unwrap();
            let _ = tcp.shutdown().await;
            String::from_utf8_lossy(&head).into_owned()
        });
        (url, task)
    }

    #[tokio::test]
    async fn authenticated_get_sends_the_keyring_access_token() {
        let _keyring = keyring_store::memory();
        let (server, request) = serve_one().await;
        // The keyring holds a renewed token, the caller still the one from its login.
        save_session_to_keyring(&session(&server, "renewed")).unwrap();

        let response = authenticated_get(&server, "from-login", "/api/frp/tunnels", false)
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);
        let request = request.await.unwrap();
        assert!(
            request.starts_with("GET /api/frp/tunnels HTTP/1.1\r\n"),
            "{request}"
        );
        let authorization = request.lines().find_map(|line| {
            let (name, value) = line.split_once(':')?;
            name.eq_ignore_ascii_case("authorization")
                .then_some(value.trim())
        });
        assert_eq!(authorization, Some("Bearer renewed"));
    }

    #[tokio::test]
    async fn authenticated_get_sends_no_access_token_off_the_logged_in_server() {
        let _keyring = keyring_store::memory();
        let (foreign, _request) = serve_one().await;
        save_session_to_keyring(&session(SERVER, "renewed")).unwrap();

        // The foreign server would answer 200; the pin refuses before any request.
        assert!(
            authenticated_get(&foreign, "from-login", "/api/frp/tunnels", false)
                .await
                .is_err()
        );
    }
}
