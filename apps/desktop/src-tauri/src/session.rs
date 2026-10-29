// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! The server session of this process, in memory only: server URL, user, tokens, the
//! certificate choice of the sign-in and the tunnel mappings and connections it fetched last.
//! Authenticated requests go through [`authed_send`], the one place that renews them.

use std::future::Future;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, OnceLock};
use std::time::Duration;

use tokio::sync::Mutex;

use crate::error::AppError;
use crate::models::Connection;
use crate::tunnel::TunnelMapping;
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
    /// Whether the sign-in allowed a self-signed server certificate (pinned on first use).
    /// Every request and renewal of the session builds its client with it, never with a
    /// value of its own; a change of the setting takes effect at the next sign-in. An
    /// enrolled device uses its pinned CA either way (`http_client::build_client`).
    pub allow_self_signed: bool,
    pub generation: u64,
    /// The tunnel mappings the session fetched last ([`SessionState::keep_tunnels`]), empty
    /// before. Only these resolve the target of a stored password, never mappings the webview
    /// passes.
    pub tunnels: Arc<[TunnelMapping]>,
    /// The server's connections the session fetched last ([`SessionState::keep_connections`]),
    /// empty before: a mapping takes a stored password only for the connection the server
    /// lists under its id.
    pub connections: Arc<[Connection]>,
}

impl Session {
    /// Who is signed in where, without the tokens.
    pub fn signed_in(&self) -> SignedIn {
        SignedIn {
            server_url: self.server_url.clone(),
            username: self.username.clone(),
            allow_self_signed: self.allow_self_signed,
        }
    }
}

/// Who an answer was sent for: the user, the server and the certificate choice of that
/// sign-in, not the tokens.
pub struct SignedIn {
    pub server_url: String,
    pub username: String,
    pub allow_self_signed: bool,
}

/// The tokens a renewal hands back.
pub struct Renewed {
    pub access: String,
    pub refresh: String,
}

/// Who hears that a failed renewal ended the session: in the app the webview, through the
/// event `session-expired` (`main.rs`); in a test a counter.
type ExpiryListener = Box<dyn Fn() + Send + Sync>;

/// Who hears that who is signed in changed: in the app frpc, which ends then (`main.rs`); in a
/// test a counter.
type SignInListener = Box<dyn Fn() + Send + Sync>;

/// The session as managed state. The lock is async because a renewal holds it across its
/// request: whoever meets a 401 meanwhile waits for it and then takes the new token.
#[derive(Default)]
pub struct SessionState {
    session: Mutex<Option<Session>>,
    generations: AtomicU64,
    expiry: OnceLock<ExpiryListener>,
    sign_in_change: OnceLock<SignInListener>,
}

impl SessionState {
    /// Starts a session, replacing any other, and tells the listener of
    /// [`SessionState::on_sign_in_change`].
    pub async fn set(
        &self,
        server_url: String,
        access: String,
        refresh: String,
        username: String,
        allow_self_signed: bool,
    ) {
        let mut session = self.session.lock().await;
        *session = Some(Session {
            server_url,
            access,
            refresh,
            username,
            allow_self_signed,
            generation: self.next_generation(),
            tunnels: Arc::default(),
            connections: Arc::default(),
        });
        drop(session);
        self.tell_sign_in_changed();
    }

    /// A copy of the current session, if there is one.
    pub async fn current(&self) -> Option<Session> {
        self.session.lock().await.clone()
    }

    /// Ends the session and hands it back, for the sign-out at the server, and tells the
    /// listener of [`SessionState::on_sign_in_change`], also without a session: ending what
    /// ran for a sign-in twice does no harm.
    pub async fn take(&self) -> Option<Session> {
        let ended = self.session.lock().await.take();
        self.tell_sign_in_changed();
        ended
    }

    /// Refuses the answer of a session that is gone: `who` signed out, or another user or
    /// server signed in since the request went out. A renewal or a new sign-in of the same
    /// user on the same server keeps it. A caller that takes an answer over (a tunnel config,
    /// a sync) checks this first.
    pub async fn ensure_signed_in(&self, who: &SignedIn) -> Result<(), AppError> {
        self.change_signed_in(who, |_| ()).await
    }

