// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! The server session of this process, in memory only: server URL, user and tokens.
//! Authenticated requests go through [`authed_send`], the one place that renews them.
#![cfg_attr(
    not(test),
    expect(
        dead_code,
        reason = "no callers yet, the auth paths move over next (R-0430)"
    )
)]

use std::future::Future;
use std::sync::atomic::{AtomicU64, Ordering};

use tokio::sync::Mutex;

use crate::error::AppError;

/// A signed-in session. `generation` changes with every token pair, from a login or a
/// renewal, and is never handed out twice.
#[derive(Clone)]
pub struct Session {
    pub server_url: String,
    pub access: String,
    pub refresh: String,
    pub username: String,
    pub is_admin: bool,
    pub generation: u64,
}

/// The tokens a renewal hands back.
pub struct Renewed {
    pub access: String,
    pub refresh: String,
}

/// The session as managed state. The lock is async because a renewal holds it across its
/// request: whoever meets a 401 meanwhile waits for it and then takes the new token.
#[derive(Default)]
pub struct SessionState {
    session: Mutex<Option<Session>>,
    generations: AtomicU64,
}

impl SessionState {
    /// Starts a session, replacing any other.
    pub async fn set(
        &self,
        server_url: String,
        access: String,
        refresh: String,
        username: String,
        is_admin: bool,
    ) {
        let mut session = self.session.lock().await;
        *session = Some(Session {
            server_url,
            access,
            refresh,
            username,
            is_admin,
            generation: self.next_generation(),
        });
    }

    /// A copy of the current session, if there is one.
    pub async fn current(&self) -> Option<Session> {
        self.session.lock().await.clone()
    }

    fn next_generation(&self) -> u64 {
        self.generations.fetch_add(1, Ordering::Relaxed) + 1
    }
}

/// The token pin's answer without a session (`validation::require_pinned_destination`),
/// the one the UI already knows.
fn no_session() -> AppError {
    AppError::Validation("Keine aktive Sitzung — Anfrage abgelehnt".to_string())
}

/// Sends the request `build` makes for the session's server with the session's access
/// token. A 401 renews the session at most once, through `renew` (server URL, refresh
/// token), and single-flight: under the lock only a request that still sees the generation
/// it went out with renews, one behind it finds the new generation and only repeats. The
/// server rotates the refresh token, so a second renewal with the old one would count as
/// reuse and revoke the whole session. A failed renewal ends the session with
/// [`AppError::SessionExpired`]. Without a session nothing is sent.
pub async fn authed_send<B, R, F>(
    state: &SessionState,
    build: B,
    renew: R,
) -> Result<reqwest::Response, AppError>
where
    B: Fn(&str) -> Result<reqwest::RequestBuilder, AppError>,
    R: FnOnce(String, String) -> F,
    F: Future<Output = Result<Renewed, AppError>>,
{
    let seen = state.current().await.ok_or_else(no_session)?;
    let response = send(&build, &seen).await?;
    if response.status() != reqwest::StatusCode::UNAUTHORIZED {
        return Ok(response);
    }
    let mut slot = state.session.lock().await;
    // Signed out, or signed in elsewhere or as someone else, while the request was under
    // way: the 401 belongs to a session that is gone, and the caller gets it.
    let Some(current) = slot
        .as_mut()
        .filter(|now| now.server_url == seen.server_url && now.username == seen.username)
    else {
        return Ok(response);
    };
    if current.generation == seen.generation {
        match renew(current.server_url.clone(), current.refresh.clone()).await {
            Ok(renewed) => {
                current.access = renewed.access;
                current.refresh = renewed.refresh;
                current.generation = state.next_generation();
            }
            Err(e) => {
                log::warn!("Session renewal failed, the session ends: {e}");
                *slot = None;
                return Err(AppError::SessionExpired);
            }
        }
    }
    let retry = current.clone();
    drop(slot);
    drop(response);
    send(&build, &retry).await
}

