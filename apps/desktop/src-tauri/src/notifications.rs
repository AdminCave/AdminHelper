// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! Long-lived SSE client for the notification bell.
//!
//! The WebView cannot open an `EventSource` against the self-signed server, so
//! the stream is tunnelled through `reqwest` here — reusing `http_client::build_client`,
//! so it inherits the same mTLS / TOFU-pin / public-CA path as `api_proxy`, and like it
//! every connection goes through `session::authed_send`: the session's access token,
//! renewed once on a 401. Each `notification` SSE frame is forwarded to the UI as a
//! `notification` Tauri event (the UI then reloads the feed), exactly like the
//! existing `frpc-terminated` event pattern.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use futures_util::StreamExt;
use tauri::{Emitter, Manager};
use tokio::time::{sleep, timeout, Duration, Instant};

use crate::auth;
use crate::error::AppError;
use crate::session::{no_session, SessionState, SignedIn};

/// Managed state: an epoch counter. Each `start` bumps it and the spawned task
/// captures the value; the task runs only while its captured epoch is still the
/// current one. `stop` / re-login / server-switch just bump the epoch, which
/// makes every in-flight task observe the mismatch and exit at its next loop
/// boundary — race-free cancellation without an AbortHandle.
pub type StreamState = Arc<NotificationStream>;

#[derive(Default)]
pub struct NotificationStream {
    pub epoch: AtomicU64,
}

pub fn new_stream_state() -> StreamState {
    Arc::new(NotificationStream::default())
}

const BASE_BACKOFF: Duration = Duration::from_millis(500);
const MAX_BACKOFF: Duration = Duration::from_secs(30);
// The server heartbeats the SSE stream ~every 30 s, so no chunk for 90 s means the connection is
// dead (silent TCP drop) — read past this treats it as a disconnect and reconnects (4.95).
const IDLE_TIMEOUT: Duration = Duration::from_secs(90);
// A connection must live at least this long before a clean close is treated as healthy; else a
// proxy that closes SSE immediately traps the client in a fast reconnect loop (4.94).
const MIN_HEALTHY_UPTIME: Duration = Duration::from_secs(30);

/// Starts the stream for the session signed in now, on its server. Every connection takes
/// the token the session holds at that moment, so a renewal reaches the next one, and the
/// stream ends with the session ([`next_step`]). Without a session nothing starts.
pub async fn start(
    app: tauri::AppHandle,
    state: StreamState,
    session: &SessionState,
    allow_self_signed: bool,
) -> Result<(), AppError> {
    let now = session.current().await.ok_or_else(no_session)?;
    let who = SignedIn {
        server_url: now.server_url,
        username: now.username,
    };
    let my_epoch = state.epoch.fetch_add(1, Ordering::SeqCst) + 1;
    tauri::async_runtime::spawn(async move {
        run_loop(app, state, my_epoch, who, allow_self_signed).await;
    });
    Ok(())
}

pub fn stop(state: &StreamState) {
    state.epoch.fetch_add(1, Ordering::SeqCst);
}

#[derive(Debug)]
enum StreamEnd {
    Closed,
    Superseded,
    /// The server refuses the session: a 401 even after the renewal, or a 403.
    Refused,
}

/// What the stream does once a connection ended.
#[derive(Debug, PartialEq)]
enum Next {
    Reconnect,
    Stop,
}

/// Whether the stream connects again after `end`. `signed_in` tells whether the session it
/// was started for is still the one signed in. The stream ends with that session: after a
/// failed renewal (`authed_send` has announced it as `session-expired`), a sign-out or a
/// sign-in of someone else no connection asks for a token any more; a new sign-in starts a
/// stream of its own. It ends, too, when the server refuses the session even after a
/// renewal, or a newer `start`/`stop` took over; the bell keeps polling. A connection of
/// the session that closed or dropped comes back.
fn next_step(end: &Result<StreamEnd, AppError>, signed_in: bool) -> Next {
    let over = matches!(
        end,
        Ok(StreamEnd::Superseded | StreamEnd::Refused) | Err(AppError::SessionExpired)
    );
    if over || !signed_in {
        Next::Stop
    } else {
        Next::Reconnect
    }
}