    /// Keeps the tunnel mappings fetched for `who` (`tunnel::fetch_tunnels`) in the session,
    /// if `who` is still signed in (as [`SessionState::ensure_signed_in`]). They last as long
    /// as the session: a sign-out, a new sign-in and a failed renewal drop them.
    pub async fn keep_tunnels(
        &self,
        who: &SignedIn,
        tunnels: Vec<TunnelMapping>,
    ) -> Result<(), AppError> {
        self.change_signed_in(who, |now| now.tunnels = tunnels.into())
            .await
    }

    /// The tunnel mappings the session fetched last; none without a session, before the first
    /// fetch that succeeded, and for a user who may not read them. The app reads them from
    /// [`SessionState::current`], together with the sign-in they belong to.
    #[cfg(test)]
    pub async fn tunnels(&self) -> Arc<[TunnelMapping]> {
        self.session
            .lock()
            .await
            .as_ref()
            .map(|now| Arc::clone(&now.tunnels))
            .unwrap_or_default()
    }

    /// Keeps the server's connections fetched for `who` (`sync::fetch_connections_jwt`) in
    /// the session, like [`SessionState::keep_tunnels`].
    pub async fn keep_connections(
        &self,
        who: &SignedIn,
        connections: Vec<Connection>,
    ) -> Result<(), AppError> {
        self.change_signed_in(who, |now| now.connections = connections.into())
            .await
    }

    /// The server's connections the session fetched last; none without a session and before
    /// the first fetch that succeeded. The app reads them from [`SessionState::current`], like
    /// [`SessionState::tunnels`].
    #[cfg(test)]
    pub async fn connections(&self) -> Arc<[Connection]> {
        self.session
            .lock()
            .await
            .as_ref()
            .map(|now| Arc::clone(&now.connections))
            .unwrap_or_default()
    }

