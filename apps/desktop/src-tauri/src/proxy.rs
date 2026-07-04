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

/// Forward a JSON API call to `server_url` presenting the session `token`.
/// Works around WebView TLS restrictions for self-signed certs by going through
/// the shared reqwest client factory.
pub async fn forward(
    server_url: &str,
    token: &str,
    method: &str,
    path: &str,
    body: Option<String>,
    allow_self_signed: bool,
) -> Result<serde_json::Value, AppError> {
    // Token-destination pin: the session JWT must only be sent to the server the
    // user logged into. A (compromised) frontend that passes a foreign server_url
    // — or a `path` that rewrites the URL authority (leading `@`, `\`, `://`) —
    // alongside the real token would otherwise leak it; TOFU would happily pin the
    // attacker's cert on first use for that new host. Pin the FINAL composed URL's
    // origin, not just server_url.
    if let Some(stored) = crate::auth::stored_server_url() {
        crate::validation::validate_proxy_path(server_url, path, &stored)?;
    }
    let client = crate::http_client::build_client(server_url, allow_self_signed)?;
    let url = format!("{}{}", server_url.trim_end_matches('/'), path);

    let mut req = build_request(&client, method, &url)?;

    req = req.header("Authorization", format!("Bearer {token}"));

    if let Some(b) = body {
        req = req.header("Content-Type", "application/json").body(b);
    }

    let response = req.send().await?;
    let status = response.status();

    if status == reqwest::StatusCode::NO_CONTENT {
        return Ok(serde_json::Value::Null);
    }

    if !status.is_success() {
        let text = crate::diagnostics::redact_body(&response.text().await.unwrap_or_default());
        return Err(AppError::Validation(format!(
            "HTTP {}: {}",
            status.as_u16(),
            text
        )));
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
/// store. Returns true only on a successful request; any error returns false —
/// a self-signed/invalid cert, but also DNS/timeout/connection failures.
pub async fn check_server_cert(server_url: &str) -> Result<bool, AppError> {
    // Never probe a cleartext network URL (https, or http only for loopback).
    crate::validation::validate_server_url_secure(server_url)?;
    let client = reqwest::Client::builder()
        .danger_accept_invalid_certs(false)
        .build()
        .map_err(AppError::from)?;

    let url = format!("{}/api/auth/me", server_url.trim_end_matches('/'));
    match client.get(&url).send().await {
        Ok(_) => Ok(true),
        // Any error (TLS, DNS, timeout) counts as "not regularly reachable".
        Err(_) => Ok(false),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
