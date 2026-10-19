// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! The server session of this process, in memory only: server URL, user and tokens.
//! Authenticated requests go through [`authed_send`], the one place that renews them.

use std::future::Future;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::OnceLock;
use std::time::Duration;

use tokio::sync::Mutex;

use crate::error::AppError;
use crate::validation::same_server_destination;

/// The longest a renewal may take. It holds the session meanwhile, so every request, sign-in
/// and sign-out waits for it.
const RENEWAL_DEADLINE: Duration = Duration::from_secs(30);

/// A signed-in session. `generation` changes with every token pair, from a login or a
/// renewal, and is never handed out twice.
#[derive(Clone)]
pub struct Session {
    pub server_url: String,
    pub access: String,
    pub refresh: String,
    pub username: String,
    pub generation: u64,
}

impl Session {
    /// Who is signed in where, without the tokens.
    fn signed_in(&self) -> SignedIn {
        SignedIn {
            server_url: self.server_url.clone(),
            username: self.username.clone(),
        }
    }
}

/// Who an answer was sent for: the user and the server, not the tokens.
pub struct SignedIn {
    pub server_url: String,
    pub username: String,
}

/// The tokens a renewal hands back.
pub struct Renewed {
    pub access: String,
    pub refresh: String,
}

/// Who hears that a failed renewal ended the session: in the app the webview, through the
/// event `session-expired` (`main.rs`); in a test a counter.
type ExpiryListener = Box<dyn Fn() + Send + Sync>;

/// The session as managed state. The lock is async because a renewal holds it across its
/// request: whoever meets a 401 meanwhile waits for it and then takes the new token.
#[derive(Default)]
pub struct SessionState {
    session: Mutex<Option<Session>>,
    generations: AtomicU64,
    expiry: OnceLock<ExpiryListener>,
}

impl SessionState {
    /// Starts a session, replacing any other.
    pub async fn set(&self, server_url: String, access: String, refresh: String, username: String) {
        let mut session = self.session.lock().await;
        *session = Some(Session {
            server_url,
            access,
            refresh,
            username,
            generation: self.next_generation(),
        });
    }

    /// A copy of the current session, if there is one.
    pub async fn current(&self) -> Option<Session> {
        self.session.lock().await.clone()
    }

    /// Ends the session and hands it back, for the sign-out at the server.
    pub async fn take(&self) -> Option<Session> {
        self.session.lock().await.take()
    }

    /// Refuses the answer of a session that is gone: `who` signed out, or another user or
    /// server signed in since the request went out. A renewal or a new sign-in of the same
    /// user on the same server keeps it. A caller that takes an answer over (a tunnel config,
    /// a sync) checks this first.
    pub async fn ensure_signed_in(&self, who: &SignedIn) -> Result<(), AppError> {
        match self.session.lock().await.as_ref() {
            Some(now) if now.server_url == who.server_url && now.username == who.username => Ok(()),
            _ => Err(AppError::Validation(
                "The session changed while the request was under way — answer dropped".to_string(),
            )),
        }
    }

    /// Sets who hears that a failed renewal ended the session, once, at the start. A sign-out
    /// is no such end and tells nobody.
    pub fn on_expiry(&self, listener: impl Fn() + Send + Sync + 'static) {
        if self.expiry.set(Box::new(listener)).is_err() {
            log::warn!("The session already has an expiry listener; the second one is ignored");
        }
    }

    fn next_generation(&self) -> u64 {
        self.generations.fetch_add(1, Ordering::Relaxed) + 1
    }
}

/// The answer to a request without a session, the one the UI already knows, and the only
/// source of its text.
pub fn no_session() -> AppError {
    AppError::Validation("Keine aktive Sitzung — Anfrage abgelehnt".to_string())
}

/// Sends the request `build` makes for the session's server with the session's access
/// token, and only if the request as built goes to that server. A 401 renews the session at
/// most once, through `renew` (server URL, refresh token), and single-flight: under the lock
/// only a request that still sees the generation it went out with renews, one behind it
/// finds the new generation and only repeats. The server rotates the refresh token, so a
/// second renewal with the old one would count as reuse and revoke the whole session. A
/// renewal that fails or outlasts [`RENEWAL_DEADLINE`] ends the session with
/// [`AppError::SessionExpired`] and tells the listener of [`SessionState::on_expiry`]. Without
/// a session nothing is sent.
///
/// The answer comes with the user it was sent for; a caller that takes it over checks
/// [`SessionState::ensure_signed_in`] first.
pub async fn authed_send<B, R, F>(
    state: &SessionState,
    build: B,
    renew: R,
) -> Result<(reqwest::Response, SignedIn), AppError>
where
    B: Fn(&str) -> Result<reqwest::RequestBuilder, AppError>,
    R: FnOnce(String, String) -> F,
    F: Future<Output = Result<Renewed, AppError>>,
{
    send_renewing(state, build, renew, RENEWAL_DEADLINE).await
}