    /// Applies `change` to the session if `who` is still signed in, under one lock; see
    /// [`SessionState::ensure_signed_in`].
    async fn change_signed_in(
        &self,
        who: &SignedIn,
        change: impl FnOnce(&mut Session),
    ) -> Result<(), AppError> {
        match self.session.lock().await.as_mut() {
            Some(now) if now.server_url == who.server_url && now.username == who.username => {
                change(now);
                Ok(())
            }
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

    /// Sets who hears that who is signed in changed, once, at the start: every sign-in, every
    /// sign-out and the end of the session by a failed renewal ([`authed_send`]). A renewal
    /// that succeeds keeps the sign-in and tells nobody.
    pub fn on_sign_in_change(&self, listener: impl Fn() + Send + Sync + 'static) {
        if self.sign_in_change.set(Box::new(listener)).is_err() {
            log::warn!("The session already has a sign-in listener; the second one is ignored");
        }
    }

    /// Tells the listener of [`SessionState::on_sign_in_change`]. Only outside the session lock:
    /// whoever hears it may ask the session at once.
    fn tell_sign_in_changed(&self) {
        if let Some(listener) = self.sign_in_change.get() {
            listener();
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

/// Sends the request `build` makes for the session's server (URL and certificate choice of
/// the sign-in) with the session's access token, and only if the request as built goes to
/// that server. A 401 renews the session at most once, through [`crate::auth::try_refresh`]
/// with the session's certificate choice, and single-flight: under the lock only a request
/// that still sees the generation it went out with renews, one behind it finds the new
/// generation and only repeats. The server rotates the refresh token, so a second renewal
/// with the old one would count as reuse and revoke the whole session. A renewal that fails
/// or outlasts [`RENEWAL_DEADLINE`] ends the session with [`AppError::SessionExpired`] and
/// tells the listeners of [`SessionState::on_sign_in_change`] and [`SessionState::on_expiry`].
/// Without a session nothing is sent.
///
/// The answer comes with the user it was sent for; a caller that takes it over checks
/// [`SessionState::ensure_signed_in`] first.
pub async fn authed_send<B>(
    state: &SessionState,
    build: B,
) -> Result<(reqwest::Response, SignedIn), AppError>
where
    B: Fn(&str, bool) -> Result<reqwest::RequestBuilder, AppError>,
{
    send_renewing(
        state,
        build,
        |server_url, refresh, allow_self_signed| async move {
            crate::auth::try_refresh(&server_url, &refresh, allow_self_signed).await
        },
        RENEWAL_DEADLINE,
    )
    .await
}

/// [`authed_send`] with the renewal (server URL, refresh token, certificate choice) and its
/// deadline as parameters.
async fn send_renewing<B, R, F>(
    state: &SessionState,
    build: B,
    renew: R,
    deadline: Duration,
) -> Result<(reqwest::Response, SignedIn), AppError>
where
    B: Fn(&str, bool) -> Result<reqwest::RequestBuilder, AppError>,
    R: FnOnce(String, String, bool) -> F,
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
        let renewal = renew(
            current.server_url.clone(),
            current.refresh.clone(),
            current.allow_self_signed,
        );
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
                state.tell_sign_in_changed();
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
    B: Fn(&str, bool) -> Result<reqwest::RequestBuilder, AppError>,
{
    let (client, request) = build(&session.server_url, session.allow_self_signed)?.build_split();
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
    fn get(
        server_url: &str,
        _allow_self_signed: bool,
    ) -> Result<reqwest::RequestBuilder, AppError> {
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
                false,
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
                send_renewing(
                    &state,
                    get,
                    |url, refresh, _| granted(Arc::clone(&renewals), url, refresh),
                    RENEWAL_DEADLINE
                ),
                send_renewing(
                    &state,
                    get,
                    |url, refresh, _| granted(Arc::clone(&renewals), url, refresh),
                    RENEWAL_DEADLINE
                ),
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

        let result = send_renewing(
            &state,
            get,
            |url, refresh, _| refused(Arc::clone(&renewals), url, refresh),
            RENEWAL_DEADLINE,
        )
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
                |_, _, _| std::future::pending::<Result<Renewed, AppError>>(),
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
        let result = send_renewing(
            &state,
            |_: &str, allow_self_signed| get(&foreign, allow_self_signed),
            |url, refresh, _| granted(Arc::clone(&renewals), url, refresh),
            RENEWAL_DEADLINE,
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

        let (response, _) = send_renewing(
            &state,
            get,
            |url, refresh, _| granted(Arc::clone(&renewals), url, refresh),
            RENEWAL_DEADLINE,
        )
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

        let result = send_renewing(
            &state,
            |url: &str, allow_self_signed| {
                builds.fetch_add(1, Ordering::Relaxed);
                get(url, allow_self_signed)
            },
            |url, refresh, _| granted(Arc::clone(&renewals), url, refresh),
            RENEWAL_DEADLINE,
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
                            false,
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
                    false,
                )
                .await;
            let renewals = Renewals::default();

            let (response, answered_for) = send_renewing(
                &state,
                get,
                |url, refresh, _| granted(Arc::clone(&renewals), url, refresh),
                RENEWAL_DEADLINE,
            )
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

    #[tokio::test]
    async fn the_request_and_its_renewal_take_the_certificate_choice_of_the_sign_in() {
        for choice in [false, true] {
            let (server, log) = serve(|token| async move {
                if token == "Bearer renewed" {
                    "200 OK"
                } else {
                    "401 Unauthorized"
                }
            })
            .await;
            let state = SessionState::default();
            state
                .set(
                    server.clone(),
                    "expired".to_string(),
                    "refresh".to_string(),
                    "ops-admin".to_string(),
                    choice,
                )
                .await;
            let built = StdMutex::new(Vec::new());
            let renewed = StdMutex::new(Vec::new());

            let (response, answered_for) = send_renewing(
                &state,
                |url: &str, allow_self_signed| {
                    built.lock().unwrap().push(allow_self_signed);
                    get(url, allow_self_signed)
                },
                |_, _, allow_self_signed| {
                    renewed.lock().unwrap().push(allow_self_signed);
                    async {
                        Ok(Renewed {
                            access: "renewed".to_string(),
                            refresh: "refresh-2".to_string(),
                        })
                    }
                },
                RENEWAL_DEADLINE,
            )
            .await
            .unwrap();

            assert_eq!(response.status(), StatusCode::OK, "{choice}");
            assert_eq!(
                log_of(&log),
                ["Bearer expired", "Bearer renewed"],
                "{choice}"
            );
            // The request, its renewal and its retry: each with the choice of the sign-in.
            assert_eq!(*built.lock().unwrap(), [choice, choice], "{choice}");
            assert_eq!(*renewed.lock().unwrap(), [choice], "{choice}");
            assert_eq!(answered_for.allow_self_signed, choice);
            assert_eq!(state.current().await.unwrap().allow_self_signed, choice);
        }
    }

    /// A tunnel mapping as `/api/frp/tunnels` lists it, told apart by `id`.
    fn mapping(id: &str) -> TunnelMapping {
        TunnelMapping {
            id: id.to_string(),
            server_id: "s1".to_string(),
            tunnel_type: "stcp".to_string(),
            protocol: "rdp".to_string(),
            local_port: 3389,
            visitor_port: Some(13389),
            custom_domains: None,
            connection_id: Some("c1".to_string()),
            enabled: true,
            name: "rdp-tunnel".to_string(),
        }
    }

    /// A connection as `/api/connections` lists it, told apart by `id`.
    fn connection(id: &str) -> Connection {
        Connection {
            id: id.to_string(),
            name: "T".to_string(),
            kind: crate::models::ConnectionKind::Rdp,
            host: Some("rdp.example.com".to_string()),
            port: Some(3389),
            username: None,
            domain: None,
            key_path: None,
            url: None,
            notes: None,
            tags: Vec::new(),
            trust_cert: false,
            last_used: None,
            server_id: None,
        }
    }

    /// The ids of the tunnel mappings and of the connections the session holds.
    async fn held_ids(state: &SessionState) -> (Vec<String>, Vec<String>) {
        let tunnels = state.tunnels().await;
        let connections = state.connections().await;
        (
            tunnels.iter().map(|mapping| mapping.id.clone()).collect(),
            connections.iter().map(|c| c.id.clone()).collect(),
        )
    }

    fn nothing_held() -> (Vec<String>, Vec<String>) {
        (Vec::new(), Vec::new())
    }

    /// Signs `state` in to `server` as `username`, with the tokens of [`signed_in`].
    async fn sign_in(state: &SessionState, server: &str, username: &str) {
        state
            .set(
                server.to_string(),
                "expired".to_string(),
                "refresh".to_string(),
                username.to_string(),
                false,
            )
            .await;
    }

    /// Signs `state` in to `server` and has the session keep the mapping and the connection
    /// `id`.
    async fn signed_in_with_fetched(state: &SessionState, server: &str, id: &str) {
        sign_in(state, server, "ops-admin").await;
        let who = state.current().await.unwrap().signed_in();
        state.keep_tunnels(&who, vec![mapping(id)]).await.unwrap();
        state
            .keep_connections(&who, vec![connection(id)])
            .await
            .unwrap();
        assert_eq!(
            held_ids(state).await,
            (vec![id.to_string()], vec![id.to_string()])
        );
    }

    #[tokio::test]
    async fn the_fetched_mappings_and_connections_last_as_long_as_the_session() {
        let (server, _log) = serve(|token| async move {
            if token == "Bearer renewed" {
                "200 OK"
            } else {
                "401 Unauthorized"
            }
        })
        .await;
        let state = SessionState::default();
        let renewals = Renewals::default();

        // A sign-in starts without them.
        sign_in(&state, &server, "ops-admin").await;
        assert_eq!(held_ids(&state).await, nothing_held());

        // A renewal changes the tokens, not what the session fetched.
        signed_in_with_fetched(&state, &server, "t1").await;
        let (response, _) = send_renewing(
            &state,
            get,
            |url, refresh, _| granted(Arc::clone(&renewals), url, refresh),
            RENEWAL_DEADLINE,
        )
        .await
        .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            held_ids(&state).await,
            (vec!["t1".to_string()], vec!["t1".to_string()])
        );

        // A new sign-in, even of the same user on the same server, starts over.
        sign_in(&state, &server, "ops-admin").await;
        assert_eq!(held_ids(&state).await, nothing_held());

        // A sign-out ends them.
        signed_in_with_fetched(&state, &server, "t2").await;
        state.take().await;
        assert_eq!(held_ids(&state).await, nothing_held());

        // So does a renewal that fails.
        signed_in_with_fetched(&state, &server, "t3").await;
        let result = send_renewing(
            &state,
            get,
            |url, refresh, _| refused(Arc::clone(&renewals), url, refresh),
            RENEWAL_DEADLINE,
        )
        .await;
        assert!(matches!(result, Err(AppError::SessionExpired)));
        assert_eq!(held_ids(&state).await, nothing_held());
    }

    #[tokio::test]
    async fn what_was_fetched_for_a_session_gone_meanwhile_is_not_kept() {
        let server = "https://adminhelper.example:8443";
        let state = SessionState::default();
        sign_in(&state, server, "ops-admin").await;
        let who = state.current().await.unwrap().signed_in();

        sign_in(&state, server, "someone-else").await;
        let kept = state.keep_tunnels(&who, vec![mapping("t1")]).await;
        assert!(kept.is_err(), "mappings kept for another user");
        let kept = state.keep_connections(&who, vec![connection("c1")]).await;
        assert!(kept.is_err(), "connections kept for another user");
        assert_eq!(held_ids(&state).await, nothing_held());

        state.take().await;
        let kept = state.keep_tunnels(&who, vec![mapping("t1")]).await;
        assert!(kept.is_err(), "mappings kept without a session");
        let kept = state.keep_connections(&who, vec![connection("c1")]).await;
        assert!(kept.is_err(), "connections kept without a session");
        assert_eq!(held_ids(&state).await, nothing_held());
    }

    /// Counts how often `state` tells that who is signed in changed. Whoever hears it may ask
    /// the session at once, so the session lock has to be free each time.
    fn sign_in_changes(state: &Arc<SessionState>) -> Arc<AtomicUsize> {
        let count = Arc::new(AtomicUsize::new(0));
        let heard = Arc::clone(&count);
        let state_seen = Arc::downgrade(state);
        state.on_sign_in_change(move || {
            let state = state_seen.upgrade().expect("the session state");
            assert!(
                state.session.try_lock().is_ok(),
                "told under the session lock"
            );
            heard.fetch_add(1, Ordering::Relaxed);
        });
        count
    }

    /// Counts how often `state` tells that a failed renewal ended it.
    fn expiries(state: &SessionState) -> Arc<AtomicUsize> {
        let count = Arc::new(AtomicUsize::new(0));
        let heard = Arc::clone(&count);
        state.on_expiry(move || {
            heard.fetch_add(1, Ordering::Relaxed);
        });
        count
    }

    fn told(count: &AtomicUsize) -> usize {
        count.load(Ordering::Relaxed)
    }

    #[tokio::test]
    async fn a_sign_in_tells_that_the_sign_in_changed() {
        let server = "https://adminhelper.example:8443";
        let state = Arc::new(SessionState::default());
        let changes = sign_in_changes(&state);

        sign_in(&state, server, "ops-admin").await;
        assert_eq!(told(&changes), 1);

        // A new sign-in replaces the session, even one of the same user on the same server.
        sign_in(&state, server, "ops-admin").await;
        assert_eq!(told(&changes), 2);
    }

    #[tokio::test]
    async fn a_sign_out_tells_that_the_sign_in_changed() {
        let state = signed_in("https://adminhelper.example:8443").await;
        let changes = sign_in_changes(&state);

        assert!(state.take().await.is_some());
        assert_eq!(told(&changes), 1);

        // A sign-out without a session tells all the same.
        assert!(state.take().await.is_none());
        assert_eq!(told(&changes), 2);
    }

    #[tokio::test]
    async fn a_failed_renewal_tells_that_the_sign_in_changed_and_that_the_session_expired() {
        let (server, _log) = serve(|_| async { "401 Unauthorized" }).await;
        let state = signed_in(&server).await;
        let (changes, expired) = (sign_in_changes(&state), expiries(&state));
        let renewals = Renewals::default();

        let result = send_renewing(
            &state,
            get,
            |url, refresh, _| refused(Arc::clone(&renewals), url, refresh),
            RENEWAL_DEADLINE,
        )
        .await;

        assert!(
            matches!(result, Err(AppError::SessionExpired)),
            "{:?}",
            result.map(|(response, _)| response.status())
        );
        assert!(state.current().await.is_none());
        assert_eq!((told(&changes), told(&expired)), (1, 1));
    }

    #[tokio::test]
    async fn a_renewal_that_succeeds_tells_nobody() {
        let (server, _log) = serve(|token| async move {
            if token == "Bearer renewed" {
                "200 OK"
            } else {
                "401 Unauthorized"
            }
        })
        .await;
        let state = signed_in(&server).await;
        let (changes, expired) = (sign_in_changes(&state), expiries(&state));
        let renewals = Renewals::default();

        let (response, _) = send_renewing(
            &state,
            get,
            |url, refresh, _| granted(Arc::clone(&renewals), url, refresh),
            RENEWAL_DEADLINE,
        )
        .await
        .unwrap();

        // The same sign-in with new tokens.
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(state.current().await.unwrap().access, "renewed");
        assert_eq!((told(&changes), told(&expired)), (0, 0));
    }

    #[tokio::test]
    async fn without_listeners_the_sign_in_changes_all_the_same() {
        let (server, _log) = serve(|_| async { "401 Unauthorized" }).await;
        let state = SessionState::default();
        let renewals = Renewals::default();

        sign_in(&state, &server, "ops-admin").await;
        let result = send_renewing(
            &state,
            get,
            |url, refresh, _| refused(Arc::clone(&renewals), url, refresh),
            RENEWAL_DEADLINE,
        )
        .await;
        assert!(matches!(result, Err(AppError::SessionExpired)));
        assert!(state.current().await.is_none());

        sign_in(&state, &server, "ops-admin").await;
        assert!(state.current().await.is_some());
        assert!(state.take().await.is_some());
        assert!(state.current().await.is_none());
    }

    const RENEWED: &str = r#"{"access_token":"renewed","refresh_token":"refresh-2"}"#;

    /// Read one request: the head and as many body bytes as its `content-length` names.
    async fn read_request<S: tokio::io::AsyncRead + Unpin>(stream: &mut S) -> String {
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
            let n = stream.read(&mut buf).await.unwrap();
            if n == 0 {
                break;
            }
            request.extend_from_slice(&buf[..n]);
        }
        String::from_utf8_lossy(&request).into_owned()
    }

    /// Serve HTTPS with a self-signed certificate, the way a server of the standard install
    /// looks to a client that trusts only public roots: the refresh grants a new pair, a
    /// request with the renewed token gets 200, any other 401. The request line of every
    /// request that gets through the handshake lands in the log.
    async fn serve_self_signed() -> (String, Arc<StdMutex<Vec<String>>>) {
        use rcgen::{CertificateParams, KeyPair, PKCS_ECDSA_P256_SHA256};
        use rustls::pki_types::{PrivateKeyDer, PrivatePkcs8KeyDer};

        let key = KeyPair::generate_for(&PKCS_ECDSA_P256_SHA256).unwrap();
        let cert = CertificateParams::new(vec!["localhost".to_string()])
            .unwrap()
            .self_signed(&key)
            .unwrap();
        let key = PrivateKeyDer::Pkcs8(PrivatePkcs8KeyDer::from(key.serialize_der()));
        let config = rustls::ServerConfig::builder_with_provider(crate::tofu::ring_provider())
            .with_safe_default_protocol_versions()
            .unwrap()
            .with_no_client_auth()
            .with_single_cert(vec![cert.der().clone()], key)
            .unwrap();
        let acceptor = tokio_rustls::TlsAcceptor::from(Arc::new(config));
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!(
            "https://127.0.0.1:{}",
            listener.local_addr().unwrap().port()
        );
        // A pin an earlier test left for this port would decide instead of this server.
        crate::tofu::forget_pin(&url).unwrap();
        // The handshake runs on a tokio worker without a test keyring, where storing a
        // first-use pin fails and the connection is refused; so this server's certificate
        // is pinned up front. The tests check the session's choice of client, not pinning.
        crate::tofu::seed_cached_pin(&url, &crate::tofu::fingerprint(cert.der()));
        let log = Arc::new(StdMutex::new(Vec::new()));
        let seen = Arc::clone(&log);
        tokio::spawn(async move {
            loop {
                let (tcp, _) = listener.accept().await.unwrap();
                // A client that refuses the certificate ends the handshake here.
                let Ok(mut tls) = acceptor.accept(tcp).await else {
                    continue;
                };
                let request = read_request(&mut tls).await;
                let line = request.lines().next().unwrap_or_default().to_string();
                let (status, body) = if line.starts_with("POST /api/auth/refresh ") {
                    ("200 OK", RENEWED)
                } else if authorization(&request) == "Bearer renewed" {
                    ("200 OK", "")
                } else {
                    ("401 Unauthorized", "")
                };
                seen.lock().unwrap().push(line);
                let reply = format!(
                    "HTTP/1.1 {status}\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
                    body.len()
                );
                let _ = tls.write_all(reply.as_bytes()).await;
                let _ = tls.shutdown().await;
            }
        });
        (url, log)
    }

    /// A GET that accepts the test server's self-signed certificate, whatever the session
    /// chose. No first contact: `serve_self_signed` pins that certificate up front.
    fn get_allowing_self_signed(
        server_url: &str,
        _session_choice: bool,
    ) -> Result<reqwest::RequestBuilder, AppError> {
        let client = crate::http_client::build_client(server_url, true)?;
        Ok(client.get(format!("{server_url}/api/servers")))
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn without_self_signed_in_the_session_the_renewal_does_not_trust_on_first_use() {
        let (server, log) = serve_self_signed().await;
        let state = SessionState::default();
        state
            .set(
                server.clone(),
                "expired".to_string(),
                "refresh".to_string(),
                "ops-admin".to_string(),
                false,
            )
            .await;

        let result = tokio::time::timeout(
            Duration::from_secs(10),
            authed_send(&state, get_allowing_self_signed),
        )
        .await
        .expect("the renewal should have failed at the handshake");

        // The call reached the server through a client of its own choice; the renewal took
        // the session's, checks the public roots only and fails at the handshake, so the
        // refresh token is never sent.
        assert!(
            matches!(result, Err(AppError::SessionExpired)),
            "{:?}",
            result.map(|(response, _)| response.status())
        );
        assert_eq!(log_of(&log), ["GET /api/servers HTTP/1.1"]);
        assert!(state.current().await.is_none());
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn with_self_signed_in_the_session_the_renewal_trusts_the_pinned_certificate() {
        let (server, log) = serve_self_signed().await;
        let state = SessionState::default();
        state
            .set(
                server.clone(),
                "expired".to_string(),
                "refresh".to_string(),
                "ops-admin".to_string(),
                true,
            )
            .await;

        let (response, _) = tokio::time::timeout(
            Duration::from_secs(10),
            authed_send(&state, get_allowing_self_signed),
        )
        .await
        .expect("the renewal should have answered in time")
        .unwrap();

        // As before: the sign-in allowed it, so the renewal trusts the pinned certificate.
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            log_of(&log),
            [
                "GET /api/servers HTTP/1.1",
                "POST /api/auth/refresh HTTP/1.1",
                "GET /api/servers HTTP/1.1",
            ]
        );
        let now = state.current().await.unwrap();
        assert_eq!(
            (now.access.as_str(), now.refresh.as_str()),
            ("renewed", "refresh-2")
        );
    }
}
