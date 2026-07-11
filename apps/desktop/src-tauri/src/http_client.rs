// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! Central TLS client factory. Previously this lived in [`crate::auth`], which
//! made that module both the session store AND the client factory — while
//! `enrollment`, `sync`, `notifications` and the api proxy all reached back into
//! `auth` just to build a client. Hosting the factory on its own leaves `auth`
//! with only session concerns and lets every caller depend on this leaf instead.

use crate::error::AppError;
use std::sync::{LazyLock, Mutex};
use std::time::Duration;

/// Process-wide client cache. Rebuilding the client per request means an empty connection pool —
/// every request pays a fresh TCP+TLS handshake and keep-alive is useless — plus up to 5 synchronous
/// keyring reads. The cached client (a cheap Arc clone) keeps a warm pool. The key covers the
/// trust-anchor inputs; an identity/pin change invalidates it explicitly via
/// [`invalidate_client_cache`], because `is_enrolled()` alone can't see a client-cert swap (5.1).
static CLIENT_CACHE: LazyLock<Mutex<Option<(String, reqwest::Client)>>> =
    LazyLock::new(|| Mutex::new(None));

/// Connect timeout: cap the TCP/TLS handshake so a DROP firewall / SYN blackhole can't
/// make login/enroll/proxy await forever (4.2).
const CONNECT_TIMEOUT: Duration = Duration::from_secs(10);
/// Read (not client-global) timeout: a request stalls out after this, but the SSE
/// notification stream survives — the server's 15 s heartbeat comment keeps it well under
/// this cap. A client-global `timeout()` would instead tear the stream down every cycle.
const READ_TIMEOUT: Duration = Duration::from_secs(45);

/// Apply the shared connect/read timeouts. Every client build path routes through this so
/// no reqwest client is ever built without a timeout (4.2).
pub fn with_timeouts(builder: reqwest::ClientBuilder) -> reqwest::ClientBuilder {
    builder
        .connect_timeout(CONNECT_TIMEOUT)
        .read_timeout(READ_TIMEOUT)
}

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

    // One is_enrolled() read, reused for both the cache key and the trust-anchor choice below.
    let enrolled = crate::enrollment::is_enrolled();
    let key = format!("{server_url}|{allow_self_signed}|{enrolled}");
    if let Some((cached_key, client)) = CLIENT_CACHE.lock().unwrap().as_ref() {
        if *cached_key == key {
            return Ok(client.clone());
        }
    }

    // Once this device is enrolled (A5), present the mTLS client cert and verify
    // the server against the pinned CA chain. This supersedes the self-signed /
    // public-CA paths below — the pinned CA is a stronger trust anchor than a
    // single leaf pin and survives gateway leaf rotation (D2).
    let client = if enrolled {
        crate::enrollment::enrolled_client()?
    } else if allow_self_signed {
        // NOT danger_accept_invalid_certs(true) — that would disable chain AND
        // hostname checks with no pinning, leaving every credential open to an
        // on-path MITM. Pin the server's certificate on first use instead.
        crate::tofu::pinning_client(server_url)?
    } else {
        // Public-CA path: reqwest's default full validation against webpki-roots.
        with_timeouts(reqwest::Client::builder())
            .build()
            .map_err(AppError::from)?
    };

    *CLIENT_CACHE.lock().unwrap() = Some((key, client.clone()));
    Ok(client)
}

/// Drop the cached client so the next [`build_client`] rebuilds it. Must be called on any change to
/// the trust material the client bakes in: the enrollment identity (store/clear) or a TOFU pin reset
/// — `is_enrolled()` in the cache key can't distinguish a cert swap on its own (5.1).
pub fn invalidate_client_cache() {
    *CLIENT_CACHE.lock().unwrap() = None;
}

#[cfg(test)]
mod tests {
    use super::with_timeouts;

    #[test]
    fn with_timeouts_builds_a_valid_client() {
        // 4.2: the shared connect/read timeouts must produce a buildable client — a guard
        // that the read_timeout/connect_timeout config stays valid across reqwest bumps.
        assert!(with_timeouts(reqwest::Client::builder()).build().is_ok());
    }
}