async fn run_loop(
    app: tauri::AppHandle,
    state: StreamState,
    my_epoch: u64,
    who: SignedIn,
    self_signed: bool,
) {
    let session = app.state::<SessionState>();
    let mut backoff = BASE_BACKOFF;
    // Checked again right before each connection: a sign-in of someone else during the
    // backoff must not lend this stream the new session's token.
    while state.epoch.load(Ordering::SeqCst) == my_epoch
        && session.ensure_signed_in(&who).await.is_ok()
    {
        let connected_at = Instant::now();
        let end = connect_and_read(session.inner(), &state, my_epoch, self_signed, || {
            let _ = app.emit("notification", ());
        })
        .await;
        match &end {
            Ok(StreamEnd::Closed) => {
                // Only a connection that lived a while is "healthy" enough to reset the backoff; a
                // proxy that closes SSE instantly would otherwise never let the backoff grow and
                // trap the client in a 2 Hz reconnect loop (4.94).
                if connected_at.elapsed() > MIN_HEALTHY_UPTIME {
                    backoff = BASE_BACKOFF;
                }
            }
            Ok(StreamEnd::Superseded | StreamEnd::Refused) => {}
            Err(e) => log::warn!("[notif-stream] disconnected: {e}"),
        }
        let signed_in = session.ensure_signed_in(&who).await.is_ok();
        if next_step(&end, signed_in) == Next::Stop
            || state.epoch.load(Ordering::SeqCst) != my_epoch
        {
            break;
        }
        sleep(backoff).await;
        backoff = (backoff * 2).min(MAX_BACKOFF);
    }
    log::info!("[notif-stream] task exited");
}

/// The stream request on `server_url`, without a token: `authed_send` sets the session's
/// when the request goes out.
fn stream_request(
    server_url: &str,
    self_signed: bool,
) -> Result<reqwest::RequestBuilder, AppError> {
    let client = crate::http_client::build_client(server_url, self_signed)?;
    let url = format!(
        "{}/api/notifications/stream",
        server_url.trim_end_matches('/')
    );
    Ok(client.get(url).header("Accept", "text/event-stream"))
}

/// One connection of the stream, through [`crate::session::authed_send`]: the token the
/// session holds now, renewed once on a 401. It reads until the server closes, the
/// connection drops or a newer `start`/`stop` takes over; `notify` hears every frame that
/// asks the feed to reload.
async fn connect_and_read(
    session: &SessionState,
    state: &StreamState,
    my_epoch: u64,
    self_signed: bool,
    notify: impl Fn(),
) -> Result<StreamEnd, AppError> {
    let (resp, _) =
        crate::session::authed_send(
            session,
            |server_url| stream_request(server_url, self_signed),
            |server_url, refresh| async move {
                auth::try_refresh(&server_url, &refresh, self_signed).await
            },
        )
        .await?;

    let code = resp.status().as_u16();
    if code == 401 || code == 403 {
        log::warn!("[notif-stream] HTTP {code}: the server refuses the session, the stream stops");
        return Ok(StreamEnd::Refused);
    }
    if !resp.status().is_success() {
        return Err(AppError::Validation(format!("SSE HTTP {code}")));
    }

    let mut stream = resp.bytes_stream();
    let mut parser = SseParser::new();
    loop {
        // Idle-timeout the read: on a silent TCP drop (suspend/resume, wifi switch, NAT timeout)
        // no chunk ever arrives, so a plain stream.next().await would hang forever — the epoch
        // check below never runs, run_loop's reconnect never fires, and stop()/re-login can't
        // cancel the task. A read past IDLE_TIMEOUT is treated as a disconnect and reconnected (4.95).
        let chunk = match timeout(IDLE_TIMEOUT, stream.next()).await {
            Err(_) => return Err(AppError::Validation("SSE idle timeout".into())),
            Ok(None) => break,
            Ok(Some(c)) => c,
        };
        // Cooperative cancellation: drop the connection the moment a newer
        // start/stop/logout bumped the epoch.
        if state.epoch.load(Ordering::SeqCst) != my_epoch {
            return Ok(StreamEnd::Superseded);
        }
        let bytes = chunk.map_err(AppError::Network)?;
        for frame in parser.push(&bytes) {
            // A `notification` frame (or a bare default) means "reload the feed".
            // The payload is only a refresh nudge, so emit a bare event.
            if frame.event.as_deref() == Some("notification") || frame.event.is_none() {
                notify();
            }
        }
    }
    Ok(StreamEnd::Closed) // stream ended cleanly -> caller reconnects
}

