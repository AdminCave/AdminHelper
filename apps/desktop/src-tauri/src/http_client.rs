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
/// every request pays a fresh TCP+TLS handshake and keep-alive is useless. The device identity it
/// needs comes from what `enrollment` read once (R-0644), not from the keyring. The cached client (a cheap Arc clone) keeps a warm pool. The key covers the
/// trust-anchor inputs; an identity/pin change invalidates it explicitly via
/// [`invalidate_client_cache`], because `is_enrolled()` alone can't see a client-cert swap (5.1).
static CLIENT_CACHE: LazyLock<ClientCache> = LazyLock::new(ClientCache::default);

/// One cached client and the count of invalidations. A client is built outside the lock, from
/// trust material read before; an invalidation while it is built makes that material stale, so
/// the client then serves its own call only and is not kept.
#[derive(Default)]
struct ClientCache(Mutex<CacheSlot>);

#[derive(Default)]
struct CacheSlot {
    generation: u64,
    entry: Option<(String, reqwest::Client)>,
}

impl ClientCache {
    /// Read before the trust material a client is built from, for [`ClientCache::keep`].
    fn generation(&self) -> u64 {
        self.0.lock().unwrap().generation
    }

    fn cached(&self, key: &str) -> Option<reqwest::Client> {
        match self.0.lock().unwrap().entry.as_ref() {
            Some((cached_key, client)) if cached_key == key => Some(client.clone()),
            _ => None,
        }
    }

    /// Keep `client` under `key`, unless the cache was invalidated since `generation`.
    fn keep(&self, generation: u64, key: String, client: &reqwest::Client) {
        let mut slot = self.0.lock().unwrap();
        if slot.generation == generation {
            slot.entry = Some((key, client.clone()));
        }
    }

    fn invalidate(&self) {
        let mut slot = self.0.lock().unwrap();
        slot.generation += 1;
        slot.entry = None;
    }
}

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
    client_for(server_url, allow_self_signed, true)
}

/// Like [`build_client`], but never with the device identity: no mTLS client
/// certificate and no enrollment CA pin, the client of a device that isn't
/// enrolled (TOFU on the self-signed path, public CA otherwise). For the sync
/// source of a sync workspace: every sync loads without the identity, which is
/// for the server of a workspace only.
pub fn build_client_without_identity(
    server_url: &str,
    allow_self_signed: bool,
) -> Result<reqwest::Client, AppError> {
    client_for(server_url, allow_self_signed, false)
}

fn client_for(
    server_url: &str,
    allow_self_signed: bool,
    with_identity: bool,
) -> Result<reqwest::Client, AppError> {
    // Choke point for every authenticated request (login, refresh, me, get,
    // logout) plus api_proxy and the tunnel/connection JWT paths: refuse to send
    // credentials to a non-TLS server. The scheme is never relaxed.
    crate::validation::validate_server_url_secure(server_url)?;

    let generation = CLIENT_CACHE.generation();
    // One is_enrolled() check (the held identity, no keyring read), for both the cache key and the
    // trust-anchor choice below.
    // The key carries the choice, so a client built without the identity never answers a call
    // that wants it (and the other way round).
    let mtls = with_identity && crate::enrollment::is_enrolled();
    let key = format!("{server_url}|{allow_self_signed}|{mtls}");
    if let Some(client) = CLIENT_CACHE.cached(&key) {
        return Ok(client);
    }

    // Once this device is enrolled (A5) and the call wants its identity, present
    // the mTLS client cert and verify the server against the pinned CA chain.
    // This supersedes the self-signed /
    // public-CA paths below — the pinned CA is a stronger trust anchor than a
    // single leaf pin and survives gateway leaf rotation (D2).
    let client = if mtls {
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

    CLIENT_CACHE.keep(generation, key, &client);
    Ok(client)
}

/// Drop the cached client so the next [`build_client`] rebuilds it. Must be called on any change to
/// the trust material the client bakes in: the enrollment identity (store/clear) or a TOFU pin reset
/// — `is_enrolled()` in the cache key can't distinguish a cert swap on its own (5.1).
pub fn invalidate_client_cache() {
    CLIENT_CACHE.invalidate();
}

#[cfg(test)]
mod tests {
    use super::{build_client, build_client_without_identity, with_timeouts, ClientCache};
    use crate::keyring_store;

    #[test]
    fn with_timeouts_builds_a_valid_client() {
        // 4.2: the shared connect/read timeouts must produce a buildable client — a guard
        // that the read_timeout/connect_timeout config stays valid across reqwest bumps.
        assert!(with_timeouts(reqwest::Client::builder()).build().is_ok());
    }

    #[test]
    fn a_client_built_across_an_invalidation_is_not_kept() {
        let cache = ClientCache::default();
        let client = with_timeouts(reqwest::Client::builder()).build().unwrap();
        let key = "https://server.example|true|true";

        // Built from trust material read before the invalidation: it must not answer later calls.
        let generation = cache.generation();
        cache.invalidate();
        cache.keep(generation, key.to_string(), &client);
        assert!(cache.cached(key).is_none());

        // Built after it: kept.
        let generation = cache.generation();
        cache.keep(generation, key.to_string(), &client);
        assert!(cache.cached(key).is_some());
        assert!(cache.cached("https://other.example|true|true").is_none());

        cache.invalidate();
        assert!(cache.cached(key).is_none());
    }

    #[test]
    fn sync_identity_choice_is_part_of_the_client_cache_key() {
        // An enrolled identity that can't build an mTLS client: the identity path fails and the
        // path without it doesn't, so each result shows which client came back, cached or not.
        let _keyring = keyring_store::memory();
        let _standard = crate::workspace::enter(crate::workspace::Workspace {
            id: crate::workspace::WorkspaceId::parse("standard").unwrap(),
            name: "Standard".to_string(),
            legacy_keys: true,
        });
        for key in ["enroll|key", "enroll|cert", "enroll|ca"] {
            keyring_store::set(key, "not a pem").unwrap();
        }
        assert!(crate::enrollment::is_enrolled());
        // A URL no other test uses, so no other test's cached client can match these keys.
        let url = "https://cache-choice.example/connections.json";

        assert!(build_client(url, false).is_err());
        assert!(build_client_without_identity(url, false).is_ok());
        assert!(
            build_client(url, false).is_err(),
            "the cached client without identity must not answer a call that wants the identity"
        );
    }
}
