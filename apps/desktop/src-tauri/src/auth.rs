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
        let text = crate::diagnostics::redact_body(&response.text().await.unwrap_or_default());
        return Err(AppError::Validation(format!(
            "Login fehlgeschlagen ({}): {}",
            status, text
        )));
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
    let _ = crate::enrollment::maybe_renew(&session.server_url).await;

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
    if let Some(stored) = stored_server_url() {
        crate::validation::validate_proxy_path(server_url, path, &stored)?;
    }
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
                let _ = save_session_to_keyring(&new_session);
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