// ── SSE frame parser ─────────────────────────────────────────────────────────

struct SseFrame {
    event: Option<String>,
    #[allow(dead_code)]
    data: String,
}

// Hard caps on the SSE parse buffers. A broken or hostile server sending an endless stream without
// a newline (or endless data: lines without a frame boundary) would otherwise grow buf/data
// unbounded (OOM) and rescan the whole buffer per chunk (quadratic). Frames here are only refresh
// nudges, so discarding a pathological one is lossless (5.10).
const MAX_SSE_BUF: usize = 64 * 1024;
const MAX_SSE_DATA_LINES: usize = 1024;

/// Parses SSE frames out of a rolling byte buffer. A frame is delimited by a
/// blank line; fields are `field: value` lines. A frame may arrive split across
/// several `bytes_stream` chunks, hence the buffer.
struct SseParser {
    buf: Vec<u8>,
    event: Option<String>,
    data: Vec<String>,
}

impl SseParser {
    fn new() -> Self {
        Self {
            buf: Vec::new(),
            event: None,
            data: Vec::new(),
        }
    }

    fn push(&mut self, bytes: &[u8]) -> Vec<SseFrame> {
        self.buf.extend_from_slice(bytes);
        if self.buf.len() > MAX_SSE_BUF {
            // An endless stream without a newline — discard rather than grow/rescan unbounded.
            self.buf.clear();
            self.event = None;
            self.data.clear();
        }
        let mut frames = Vec::new();
        while let Some(pos) = self.buf.iter().position(|&b| b == b'\n') {
            let raw: Vec<u8> = self.buf.drain(..=pos).collect();
            let line = String::from_utf8_lossy(&raw);
            let line = line.trim_end_matches(['\r', '\n']);

            if line.is_empty() {
                // Frame boundary.
                if !self.data.is_empty() {
                    frames.push(SseFrame {
                        event: self.event.take(),
                        data: self.data.join("\n"),
                    });
                }
                self.event = None;
                self.data.clear();
            } else if line.starts_with(':') {
                // Comment / heartbeat — ignore, it just keeps the stream open.
            } else if let Some(v) = line.strip_prefix("event:") {
                self.event = Some(v.trim().to_string());
            } else if let Some(v) = line.strip_prefix("data:") {
                // Per spec, one leading space after the colon is stripped.
                self.data.push(v.strip_prefix(' ').unwrap_or(v).to_string());
                if self.data.len() > MAX_SSE_DATA_LINES {
                    // Endless data: lines without a frame boundary — discard the pathological frame.
                    self.event = None;
                    self.data.clear();
                }
            }
            // `id:` / `retry:` are not needed for the coarse refresh model.
        }
        frames
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicUsize;
    use std::sync::Mutex;

    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    const RENEWED: &str = r#"{"access_token":"renewed","refresh_token":"refresh-2"}"#;
    const STREAM: &str = "GET /api/notifications/stream HTTP/1.1";
    const REFRESH: &str = "POST /api/auth/refresh HTTP/1.1";
    const FRAME: &str = "event: notification\ndata: {}\n\n";

    fn reply(status: &str, body: &str) -> String {
        format!(
            "HTTP/1.1 {status}\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
            body.len()
        )
    }

    /// Read one request: the head and as many body bytes as its `content-length` names.
    async fn read_request(tcp: &mut tokio::net::TcpStream) -> String {
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
            let n = tcp.read(&mut buf).await.unwrap();
            if n == 0 {
                break;
            }
            request.extend_from_slice(&buf[..n]);
        }
        String::from_utf8_lossy(&request).into_owned()
    }

