// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! Central TLS client factory. Previously this lived in [`crate::auth`], which
//! made that module both the session store AND the client factory — while
//! `enrollment`, `sync`, `notifications` and the api proxy all reached back into
//! `auth` just to build a client. Hosting the factory on its own leaves `auth`
//! with only session concerns and lets every caller depend on this leaf instead.

use crate::error::AppError;

/// Build the reqwest client for talking to `server_url`, choosing the strongest
/// available trust anchor.
pub fn build_client(
    server_url: &str,
    allow_self_signed: bool,
) -> Result<reqwest::Client, AppError> {
    // Choke point for every authenticated request (login, refresh, me, get,
    // logout) plus api_proxy and the tunnel/connection JWT paths: refuse to send
    // credentials to a non-TLS server. The scheme is never relaxed.
    crate::validation::validate_server_url_secure(server_url)?;
    // Once this device is enrolled (A5), present the mTLS client cert and verify
    // the server against the pinned CA chain. This supersedes the self-signed /
    // public-CA paths below — the pinned CA is a stronger trust anchor than a
    // single leaf pin and survives gateway leaf rotation (D2).
    if crate::enrollment::is_enrolled() {
        return crate::enrollment::enrolled_client();
    }
    if allow_self_signed {
        // NOT danger_accept_invalid_certs(true) — that would disable chain AND
        // hostname checks with no pinning, leaving every credential open to an
        // on-path MITM. Pin the server's certificate on first use instead.
        crate::tofu::pinning_client(server_url)
    } else {
        // Public-CA path: reqwest's default full validation against webpki-roots.
        reqwest::Client::builder().build().map_err(AppError::from)
    }
}
