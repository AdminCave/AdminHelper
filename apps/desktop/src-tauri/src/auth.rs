// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use serde::Deserialize;

use crate::error::AppError;
use crate::models::AuthSession;

const KEYRING_SERVICE: &str = "com.adminhelper.app";
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

pub fn build_client(
    server_url: &str,
    allow_self_signed: bool,
) -> Result<reqwest::Client, AppError> {
    // Choke point for every authenticated request (login, refresh, me, get,
    // logout): refuse to send credentials to a non-TLS server. allow_self_signed
    // only relaxes cert *validation* on https, never the scheme itself.
    crate::validation::validate_server_url_secure(server_url)?;
    reqwest::Client::builder()
        .danger_accept_invalid_certs(allow_self_signed)
        .build()
        .map_err(AppError::from)
}

pub async fn login(
    server_url: &str,
    username: &str,
    password: &str,
    allow_self_signed: bool,
) -> Result<AuthSession, AppError> {
    let url = format!("{}/api/auth/login", server_url.trim_end_matches('/'));
    let client = build_client(server_url, allow_self_signed)?;
    let body = serde_json::json!({
        "username": username,
        "password": password,
    });

    let response = client.post(&url).json(&body).send().await?;

    if !response.status().is_success() {
        let status = response.status();
        let text = response.text().await.unwrap_or_default();
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

    Ok(session)
}

async fn fetch_me(
    server_url: &str,
    token: &str,
    allow_self_signed: bool,
) -> Result<MeResponse, AppError> {
    let url = format!("{}/api/auth/me", server_url.trim_end_matches('/'));
    let client = build_client(server_url, allow_self_signed)?;
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

pub async fn check_session(allow_self_signed: bool) -> Result<Option<AuthSession>, AppError> {
    let (server_url, token, refresh_token) = match load_session_from_keyring() {
        Ok(triple) => triple,
        Err(_) => return Ok(None),
    };

    // Try with the current access token
    match fetch_me(&server_url, &token, allow_self_signed).await {
        Ok(me) => Ok(Some(AuthSession {
            server_url,
            token,
            refresh_token,
            username: me.username,
            is_admin: me.is_admin,
        })),
        Err(_) => {
            // Access token expired — try to refresh
            match try_refresh(&server_url, &refresh_token, allow_self_signed).await {
                Ok(session) => {
                    save_session_to_keyring(&session)?;
                    Ok(Some(session))
                }
                Err(_) => {
                    let _ = clear_keyring();
                    Ok(None)
                }
            }
        }
    }
}

/// Exchanges the refresh token for new access and refresh tokens.
async fn try_refresh(
    server_url: &str,
    refresh_token: &str,
    allow_self_signed: bool,
) -> Result<AuthSession, AppError> {
    let url = format!("{}/api/auth/refresh", server_url.trim_end_matches('/'));
    let client = build_client(server_url, allow_self_signed)?;
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
    let client = build_client(server_url, allow_self_signed)?;
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
    clear_keyring()
}

async fn notify_server_logout(
    server_url: &str,
    token: &str,
    refresh_token: &str,
    allow_self_signed: bool,
) -> Result<(), AppError> {
    let url = format!("{}/api/auth/logout", server_url.trim_end_matches('/'));
    let client = build_client(server_url, allow_self_signed)?;
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

fn save_session_to_keyring(session: &AuthSession) -> Result<(), AppError> {
    #[cfg(unix)]
    {
        use keyring::Entry;
        let jwt_entry = Entry::new(KEYRING_SERVICE, KEYRING_JWT_KEY)
            .map_err(|e| AppError::Keyring(e.to_string()))?;
        jwt_entry
            .set_password(&session.token)
            .map_err(|e| AppError::Keyring(e.to_string()))?;
        let refresh_entry = Entry::new(KEYRING_SERVICE, KEYRING_REFRESH_KEY)
            .map_err(|e| AppError::Keyring(e.to_string()))?;
        refresh_entry
            .set_password(&session.refresh_token)
            .map_err(|e| AppError::Keyring(e.to_string()))?;
        let url_entry = Entry::new(KEYRING_SERVICE, KEYRING_SERVER_URL_KEY)
            .map_err(|e| AppError::Keyring(e.to_string()))?;
        url_entry
            .set_password(&session.server_url)
            .map_err(|e| AppError::Keyring(e.to_string()))?;
        Ok(())
    }
    #[cfg(target_os = "windows")]
    {
        use crate::password::{to_utf16_null, windows_store_credential};
        windows_store_credential(KEYRING_JWT_KEY, "adminhelper", &session.token)?;
        windows_store_credential(KEYRING_REFRESH_KEY, "adminhelper", &session.refresh_token)?;
        windows_store_credential(KEYRING_SERVER_URL_KEY, "adminhelper", &session.server_url)?;
        Ok(())
    }
    #[cfg(not(any(target_os = "windows", unix)))]
    {
        Ok(())
    }
}

fn load_session_from_keyring() -> Result<(String, String, String), AppError> {
    #[cfg(unix)]
    {
        use keyring::Entry;
        let jwt_entry = Entry::new(KEYRING_SERVICE, KEYRING_JWT_KEY)
            .map_err(|e| AppError::Keyring(e.to_string()))?;
        let token = jwt_entry
            .get_password()
            .map_err(|e| AppError::Keyring(e.to_string()))?;
        let refresh_entry = Entry::new(KEYRING_SERVICE, KEYRING_REFRESH_KEY)
            .map_err(|e| AppError::Keyring(e.to_string()))?;
        let refresh_token = refresh_entry.get_password().unwrap_or_default();
        let url_entry = Entry::new(KEYRING_SERVICE, KEYRING_SERVER_URL_KEY)
            .map_err(|e| AppError::Keyring(e.to_string()))?;
        let server_url = url_entry
            .get_password()
            .map_err(|e| AppError::Keyring(e.to_string()))?;
        Ok((server_url, token, refresh_token))
    }
    #[cfg(target_os = "windows")]
    {
        use crate::password::windows_read_credential;
        let token = windows_read_credential(KEYRING_JWT_KEY)?;
        let refresh_token = windows_read_credential(KEYRING_REFRESH_KEY).unwrap_or_default();
        let server_url = windows_read_credential(KEYRING_SERVER_URL_KEY)?;
        Ok((server_url, token, refresh_token))
    }
    #[cfg(not(any(target_os = "windows", unix)))]
    {
        Err(AppError::Keyring("Plattform nicht unterstützt".to_string()))
    }
}

fn clear_keyring() -> Result<(), AppError> {
    #[cfg(unix)]
    {
        use keyring::{Entry, Error as KeyringError};
        for key in [KEYRING_JWT_KEY, KEYRING_REFRESH_KEY, KEYRING_SERVER_URL_KEY] {
            if let Ok(entry) = Entry::new(KEYRING_SERVICE, key) {
                match entry.delete_credential() {
                    Ok(_) | Err(KeyringError::NoEntry) => {}
                    Err(e) => return Err(AppError::Keyring(e.to_string())),
                }
            }
        }
        Ok(())
    }
    #[cfg(target_os = "windows")]
    {
        use crate::password::windows_delete_credential;
        let _ = windows_delete_credential(KEYRING_JWT_KEY);
        let _ = windows_delete_credential(KEYRING_REFRESH_KEY);
        let _ = windows_delete_credential(KEYRING_SERVER_URL_KEY);
        Ok(())
    }
    #[cfg(not(any(target_os = "windows", unix)))]
    {
        Ok(())
    }
}