    /// Serve HTTP on a fresh loopback port, one request per connection: every request lands
    /// in the log, then `answer` returns the whole response to it.
    async fn serve(
        mut answer: impl FnMut(&str) -> String + Send + 'static,
    ) -> (String, Arc<Mutex<Vec<String>>>) {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://127.0.0.1:{}", listener.local_addr().unwrap().port());
        let log = Arc::new(Mutex::new(Vec::new()));
        let seen = Arc::clone(&log);
        tokio::spawn(async move {
            loop {
                let (mut tcp, _) = listener.accept().await.unwrap();
                let request = read_request(&mut tcp).await;
                seen.lock().unwrap().push(request.clone());
                tcp.write_all(answer(&request).as_bytes()).await.unwrap();
                let _ = tcp.shutdown().await;
            }
        });
        (url, log)
    }

    /// The request lines in the order the requests arrived.
    fn request_lines(log: &Mutex<Vec<String>>) -> Vec<String> {
        let log = log.lock().unwrap();
        log.iter()
            .map(|request| request.lines().next().unwrap_or_default().to_string())
            .collect()
    }

    /// The Authorization header of a request, if it has one.
    fn authorization(request: &str) -> Option<&str> {
        request.lines().find_map(|line| {
            let (name, value) = line.split_once(':')?;
            name.eq_ignore_ascii_case("authorization")
                .then_some(value.trim())
        })
    }

    /// The Authorization headers in the order the requests arrived.
    fn tokens(log: &Mutex<Vec<String>>) -> Vec<Option<String>> {
        let log = log.lock().unwrap();
        log.iter()
            .map(|request| authorization(request).map(str::to_string))
            .collect()
    }

    /// `ops-admin` signed in on `server_url` with an access token the server no longer takes.
    async fn signed_in(server_url: &str) -> SessionState {
        let session = SessionState::default();
        session
            .set(
                server_url.to_string(),
                "expired".to_string(),
                "refresh".to_string(),
                "ops-admin".to_string(),
            )
            .await;
        session
    }

    /// Counts how often `session` announces that it ended.
    fn expiries(session: &SessionState) -> Arc<AtomicUsize> {
        let count = Arc::new(AtomicUsize::new(0));
        let heard = Arc::clone(&count);
        session.on_expiry(move || {
            heard.fetch_add(1, Ordering::Relaxed);
        });
        count
    }

    /// One connection of the stream, counting the frames it hands on.
    async fn connect_once(
        session: &SessionState,
        frames: &AtomicUsize,
    ) -> Result<StreamEnd, AppError> {
        let stream = new_stream_state();
        connect_and_read(session, &stream, 0, false, || {
            frames.fetch_add(1, Ordering::Relaxed);
        })
        .await
    }

    #[test]
    fn the_stream_request_asks_for_events_and_carries_no_token_of_its_own() {
        let request = stream_request("https://adminhelper.example:8443/", false)
            .unwrap()
            .build()
            .unwrap();

        assert_eq!(request.method(), reqwest::Method::GET);
        assert_eq!(
            request.url().as_str(),
            "https://adminhelper.example:8443/api/notifications/stream"
        );
        assert_eq!(request.headers()["accept"], "text/event-stream");
        // The token is the session's, set by authed_send when the request goes out.
        assert!(request.headers().get("authorization").is_none());
    }

