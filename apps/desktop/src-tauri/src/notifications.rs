// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! Long-lived SSE client for the notification bell.
//!
//! The WebView cannot open an `EventSource` against the self-signed server, so
//! the stream is tunnelled through `reqwest` here — reusing `http_client::build_client`,
//! so it inherits the same mTLS / TOFU-pin / public-CA path and JWT bearer that
//! `api_proxy` uses. Each `notification` SSE frame is forwarded to the UI as a
//! `notification` Tauri event (the UI then reloads the feed), exactly like the
//! existing `frpc-terminated` event pattern.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use futures_util::StreamExt;
use tauri::Emitter;
use tokio::time::{sleep, timeout, Duration, Instant};

use crate::auth;
use crate::error::AppError;

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

pub async fn start(
    app: tauri::AppHandle,
    state: StreamState,
    server_url: String,
    token: String,
    allow_self_signed: bool,
) -> Result<(), AppError> {
    // Token-destination pin (same guard as api_proxy): never stream the JWT to a
    // server other than the one stored on login.
    crate::validation::require_pinned_destination(
        &server_url,
        "/api/notifications/stream",
        auth::stored_server_url().as_deref(),
    )?;
    let my_epoch = state.epoch.fetch_add(1, Ordering::SeqCst) + 1;
    tauri::async_runtime::spawn(async move {
        run_loop(app, state, my_epoch, server_url, token, allow_self_signed).await;
    });
    Ok(())
}

pub fn stop(state: &StreamState) {
    state.epoch.fetch_add(1, Ordering::SeqCst);
}

enum StreamEnd {
    Closed,
    Superseded,
    AuthFailed,
}

async fn run_loop(
    app: tauri::AppHandle,
    state: StreamState,
    my_epoch: u64,
    server_url: String,
    token: String,
    self_signed: bool,
) {
    let mut backoff = BASE_BACKOFF;
    while state.epoch.load(Ordering::SeqCst) == my_epoch {
        let connected_at = Instant::now();
        match connect_and_read(&app, &state, my_epoch, &server_url, &token, self_signed).await {
            Ok(StreamEnd::Superseded) => break,
            Ok(StreamEnd::Closed) => {
                // Only a connection that lived a while is "healthy" enough to reset the backoff; a
                // proxy that closes SSE instantly would otherwise never let the backoff grow and
                // trap the client in a 2 Hz reconnect loop (4.94).
                if connected_at.elapsed() > MIN_HEALTHY_UPTIME {
                    backoff = BASE_BACKOFF;
                }
            }
            Ok(StreamEnd::AuthFailed) => {
                // 401/403: token expired. Stop and let the UI fall back to
                // polling; a fresh login restarts the stream.
                let _ = app.emit("notification-stream-auth-failed", ());
                break;
            }
            Err(e) => log::warn!("[notif-stream] disconnected: {e}"),
        }
        if state.epoch.load(Ordering::SeqCst) != my_epoch {
            break;
        }
        sleep(backoff).await;
        backoff = (backoff * 2).min(MAX_BACKOFF);
    }
    log::info!("[notif-stream] task exited");
}

async fn connect_and_read(
    app: &tauri::AppHandle,
    state: &StreamState,
    my_epoch: u64,
    server_url: &str,
    token: &str,
    self_signed: bool,
) -> Result<StreamEnd, AppError> {
    let client = crate::http_client::build_client(server_url, self_signed)?;
    let url = format!(
        "{}/api/notifications/stream",
        server_url.trim_end_matches('/')
    );
    let resp = client
        .get(&url)
        .header("Authorization", format!("Bearer {token}"))
        .header("Accept", "text/event-stream")
        .send()
        .await?;

    let code = resp.status().as_u16();
    if code == 401 || code == 403 {
        return Ok(StreamEnd::AuthFailed);
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
                let _ = app.emit("notification", ());
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