/// [`authed_send`] with the renewal deadline as a parameter.
async fn send_renewing<B, R, F>(
    state: &SessionState,
    build: B,
    renew: R,
    deadline: Duration,
) -> Result<(reqwest::Response, SignedIn), AppError>
where
    B: Fn(&str) -> Result<reqwest::RequestBuilder, AppError>,
    R: FnOnce(String, String) -> F,
    F: Future<Output = Result<Renewed, AppError>>,
{
    let seen = state.current().await.ok_or_else(no_session)?;
    let response = send(&build, &seen).await?;
    if response.status() != reqwest::StatusCode::UNAUTHORIZED {
        return Ok((response, seen.signed_in()));
    }
    let mut slot = state.session.lock().await;
    // Signed out, or signed in elsewhere or as someone else, while the request was under
    // way: the 401 belongs to a session that is gone, and the caller gets it.
    let Some(current) = slot
        .as_mut()
        .filter(|now| now.server_url == seen.server_url && now.username == seen.username)
    else {
        return Ok((response, seen.signed_in()));
    };
    if current.generation == seen.generation {
        let renewal = renew(current.server_url.clone(), current.refresh.clone());
        // Past the deadline the session ends as on a refusal: the server may have rotated the
        // refresh token by then, so the one held here could not renew again anyway.
        let renewed = tokio::time::timeout(deadline, renewal)
            .await
            .unwrap_or_else(|_| {
                Err(AppError::Connection(format!(
                    "no answer within {} s",
                    deadline.as_secs_f32()
                )))
            });
        match renewed {
            Ok(renewed) => {
                current.access = renewed.access;
                current.refresh = renewed.refresh;
                current.generation = state.next_generation();
            }
            Err(e) => {
                log::warn!("Session renewal failed, the session ends: {e}");
                *slot = None;
                // Outside the lock: whoever hears it may ask the session at once.
                drop(slot);
                if let Some(listener) = state.expiry.get() {
                    listener();
                }
                return Err(AppError::SessionExpired);
            }
        }
    }
    let retry = current.clone();
    drop(slot);
    drop(response);
    Ok((send(&build, &retry).await?, retry.signed_in()))
}

/// Sends what `build` makes with the session's access token. The pin checks the request as
/// built, not the URL it was built from: a path can still move the authority (`@host`), and
/// the token must reach no origin but the session's.
async fn send<B>(build: &B, session: &Session) -> Result<reqwest::Response, AppError>
where
    B: Fn(&str) -> Result<reqwest::RequestBuilder, AppError>,
{
    let (client, request) = build(&session.server_url)?.build_split();
    let request = request?;
    if !same_server_destination(request.url().as_str(), &session.server_url) {
        return Err(AppError::Validation(
            "The request target is not the signed-in server — request refused".to_string(),
        ));
    }
    Ok(reqwest::RequestBuilder::from_parts(client, request)
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

        assert_eq!(first.unwrap().0.status(), StatusCode::OK);
        assert_eq!(second.unwrap().0.status(), StatusCode::OK);
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
            (after.server_url, after.username.as_str()),
            (server, "ops-admin")
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
            result.map(|(response, _)| response.status())
        );
        assert!(state.current().await.is_none());
        assert_eq!(renewals.lock().unwrap().len(), 1);
        // No retry without a token.
        assert_eq!(log_of(&log), ["Bearer expired"]);
    }

    #[tokio::test]
    async fn a_renewal_past_the_deadline_ends_the_session() {
        let (server, log) = serve(|_| async { "401 Unauthorized" }).await;
        let state = signed_in(&server).await;

        // A renewal that never answers; the outer limit only keeps a regression from hanging.
        let result = tokio::time::timeout(
            Duration::from_secs(10),
            send_renewing(
                &state,
                get,
                |_, _| std::future::pending::<Result<Renewed, AppError>>(),
                Duration::from_millis(50),
            ),
        )
        .await
        .expect("the renewal deadline should have ended the wait");

        assert!(
            matches!(result, Err(AppError::SessionExpired)),
            "{:?}",
            result.map(|(response, _)| response.status())
        );
        assert!(state.current().await.is_none());
        assert_eq!(log_of(&log), ["Bearer expired"]);
    }

    #[tokio::test]
    async fn a_request_off_the_signed_in_server_is_not_sent() {
        let (server, log) = serve(|_| async { "200 OK" }).await;
        let (foreign, foreign_log) = serve(|_| async { "200 OK" }).await;
        let state = signed_in(&server).await;
        let renewals = Renewals::default();

        // The request as built goes elsewhere than the session's server.
        let result = authed_send(
            &state,
            |_: &str| get(&foreign),
            |url, refresh| granted(Arc::clone(&renewals), url, refresh),
        )
        .await;

        let message = result.err().map(|e| e.to_string()).unwrap_or_default();
        assert!(message.contains("not the signed-in server"), "{message}");
        assert_eq!(log_of(&foreign_log), Vec::<String>::new());
        assert_eq!(log_of(&log), Vec::<String>::new());
        assert!(renewals.lock().unwrap().is_empty());
        assert_eq!(state.current().await.unwrap().access, "expired");
    }

    #[tokio::test]
    async fn a_401_after_the_renewal_is_not_renewed_again() {
        let (server, log) = serve(|_| async { "401 Unauthorized" }).await;
        let state = signed_in(&server).await;
        let renewals = Renewals::default();

        let (response, _) = authed_send(&state, get, |url, refresh| {
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
                )
                .await;
            let renewals = Renewals::default();

            let (response, answered_for) = authed_send(&state, get, |url, refresh| {
                granted(Arc::clone(&renewals), url, refresh)
            })
            .await
            .unwrap();

            assert!(renewals.lock().unwrap().is_empty(), "{change:?}");
            // The answer names the user it was sent for, so a caller can tell whether that one
            // is still signed in before it takes the answer over.
            assert_eq!(
                (
                    answered_for.server_url.as_str(),
                    answered_for.username.as_str()
                ),
                (server.as_str(), "ops-admin"),
                "{change:?}"
            );
            let taken_over = state.ensure_signed_in(&answered_for).await;
            match change {
                Change::SameUserAgain => assert!(taken_over.is_ok(), "{change:?}"),
                _ => assert!(taken_over.is_err(), "{change:?}"),
            }
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