    #[tokio::test]
    async fn after_a_renewal_the_stream_connects_with_the_new_token() {
        let (server, log) = serve(|request| {
            if request.starts_with(REFRESH) {
                reply("200 OK", RENEWED)
            } else if authorization(request) == Some("Bearer renewed") {
                reply("200 OK", FRAME)
            } else {
                reply("401 Unauthorized", "")
            }
        })
        .await;
        let session = signed_in(&server).await;
        let expired = expiries(&session);
        let frames = AtomicUsize::new(0);

        // The token of the sign-in has expired: the first connection renews it, and the one
        // after the stream dropped takes the new token from the session.
        let first = connect_once(&session, &frames).await;
        let second = connect_once(&session, &frames).await;

        assert!(matches!(first, Ok(StreamEnd::Closed)), "{first:?}");
        assert!(matches!(second, Ok(StreamEnd::Closed)), "{second:?}");
        assert_eq!(frames.load(Ordering::Relaxed), 2);
        assert_eq!(request_lines(&log), [STREAM, REFRESH, STREAM, STREAM]);
        assert_eq!(
            tokens(&log),
            [
                Some("Bearer expired".to_string()),
                None,
                Some("Bearer renewed".to_string()),
                Some("Bearer renewed".to_string()),
            ]
        );
        assert_eq!(session.current().await.unwrap().access, "renewed");
        assert_eq!(expired.load(Ordering::Relaxed), 0);
    }

    #[tokio::test]
    async fn a_refused_renewal_ends_the_session_and_the_stream() {
        let (server, log) = serve(|_| reply("401 Unauthorized", "")).await;
        let session = signed_in(&server).await;
        let expired = expiries(&session);
        let frames = AtomicUsize::new(0);

        let end = connect_once(&session, &frames).await;

        assert!(matches!(end, Err(AppError::SessionExpired)), "{end:?}");
        // The webview hears it the way every other request tells it (`session-expired`).
        assert_eq!(expired.load(Ordering::Relaxed), 1);
        assert!(session.current().await.is_none());
        assert_eq!(next_step(&end, false), Next::Stop);
        // No retry without a token.
        assert_eq!(request_lines(&log), [STREAM, REFRESH]);
    }

    #[tokio::test]
    async fn a_401_after_the_renewal_stops_the_stream_and_keeps_the_session() {
        let (server, log) = serve(|request| {
            if request.starts_with(REFRESH) {
                reply("200 OK", RENEWED)
            } else {
                reply("401 Unauthorized", "")
            }
        })
        .await;
        let session = signed_in(&server).await;
        let expired = expiries(&session);
        let frames = AtomicUsize::new(0);

        let end = connect_once(&session, &frames).await;

        assert!(matches!(end, Ok(StreamEnd::Refused)), "{end:?}");
        assert_eq!(next_step(&end, true), Next::Stop);
        assert_eq!(request_lines(&log), [STREAM, REFRESH, STREAM]);
        assert_eq!(session.current().await.unwrap().access, "renewed");
        assert_eq!(expired.load(Ordering::Relaxed), 0);
    }

    #[tokio::test]
    async fn after_a_sign_out_the_stream_sends_no_token() {
        let (server, log) = serve(|_| reply("200 OK", FRAME)).await;
        let session = signed_in(&server).await;
        let expired = expiries(&session);
        let frames = AtomicUsize::new(0);
        let before = connect_once(&session, &frames).await;
        assert!(matches!(before, Ok(StreamEnd::Closed)), "{before:?}");

        // A sign-out takes the session first (`auth::logout`).
        session.take().await;
        let after = connect_once(&session, &frames).await;

        let message = after.as_ref().err().map(|e| e.to_string());
        assert_eq!(
            message.as_deref(),
            Some("Keine aktive Sitzung — Anfrage abgelehnt")
        );
        assert_eq!(next_step(&after, false), Next::Stop);
        assert_eq!(request_lines(&log), [STREAM]);
        // A sign-out is no expiry.
        assert_eq!(expired.load(Ordering::Relaxed), 0);
    }

