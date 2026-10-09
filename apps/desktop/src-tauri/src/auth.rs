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

/// Authenticated GET with automatic token refresh on 401.
pub async fn authenticated_get(
    server_url: &str,
    token: &str,
    path: &str,
    allow_self_signed: bool,
) -> Result<reqwest::Response, AppError> {
    // Same token-destination pin as api_proxy: refuse to send the JWT if the
    // FINAL composed URL (a `path` with a leading `@`/`\`/`://` can rewrite the
    // authority) drifts off the logged-in server. server_url and token both
    // originate from frontend commands, so this is a real boundary.
    crate::validation::require_pinned_destination(
        server_url,
        path,
        stored_server_url().as_deref(),
    )?;
    let client = crate::http_client::build_client(server_url, allow_self_signed)?;
    let url = format!("{}{}", server_url.trim_end_matches('/'), path);

    let response = client
        .get(&url)
        .header("Authorization", format!("Bearer {token}"))
        .send()
        .await?;

    if response.status() == reqwest::StatusCode::UNAUTHORIZED {
        // Load the refresh token from the keyring and try to refresh
        if let Ok((_, _, refresh_token)) = load_session_from_keyring() {
            if let Ok(new_session) =
                try_refresh(server_url, &refresh_token, allow_self_signed).await
            {
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
}