async fn send<B>(build: &B, session: &Session) -> Result<reqwest::Response, AppError>
where
    B: Fn(&str) -> Result<reqwest::RequestBuilder, AppError>,
{
    Ok(build(&session.server_url)?
        .bearer_auth(&session.access)
        .send()
        .await?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicUsize;
    use std::sync::{Arc, Mutex as StdMutex};
    use std::time::Duration;

    use reqwest::StatusCode;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::sync::Barrier;

    /// The renewals a test saw: server URL and refresh token of each.
    type Renewals = Arc<StdMutex<Vec<(String, String)>>>;

    /// The Authorization header of a request head, `-` without one.
    fn authorization(head: &str) -> String {
        head.lines()
            .find_map(|line| {
                let (name, value) = line.split_once(':')?;
                name.eq_ignore_ascii_case("authorization")
                    .then(|| value.trim().to_string())
            })
            .unwrap_or_else(|| "-".to_string())
    }

    /// Serve HTTP on a fresh loopback port, each connection on its own task, so a test can
    /// hold requests until several have arrived. The Authorization header of every request
    /// lands in the log, and `answer` gives the status line for it.
    async fn serve<A, F>(answer: A) -> (String, Arc<StdMutex<Vec<String>>>)
    where
        A: Fn(String) -> F + Send + Sync + 'static,
        F: Future<Output = &'static str> + Send + 'static,
    {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://127.0.0.1:{}", listener.local_addr().unwrap().port());
        let log = Arc::new(StdMutex::new(Vec::new()));
        let seen = Arc::clone(&log);
        let answer = Arc::new(answer);
        tokio::spawn(async move {
            loop {
                let (mut tcp, _) = listener.accept().await.unwrap();
                let seen = Arc::clone(&seen);
                let answer = Arc::clone(&answer);
                tokio::spawn(async move {
                    let mut head = Vec::new();
                    let mut buf = [0u8; 1024];
                    while !head.windows(4).any(|w| w == b"\r\n\r\n") {
                        let n = tcp.read(&mut buf).await.unwrap();
                        if n == 0 {
                            break;
                        }
                        head.extend_from_slice(&buf[..n]);
                    }
                    let token = authorization(&String::from_utf8_lossy(&head));
                    seen.lock().unwrap().push(token.clone());
                    let status = answer(token).await;
                    let reply = format!(
                        "HTTP/1.1 {status}\r\ncontent-length: 0\r\nconnection: close\r\n\r\n"
                    );
                    tcp.write_all(reply.as_bytes()).await.unwrap();
                    let _ = tcp.shutdown().await;
                });
            }
        });
        (url, log)
    }

    /// A GET on the session's server.
    fn get(server_url: &str) -> Result<reqwest::RequestBuilder, AppError> {
        let client = crate::http_client::with_timeouts(reqwest::Client::builder()).build()?;
        Ok(client.get(format!("{server_url}/api/servers")))
    }

    async fn signed_in(server_url: &str) -> Arc<SessionState> {
        let state = Arc::new(SessionState::default());
        state
            .set(
                server_url.to_string(),
                "expired".to_string(),
                "refresh".to_string(),
                "ops-admin".to_string(),
                true,
            )
            .await;
        state
    }

    /// A renewal the server grants.
    async fn granted(
        renewals: Renewals,
        url: String,
        refresh: String,
    ) -> Result<Renewed, AppError> {
        renewals.lock().unwrap().push((url, refresh));
        // The renewal is under way while another request may meet its 401.
        tokio::task::yield_now().await;
        Ok(Renewed {
            access: "renewed".to_string(),
            refresh: "refresh-2".to_string(),
        })
    }

    /// A renewal the server refuses.
    async fn refused(
        renewals: Renewals,
        url: String,
        refresh: String,
    ) -> Result<Renewed, AppError> {
        renewals.lock().unwrap().push((url, refresh));
        Err(AppError::Validation("Refresh fehlgeschlagen".to_string()))
    }

    fn log_of(log: &StdMutex<Vec<String>>) -> Vec<String> {
        log.lock().unwrap().clone()
    }

    #[tokio::test]
    async fn two_concurrent_401s_renew_once_and_both_retry_with_the_new_token() {
        // Both requests go out with the old token before either sees its 401.
        let gate = Arc::new(Barrier::new(2));
        let (server, log) = serve(move |token| {
            let gate = Arc::clone(&gate);
            async move {
                if token == "Bearer expired" {
                    gate.wait().await;
                    "401 Unauthorized"
                } else if token == "Bearer renewed" {
                    "200 OK"
                } else {
                    "400 Bad Request"
                }
            }
        })
        .await;
        let state = signed_in(&server).await;
        let before = state.current().await.unwrap().generation;
        let renewals = Renewals::default();

        let (first, second) = tokio::time::timeout(Duration::from_secs(10), async {
            tokio::join!(
                authed_send(&state, get, |url, refresh| granted(
                    Arc::clone(&renewals),
                    url,
                    refresh
                )),
                authed_send(&state, get, |url, refresh| granted(
                    Arc::clone(&renewals),
                    url,
                    refresh
                )),
            )
        })
        .await
        .expect("both requests should have gone out with the old token");

        assert_eq!(first.unwrap().status(), StatusCode::OK);
        assert_eq!(second.unwrap().status(), StatusCode::OK);
        assert_eq!(
            *renewals.lock().unwrap(),
            [(server.clone(), "refresh".to_string())]
        );
        let mut tokens = log_of(&log);
        tokens.sort();
        assert_eq!(
            tokens,
            [
                "Bearer expired",
                "Bearer expired",
                "Bearer renewed",
                "Bearer renewed"
            ]
        );
        let after = state.current().await.unwrap();
        assert_eq!(
            (after.access.as_str(), after.refresh.as_str()),
            ("renewed", "refresh-2")
        );
        assert_ne!(after.generation, before);
        // A renewal changes the tokens, not who is signed in where.
        assert_eq!(
            (after.server_url, after.username.as_str(), after.is_admin),
            (server, "ops-admin", true)
        );
    }

    #[tokio::test]
    async fn a_failed_renewal_ends_the_session() {
        let (server, log) = serve(|_| async { "401 Unauthorized" }).await;
        let state = signed_in(&server).await;
        let renewals = Renewals::default();

        let result = authed_send(&state, get, |url, refresh| {
            refused(Arc::clone(&renewals), url, refresh)
        })
        .await;

        assert!(
            matches!(result, Err(AppError::SessionExpired)),
            "{:?}",
            result.map(|response| response.status())
        );
        assert!(state.current().await.is_none());
        assert_eq!(renewals.lock().unwrap().len(), 1);
        // No retry without a token.
        assert_eq!(log_of(&log), ["Bearer expired"]);
    }

    #[tokio::test]
    async fn a_401_after_the_renewal_is_not_renewed_again() {
        let (server, log) = serve(|_| async { "401 Unauthorized" }).await;
        let state = signed_in(&server).await;
        let renewals = Renewals::default();

        let response = authed_send(&state, get, |url, refresh| {
            granted(Arc::clone(&renewals), url, refresh)
        })
        .await
        .unwrap();

        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
        assert_eq!(renewals.lock().unwrap().len(), 1);
        assert_eq!(log_of(&log), ["Bearer expired", "Bearer renewed"]);
        assert_eq!(state.current().await.unwrap().access, "renewed");
    }

    #[tokio::test]
    async fn without_a_session_nothing_is_sent() {
        let (_server, log) = serve(|_| async { "200 OK" }).await;
        let state = SessionState::default();
        let builds = AtomicUsize::new(0);
        let renewals = Renewals::default();

        let result = authed_send(
            &state,
            |url: &str| {
                builds.fetch_add(1, Ordering::Relaxed);
                get(url)
            },
            |url, refresh| granted(Arc::clone(&renewals), url, refresh),
        )
        .await;

        let message = result.err().map(|e| e.to_string()).unwrap_or_default();
        assert!(message.starts_with("Keine aktive Sitzung"), "{message}");
        assert_eq!(builds.load(Ordering::Relaxed), 0);
        assert!(renewals.lock().unwrap().is_empty());
        assert_eq!(log_of(&log), Vec::<String>::new());
    }

    #[tokio::test]
    async fn a_401_from_a_session_replaced_meanwhile_is_not_renewed() {
        #[derive(Clone, Copy, Debug)]
        enum Change {
            SignedOut,
            OtherServer,
            OtherUser,
            SameUserAgain,
        }
        for change in [
            Change::SignedOut,
            Change::OtherServer,
            Change::OtherUser,
            Change::SameUserAgain,
        ] {
            let state = Arc::new(SessionState::default());
            let shared = Arc::clone(&state);
            let (server, log) = serve(move |token| {
                let state = Arc::clone(&shared);
                async move {
                    if token != "Bearer expired" {
                        return "200 OK";
                    }
                    // The session changes while the request waits for its answer.
                    let here = state.current().await.unwrap().server_url;
                    let (url, user) = match change {
                        Change::SignedOut => {
                            *state.session.lock().await = None;
                            return "401 Unauthorized";
                        }
                        Change::OtherServer => ("https://adminhelper.example:8443", "ops-admin"),
                        Change::OtherUser => (here.as_str(), "someone-else"),
                        Change::SameUserAgain => (here.as_str(), "ops-admin"),
                    };
                    state
                        .set(
                            url.to_string(),
                            "next".to_string(),
                            "next-refresh".to_string(),
                            user.to_string(),
                            true,
                        )
                        .await;
                    "401 Unauthorized"
                }
            })
            .await;
            state
                .set(
                    server.clone(),
                    "expired".to_string(),
                    "refresh".to_string(),
                    "ops-admin".to_string(),
                    true,
                )
                .await;
            let renewals = Renewals::default();

            let response = authed_send(&state, get, |url, refresh| {
                granted(Arc::clone(&renewals), url, refresh)
            })
            .await
            .unwrap();

            assert!(renewals.lock().unwrap().is_empty(), "{change:?}");
            match change {
                // The same user on the same server: only the token is new, so the request
                // goes again with it.
                Change::SameUserAgain => {
                    assert_eq!(response.status(), StatusCode::OK, "{change:?}");
                    assert_eq!(
                        log_of(&log),
                        ["Bearer expired", "Bearer next"],
                        "{change:?}"
                    );
                }
                // The session the request belonged to is gone: the caller gets its 401.
                _ => {
                    assert_eq!(response.status(), StatusCode::UNAUTHORIZED, "{change:?}");
                    assert_eq!(log_of(&log), ["Bearer expired"], "{change:?}");
                }
            }
            let token = state.current().await.map(|session| session.access);
            match change {
                Change::SignedOut => assert_eq!(token, None, "{change:?}"),
                _ => assert_eq!(token.as_deref(), Some("next"), "{change:?}"),
            }
        }
    }
}