    #[test]
    fn the_stream_comes_back_after_a_drop_and_ends_with_its_session() {
        let dropped = || Err(AppError::Validation("SSE idle timeout".into()));

        // A connection of the session still signed in that closed or dropped comes back.
        assert_eq!(next_step(&Ok(StreamEnd::Closed), true), Next::Reconnect);
        assert_eq!(next_step(&dropped(), true), Next::Reconnect);
        // The session is over: the renewal failed (announced by authed_send), the user signed
        // out, or someone else signed in.
        assert_eq!(next_step(&Err(AppError::SessionExpired), false), Next::Stop);
        assert_eq!(next_step(&Err(AppError::SessionExpired), true), Next::Stop);
        assert_eq!(next_step(&Ok(StreamEnd::Closed), false), Next::Stop);
        assert_eq!(next_step(&dropped(), false), Next::Stop);
        // The server refuses the session even after a renewal, or a newer start took over.
        assert_eq!(next_step(&Ok(StreamEnd::Refused), true), Next::Stop);
        assert_eq!(next_step(&Ok(StreamEnd::Superseded), true), Next::Stop);
    }

    #[test]
    fn parses_a_simple_frame() {
        let mut p = SseParser::new();
        let frames = p.push(b"event: notification\ndata: {\"type\":\"refresh\"}\n\n");
        assert_eq!(frames.len(), 1);
        assert_eq!(frames[0].event.as_deref(), Some("notification"));
        assert_eq!(frames[0].data, "{\"type\":\"refresh\"}");
    }

    #[test]
    fn reassembles_a_frame_split_across_chunks() {
        let mut p = SseParser::new();
        assert!(p.push(b"event: notif").is_empty());
        assert!(p.push(b"ication\ndata: x").is_empty());
        let frames = p.push(b"\n\n");
        assert_eq!(frames.len(), 1);
        assert_eq!(frames[0].event.as_deref(), Some("notification"));
        assert_eq!(frames[0].data, "x");
    }

    #[test]
    fn ignores_comment_heartbeats() {
        let mut p = SseParser::new();
        assert!(p.push(b": ping\n\n").is_empty());
        assert!(p.push(b": connected\n\n").is_empty());
    }

    #[test]
    fn handles_multiple_frames_in_one_chunk() {
        let mut p = SseParser::new();
        let frames = p.push(b"event: notification\ndata: a\n\nevent: notification\ndata: b\n\n");
        assert_eq!(frames.len(), 2);
        assert_eq!(frames[0].data, "a");
        assert_eq!(frames[1].data, "b");
    }

    #[test]
    fn multi_line_data_is_joined() {
        let mut p = SseParser::new();
        let frames = p.push(b"data: line1\ndata: line2\n\n");
        assert_eq!(frames.len(), 1);
        assert_eq!(frames[0].data, "line1\nline2");
    }

    #[test]
    fn caps_a_newline_less_flood() {
        // 5.10: an endless stream without a newline is discarded, not grown/rescanned unbounded.
        let mut p = SseParser::new();
        let frames = p.push(&vec![b'x'; MAX_SSE_BUF + 100]);
        assert!(frames.is_empty());
        assert_eq!(p.buf.len(), 0, "over-cap buffer should be cleared");
    }

    #[test]
    fn caps_endless_data_lines_without_a_frame_boundary() {
        // 5.10: endless data: lines that never hit a blank-line boundary are discarded.
        let mut input = String::new();
        for _ in 0..(MAX_SSE_DATA_LINES + 10) {
            input.push_str("data: x\n");
        }
        let mut p = SseParser::new();
        let frames = p.push(input.as_bytes());
        assert!(frames.is_empty(), "no frame boundary -> no frame");
        assert!(
            p.data.len() <= MAX_SSE_DATA_LINES,
            "data lines should be capped, got {}",
            p.data.len()
        );
    }
}
