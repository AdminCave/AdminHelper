// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! The local WebSocket that carries the desktop picture to the webview and its input back
//! (docs/features/arch-rdp-backend.md, "WebSocket-Protokoll").
//!
//! One server per session, on 127.0.0.1 with a port the system picks, listening as long as the
//! session lives. A client logs in with the session's token as its first text message; a login
//! uses the token up, and `Tokens::renew` hands out the next one (R-1101). Each token belongs to a
//! screen: screen 0 shows the desktop, or its first monitor once the webview asked for two
//! (`{"t":"layout",…}`), screen 1 the second monitor. One client streams per screen: a new login
//! takes over from the one before on its screen and gets its whole picture first, and a client
//! that goes away leaves the session running, for 60 s while no screen has a client. Pictures go out one at a time, the next
//! after the client's `{"t":"ack"}`; whatever changes in between is merged into one enclosing
//! rectangle, so no backlog builds up behind a slow webview. Once a second, while there is a
//! picture, a text message `{"t":"stats",…}` tells how many pictures went out and what the
//! server measured.

use std::io;
use std::net::Ipv4Addr;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use std::task::Poll;

use futures_util::{SinkExt, StreamExt};
use ironrdp_client::rdp::DesktopUpdate;
use serde::{Deserialize, Serialize};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::{mpsc, Notify};
use tokio::task::{JoinError, JoinSet};
use tokio::time::{interval_at, timeout, Instant, MissedTickBehavior};
use tokio_tungstenite::tungstenite::protocol::WebSocketConfig;
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::{accept_async_with_config, WebSocketStream};

use super::session::{Display, Layout};

const TOKEN_BYTES: usize = 32;
const LOGIN_DEADLINE: Duration = Duration::from_secs(5);
/// Logins that run side by side. Each ends at the deadline, so a local process that opens
/// connections and stays silent holds back the webview's login by one deadline at most.
const MAX_PENDING_LOGINS: usize = 8;
const ACCEPT_BACKOFF: Duration = Duration::from_millis(50);
/// The client sends the token and small JSON messages; anything larger is not ours.
const MAX_CLIENT_MESSAGE: usize = 4096;
const FRAME_VERSION: u16 = 1;
/// Version, x, y, width, height, desktop width, desktop height: seven u16, little-endian.
const HEADER_LEN: usize = 14;
const STATS_EVERY: Duration = Duration::from_secs(1);
/// How long a session lives on while no client streams any screen. A view that goes away without
/// stopping its session (a reload, a lost window) must not leave it logged in where nothing shows
/// it; a docked-out window hands over within seconds.
const NO_CLIENT_DEADLINE: Duration = Duration::from_secs(60);
/// The desktop as one picture, or its two monitors as two (R-1101).
pub(crate) const SCREENS: usize = 2;

/// What the webview sends besides the receipt, for the session to pass on to the server.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Input {
    /// A keyboard scancode; `extended` is the E0 prefix.
    Key {
        code: u8,
        extended: bool,
        down: bool,
    },
    /// The pointer in desktop coordinates, the pressed buttons as a bit mask and a wheel step.
    Mouse {
        x: u16,
        y: u16,
        buttons: u8,
        wheel: i16,
    },
    /// Ctrl+Alt+Del, which the webview cannot send as keys: the local system takes it first.
    CtrlAltDel,
    /// The desktop the webview wants, already within the limits of MS-RDPEDISP.
    Size(Display),
    /// Two monitors instead of one desktop, already placed edge to edge.
    Layout(Layout),
    Close,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "t", rename_all = "lowercase")]
enum ClientMessage {
    Ack,
    Key {
        code: u8,
        ext: bool,
        down: bool,
    },
    Mouse {
        x: u16,
        y: u16,
        buttons: u8,
        wheel: i16,
    },
    Cad,
    Size {
        w: u16,
        h: u16,
        scale: u32,
    },
    Layout {
        monitors: Vec<Monitor>,
    },
    Close,
}

/// One monitor of a `layout` message: where the webview sees it, its size and scale.
#[derive(Debug, Deserialize)]
struct Monitor {
    x: i32,
    y: i32,
    w: u16,
    h: u16,
    scale: u32,
}

/// The `stats` message: pictures per second sent to the webview, the desktop size and, when the
/// server measured them, its bandwidth and round-trip time.
#[derive(Debug, Serialize)]
#[serde(tag = "t", rename = "stats")]
struct Stats {
    fps: f64,
    width: u16,
    height: u16,
    #[serde(skip_serializing_if = "Option::is_none")]
    mbps: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    rtt_ms: Option<u32>,
}

/// The token that logs the next client of each screen in. A login uses it up; until `renew` hands
/// out the next one, no further client of that screen gets in. Screen 1 has none until the first
/// `renew`.
#[derive(Clone)]
pub(crate) struct Tokens(Arc<Mutex<[Option<String>; SCREENS]>>);

impl Tokens {
    fn new() -> io::Result<Self> {
        Ok(Self(Arc::new(Mutex::new([Some(fresh_token()?), None]))))
    }

    fn slots(&self) -> std::sync::MutexGuard<'_, [Option<String>; SCREENS]> {
        self.0.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// A fresh token for the next login on `screen`; the one before, used or not, logs in no more.
    pub(crate) fn renew(&self, screen: usize) -> io::Result<String> {
        let token = fresh_token()?;
        let mut slots = self.slots();
        let slot = slots
            .get_mut(screen)
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "no such screen"))?;
        *slot = Some(token.clone());
        Ok(token)
    }

    /// The screen whose token `presented` is; a match uses it up, so of logins that race with the
    /// same token only one gets in. Every slot is compared, in time independent of which matches.
    fn redeem(&self, presented: &[u8]) -> Option<usize> {
        let mut slots = self.slots();
        let mut screen = None;
        for (index, slot) in slots.iter().enumerate() {
            if slot
                .as_deref()
                .is_some_and(|token| same_token(token.as_bytes(), presented))
            {
                screen = Some(index);
            }
        }
        if let Some(index) = screen {
            slots[index] = None;
        }
        screen
    }
}

fn fresh_token() -> io::Result<String> {
    let mut bytes = [0u8; TOKEN_BYTES];
    crate::tofu::ring_provider()
        .secure_random
        .fill(&mut bytes)
        .map_err(|_| io::Error::other("no random bytes for the frame token"))?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

pub(crate) struct FrameServer {
    listener: std::net::TcpListener,
    tokens: Tokens,
    login_deadline: Duration,
    no_client_deadline: Duration,
    stats_every: Duration,
}

impl FrameServer {
    /// Binds before the session starts, so port and token can go to the webview right away.
    pub(crate) fn bind() -> io::Result<Self> {
        let listener = std::net::TcpListener::bind((Ipv4Addr::LOCALHOST, 0))?;
        listener.set_nonblocking(true)?;
        Ok(Self {
            listener,
            tokens: Tokens::new()?,
            login_deadline: LOGIN_DEADLINE,
            no_client_deadline: NO_CLIENT_DEADLINE,
            stats_every: STATS_EVERY,
        })
    }

    pub(crate) fn port(&self) -> io::Result<u16> {
        Ok(self.listener.local_addr()?.port())
    }

    /// The token of the first login, on screen 0.
    pub(crate) fn token(&self) -> String {
        self.tokens.slots()[0].clone().unwrap_or_default()
    }

    /// Where the tokens of later logins come from.
    pub(crate) fn tokens(&self) -> Tokens {
        self.tokens.clone()
    }

    /// Streams `frames` to the client of each screen that logged in last and passes its input on,
    /// until a client sends `close`, no client streams for `no_client_deadline` or the session
    /// takes no more input. Must run inside a tokio runtime.
    pub(crate) async fn serve(self, frames: Frames, input: mpsc::Sender<Input>) -> io::Result<()> {
        let listener = TcpListener::from_std(self.listener)?;
        // A wrong token, or none in time, closes only that connection, and logins do not wait for
        // each other: a local process that connects first must not lock the webview out.
        let mut pending = JoinSet::new();
        // At most one per screen: the client that streams it.
        let mut clients: [JoinSet<Ended>; SCREENS] = Default::default();
        let mut alone_until = None;
        loop {
            if clients.iter().all(JoinSet::is_empty) {
                alone_until.get_or_insert_with(|| Instant::now() + self.no_client_deadline);
            } else {
                alone_until = None;
            }
            tokio::select! {
                accepted = listener.accept(), if pending.len() < MAX_PENDING_LOGINS => {
                    // The listener lives as long as the session: a connection reset before
                    // the accept or a full file table must not end it, so it keeps listening
                    // and backs off a moment, since a full table fails again at once.
                    let tcp = match accepted {
                        Ok((tcp, _)) => tcp,
                        Err(error) => {
                            log::debug!("the RDP frame socket missed a connection: {error}");
                            tokio::time::sleep(ACCEPT_BACKOFF).await;
                            continue;
                        }
                    };
                    let (tokens, deadline) = (self.tokens.clone(), self.login_deadline);
                    pending.spawn(async move { timeout(deadline, login(tcp, &tokens)).await });
                }
                Some(done) = pending.join_next() => {
                    if let Ok(Ok(Some((ws, screen)))) = done {
                        // The client before is gone before the whole picture is due, so it
                        // cannot take that picture from the new one.
                        clients[screen].shutdown().await;
                        frames.refresh(screen);
                        let (frames, input) = (frames.clone(), input.clone());
                        clients[screen].spawn(stream(ws, screen, frames, input, self.stats_every));
                    }
                }
                done = ended(&mut clients) => {
                    if matches!(done, Ok(Ended::Close)) || input.is_closed() {
                        return Ok(());
                    }
                }
                () = tokio::time::sleep_until(alone_until.unwrap_or_else(Instant::now)),
                    if alone_until.is_some() => return Ok(()),
            }
        }
    }
}

/// The end of the next client stream, of whichever screen; pending while none streams (a login
/// that spawns one comes through another branch of `serve`, which polls again).
async fn ended(clients: &mut [JoinSet<Ended>; SCREENS]) -> Result<Ended, JoinError> {
    std::future::poll_fn(|cx| {
        for client in clients.iter_mut() {
            if let Poll::Ready(Some(done)) = client.poll_join_next(cx) {
                return Poll::Ready(done);
            }
        }
        Poll::Pending
    })
    .await
}

/// How a client's stream ended.
#[derive(Debug, PartialEq, Eq)]
enum Ended {
    /// The client sent `close`, which ends the session.
    Close,
    /// The client went away, or the session took no more input.
    Gone,
}

/// The client and the screen its token belongs to.
async fn login(tcp: TcpStream, tokens: &Tokens) -> Option<(WebSocketStream<TcpStream>, usize)> {
    let limits = WebSocketConfig::default()
        .max_message_size(Some(MAX_CLIENT_MESSAGE))
        .max_frame_size(Some(MAX_CLIENT_MESSAGE));
    let mut ws = accept_async_with_config(tcp, Some(limits)).await.ok()?;
    let screen = match ws.next().await {
        Some(Ok(Message::Text(text))) => tokens.redeem(text.as_bytes()),
        _ => None,
    };
    match screen {
        Some(screen) => Some((ws, screen)),
        None => {
            let _ = ws.close(None).await;
            None
        }
    }
}

/// Compares in time independent of where the first difference is.
fn same_token(expected: &[u8], presented: &[u8]) -> bool {
    if expected.len() != presented.len() {
        return false;
    }
    let difference = expected
        .iter()
        .zip(presented)
        .fold(0u8, |acc, (a, b)| acc | (a ^ b));
    std::hint::black_box(difference) == 0
}

async fn stream(
    mut ws: WebSocketStream<TcpStream>,
    screen: usize,
    frames: Frames,
    input: mpsc::Sender<Input>,
    stats_every: Duration,
) -> Ended {
    // The first picture needs no receipt; every further one waits for the client's ack.
    let mut acked = true;
    let mut since = Instant::now();
    let mut stats = interval_at(since + stats_every, stats_every);
    stats.set_missed_tick_behavior(MissedTickBehavior::Delay);
    loop {
        tokio::select! {
            () = frames.changed(screen), if acked => {
                if let Some(frame) = frames.take_frame(screen) {
                    if ws.send(Message::binary(frame)).await.is_err() {
                        return Ended::Gone;
                    }
                    frames.sent(screen);
                    acked = false;
                }
            }
            now = stats.tick() => {
                let elapsed = now.duration_since(since);
                since = now;
                if let Some(text) = frames.take_stats(screen, elapsed) {
                    if ws.send(Message::text(text)).await.is_err() {
                        return Ended::Gone;
                    }
                }
            }
            message = ws.next() => {
                let text = match message {
                    Some(Ok(Message::Text(text))) => text,
                    Some(Ok(Message::Close(_)) | Err(_)) | None => return Ended::Gone,
                    Some(Ok(_)) => continue,
                };
                let event = match serde_json::from_str::<ClientMessage>(&text) {
                    Ok(ClientMessage::Ack) => {
                        acked = true;
                        continue;
                    }
                    Ok(ClientMessage::Key { code, ext, down }) => Input::Key {
                        code,
                        extended: ext,
                        down,
                    },
                    Ok(ClientMessage::Mouse { x, y, buttons, wheel }) => {
                        // The client's picture starts where its monitor lies in the desktop.
                        let (left, top) = frames.origin(screen);
                        Input::Mouse {
                            x: x.saturating_add(left),
                            y: y.saturating_add(top),
                            buttons,
                            wheel,
                        }
                    }
                    Ok(ClientMessage::Cad) => Input::CtrlAltDel,
                    Ok(ClientMessage::Size { w, h, scale }) => {
                        Input::Size(Display::clamped(w, h, scale))
                    }
                    Ok(ClientMessage::Layout { monitors }) => match monitors.as_slice() {
                        [first, second] => Input::Layout(Layout::placed(
                            Display::clamped(first.w, first.h, first.scale),
                            Display::clamped(second.w, second.h, second.scale),
                            second.x.saturating_sub(first.x),
                            second.y.saturating_sub(first.y),
                        )),
                        _ => continue,
                    },
                    Ok(ClientMessage::Close) => Input::Close,
                    // Unknown or malformed: dropped, the session goes on.
                    Err(_) => continue,
                };
                if input.send(event).await.is_err() {
                    return Ended::Gone;
                }
                if event == Input::Close {
                    return Ended::Close;
                }
            }
        }
    }
}

/// The desktop picture, shared between the session (which applies IronRDP's updates) and the
/// WebSocket (which sends what changed to the client of each screen).
#[derive(Clone, Default)]
pub(crate) struct Frames(Arc<Shared>);

#[derive(Default)]
struct Shared {
    buffer: Mutex<Framebuffer>,
    /// One per screen: a `notify_one` keeps its permit for the stream of that screen only.
    changed: [Notify; SCREENS],
    counters: Mutex<Counters>,
}

/// What the next `stats` message of each screen reports.
#[derive(Default)]
struct Counters {
    /// Pictures sent since the last `stats` message, per screen.
    sent: [u32; SCREENS],
    rtt_ms: Option<u32>,
    bandwidth_kbps: Option<u32>,
}

fn one_decimal(value: f64) -> f64 {
    (value * 10.0).round() / 10.0
}

#[derive(Default)]
struct Framebuffer {
    width: u16,
    height: u16,
    /// `0x00RRGGBB`, row by row, as IronRDP delivers them.
    pixels: Vec<u32>,
    /// Where each screen's monitor lies in the desktop; `None` shows the whole desktop on
    /// screen 0 and nothing on screen 1.
    layout: Option<[Viewport; SCREENS]>,
    /// What changed on each screen since its last picture went out, in desktop coordinates.
    dirty: [Option<Rect>; SCREENS],
}

/// A monitor's place in the desktop picture, which starts at the top left corner of all monitors.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct Viewport {
    pub(crate) x: u16,
    pub(crate) y: u16,
    pub(crate) width: u16,
    pub(crate) height: u16,
}

/// Inclusive coordinates, like IronRDP's regions.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Rect {
    left: u16,
    top: u16,
    right: u16,
    bottom: u16,
}

impl Rect {
    fn union(self, other: Rect) -> Rect {
        Rect {
            left: self.left.min(other.left),
            top: self.top.min(other.top),
            right: self.right.max(other.right),
            bottom: self.bottom.max(other.bottom),
        }
    }

    fn intersection(self, other: Rect) -> Option<Rect> {
        let rect = Rect {
            left: self.left.max(other.left),
            top: self.top.max(other.top),
            right: self.right.min(other.right),
            bottom: self.bottom.min(other.bottom),
        };
        (rect.left <= rect.right && rect.top <= rect.bottom).then_some(rect)
    }

    fn width(self) -> u16 {
        self.right - self.left + 1
    }

    fn height(self) -> u16 {
        self.bottom - self.top + 1
    }
}

impl Frames {
    fn buffer(&self) -> std::sync::MutexGuard<'_, Framebuffer> {
        self.0.buffer.lock().unwrap_or_else(|e| e.into_inner())
    }

    fn notify_all(&self) {
        for changed in &self.0.changed {
            changed.notify_one();
        }
    }

    pub(crate) fn apply(&self, update: DesktopUpdate) {
        self.buffer().apply(update);
        self.notify_all();
    }

    /// Shows the desktop's monitors on a screen each, or with `None` the whole desktop on screen
    /// 0 again. A layout that differs from the one before sends every screen its whole picture.
    pub(crate) fn set_layout(&self, layout: Option<[Viewport; SCREENS]>) {
        if self.buffer().set_layout(layout) {
            self.notify_all();
        }
    }

    fn has_changes(&self, screen: usize) -> bool {
        self.buffer().dirty[screen].is_some()
    }

    /// The next picture of `screen` covers all of it, for a client that has none of it yet.
    fn refresh(&self, screen: usize) {
        self.buffer().refresh(screen);
        self.0.changed[screen].notify_one();
    }

    /// Returns once there is something to send on `screen`. A notification without a change
    /// (its picture already went out) waits on.
    async fn changed(&self, screen: usize) {
        while !self.has_changes(screen) {
            self.0.changed[screen].notified().await;
        }
    }

    fn take_frame(&self, screen: usize) -> Option<Vec<u8>> {
        self.buffer().take_frame(screen)
    }

    /// Where the picture of `screen` starts in the desktop.
    pub(crate) fn origin(&self, screen: usize) -> (u16, u16) {
        self.buffer()
            .visible(screen)
            .map_or((0, 0), |visible| (visible.left, visible.top))
    }

    fn counters(&self) -> std::sync::MutexGuard<'_, Counters> {
        self.0.counters.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// What the server last measured of the connection; `None` for a connection that has not
    /// measured yet, so a new connection does not show the values of the one before.
    pub(crate) fn network(&self, rtt_ms: Option<u32>, bandwidth_kbps: Option<u32>) {
        let mut counters = self.counters();
        counters.rtt_ms = rtt_ms;
        counters.bandwidth_kbps = bandwidth_kbps;
    }

    fn sent(&self, screen: usize) {
        let mut counters = self.counters();
        counters.sent[screen] = counters.sent[screen].saturating_add(1);
    }

    /// The `stats` message of `screen` for the `elapsed` time since its last one, which starts
    /// the count again; none while the screen shows no picture.
    pub(crate) fn take_stats(&self, screen: usize, elapsed: Duration) -> Option<String> {
        let visible = self.buffer().visible(screen);
        let mut counters = self.counters();
        let sent = std::mem::take(&mut counters.sent[screen]);
        let visible = visible.filter(|_| !elapsed.is_zero())?;
        let stats = Stats {
            fps: one_decimal(f64::from(sent) / elapsed.as_secs_f64()),
            width: visible.width(),
            height: visible.height(),
            mbps: counters
                .bandwidth_kbps
                .map(|kbps| one_decimal(f64::from(kbps) / 1000.0)),
            rtt_ms: counters.rtt_ms,
        };
        serde_json::to_string(&stats).ok()
    }

    /// The whole desktop as a PNG; an error while there is no picture yet.
    pub(crate) fn png(&self) -> Result<Vec<u8>, String> {
        // Copied first: encoding takes longer than an update should wait for the lock.
        let (width, height, rgb) = {
            let buffer = self.buffer();
            let rgb: Vec<u8> = buffer
                .pixels
                .iter()
                .flat_map(|pixel| {
                    let [_, red, green, blue] = pixel.to_be_bytes();
                    [red, green, blue]
                })
                .collect();
            (buffer.width, buffer.height, rgb)
        };
        if width == 0 {
            return Err("the session shows no picture yet".into());
        }
        let mut png = Vec::new();
        let mut encoder = png::Encoder::new(&mut png, u32::from(width), u32::from(height));
        encoder.set_color(png::ColorType::Rgb);
        encoder.set_depth(png::BitDepth::Eight);
        let mut writer = encoder.write_header().map_err(|e| e.to_string())?;
        writer.write_image_data(&rgb).map_err(|e| e.to_string())?;
        writer.finish().map_err(|e| e.to_string())?;
        Ok(png)
    }
}

impl Framebuffer {
    /// The part of the desktop `screen` shows: its monitor as far as the desktop reaches, which
    /// until the server took a new layout may be less than the monitor or nothing.
    fn visible(&self, screen: usize) -> Option<Rect> {
        if self.width == 0 {
            return None;
        }
        let desktop = Rect {
            left: 0,
            top: 0,
            right: self.width - 1,
            bottom: self.height - 1,
        };
        let Some(layout) = self.layout else {
            return (screen == 0).then_some(desktop);
        };
        let viewport = layout[screen];
        let corner = |start: u16, length: u16| start.saturating_add(length.max(1) - 1);
        Rect {
            left: viewport.x,
            top: viewport.y,
            right: corner(viewport.x, viewport.width),
            bottom: corner(viewport.y, viewport.height),
        }
        .intersection(desktop)
    }

    /// Every screen's next picture covers all of it.
    fn refresh_all(&mut self) {
        for screen in 0..SCREENS {
            self.refresh(screen);
        }
    }

    fn apply(&mut self, update: DesktopUpdate) {
        let (pixels, width, height, region) = update.into_parts();
        let (width, height) = (width.get(), height.get());
        let region = Rect {
            left: region.left,
            top: region.top,
            right: region.right,
            bottom: region.bottom,
        };
        if (width, height) != (self.width, self.height) {
            self.width = width;
            self.height = height;
            self.pixels = vec![0; usize::from(width) * usize::from(height)];
            // The clients' pictures have another size, or there are none yet: the next ones
            // cover all of their screens.
            self.refresh_all();
        }
        // DesktopUpdate::new checked that the region lies in the desktop and `pixels` fills it.
        let row_len = usize::from(region.width());
        for (row, line) in pixels.chunks_exact(row_len).enumerate() {
            let start =
                (usize::from(region.top) + row) * usize::from(width) + usize::from(region.left);
            self.pixels[start..start + row_len].copy_from_slice(line);
        }
        for screen in 0..SCREENS {
            if let Some(changed) = self
                .visible(screen)
                .and_then(|visible| visible.intersection(region))
            {
                let dirty = &mut self.dirty[screen];
                *dirty = Some(dirty.map_or(changed, |dirty| dirty.union(changed)));
            }
        }
    }

    /// Whether the layout changed.
    fn set_layout(&mut self, layout: Option<[Viewport; SCREENS]>) -> bool {
        if self.layout == layout {
            return false;
        }
        self.layout = layout;
        self.refresh_all();
        true
    }

    fn refresh(&mut self, screen: usize) {
        self.dirty[screen] = self.visible(screen);
    }

    /// The next picture of `screen`, in the coordinates of its monitor: the header names the
    /// monitor's visible size as the desktop.
    fn take_frame(&mut self, screen: usize) -> Option<Vec<u8>> {
        let dirty = self.dirty[screen].take()?;
        let visible = self.visible(screen)?;
        let row_len = usize::from(dirty.width());
        let mut frame = Vec::with_capacity(HEADER_LEN + row_len * usize::from(dirty.height()) * 4);
        for value in [
            FRAME_VERSION,
            dirty.left - visible.left,
            dirty.top - visible.top,
            dirty.width(),
            dirty.height(),
            visible.width(),
            visible.height(),
        ] {
            frame.extend_from_slice(&value.to_le_bytes());
        }
        for y in dirty.top..=dirty.bottom {
            let start = usize::from(y) * usize::from(self.width) + usize::from(dirty.left);
            for pixel in &self.pixels[start..start + row_len] {
                let [_, red, green, blue] = pixel.to_be_bytes();
                frame.extend_from_slice(&[red, green, blue, 0xff]);
            }
        }
        Some(frame)
    }
}

#[cfg(test)]
mod tests {
    use std::num::NonZeroU16;

    use ironrdp_pdu::geometry::InclusiveRectangle;
    use tokio::task::JoinHandle;
    use tokio_tungstenite::client_async;

    use super::*;

    type Client = WebSocketStream<TcpStream>;

    /// Long enough for a loaded CI runner, short enough not to hide a hang.
    const WAIT: Duration = Duration::from_secs(5);
    /// How long "nothing arrives" is watched.
    const QUIET: Duration = Duration::from_millis(300);

    fn update(width: u16, height: u16, region: (u16, u16, u16, u16), pixel: u32) -> DesktopUpdate {
        let (left, top, right, bottom) = region;
        let count = usize::from(right - left + 1) * usize::from(bottom - top + 1);
        DesktopUpdate::new(
            vec![pixel; count],
            NonZeroU16::new(width).unwrap(),
            NonZeroU16::new(height).unwrap(),
            InclusiveRectangle {
                left,
                top,
                right,
                bottom,
            },
        )
        .unwrap()
    }

    fn header(frame: &[u8]) -> [u16; 7] {
        std::array::from_fn(|i| u16::from_le_bytes([frame[2 * i], frame[2 * i + 1]]))
    }

    fn rgba(pixel: u32) -> [u8; 4] {
        let [_, red, green, blue] = pixel.to_be_bytes();
        [red, green, blue, 0xff]
    }

    async fn connect(port: u16) -> Client {
        let tcp = TcpStream::connect((Ipv4Addr::LOCALHOST, port))
            .await
            .unwrap();
        client_async(format!("ws://127.0.0.1:{port}/"), tcp)
            .await
            .unwrap()
            .0
    }

    struct Running {
        port: u16,
        token: String,
        tokens: Tokens,
        frames: Frames,
        input: mpsc::Receiver<Input>,
        task: JoinHandle<io::Result<()>>,
    }

    fn start(login_deadline: Duration) -> Running {
        // Only the stats tests hear the stats; the others count on pictures alone.
        start_with(login_deadline, Duration::from_secs(3600))
    }

    fn start_with(login_deadline: Duration, stats_every: Duration) -> Running {
        start_alone(login_deadline, stats_every, NO_CLIENT_DEADLINE)
    }

    fn start_alone(
        login_deadline: Duration,
        stats_every: Duration,
        no_client_deadline: Duration,
    ) -> Running {
        let mut server = FrameServer::bind().unwrap();
        server.login_deadline = login_deadline;
        server.stats_every = stats_every;
        server.no_client_deadline = no_client_deadline;
        let (port, token, tokens) = (server.port().unwrap(), server.token(), server.tokens());
        let frames = Frames::default();
        let (sender, input) = mpsc::channel(16);
        let task = tokio::spawn(server.serve(frames.clone(), sender));
        Running {
            port,
            token,
            tokens,
            frames,
            input,
            task,
        }
    }

    async fn logged_in(running: &Running) -> Client {
        with_token(running, &running.token).await
    }

    async fn with_token(running: &Running, token: &str) -> Client {
        let mut ws = connect(running.port).await;
        ws.send(Message::text(token)).await.unwrap();
        ws
    }

    async fn next_frame(ws: &mut Client) -> Vec<u8> {
        match timeout(WAIT, ws.next()).await {
            Ok(Some(Ok(Message::Binary(frame)))) => frame.to_vec(),
            other => panic!("expected a picture, got {other:?}"),
        }
    }

    async fn assert_quiet(ws: &mut Client) {
        if let Ok(message) = timeout(QUIET, ws.next()).await {
            panic!("expected nothing, got {message:?}");
        }
    }

    /// The server ended this connection without sending a picture.
    async fn assert_closed(ws: &mut Client) {
        loop {
            match timeout(WAIT, ws.next()).await {
                Err(_) => panic!("the server kept the connection open"),
                Ok(Some(Ok(Message::Binary(_)))) => {
                    panic!("a picture went to a client without login")
                }
                Ok(Some(Ok(Message::Close(_)) | Err(_)) | None) => return,
                Ok(Some(Ok(_))) => {}
            }
        }
    }

    async fn ack(ws: &mut Client) {
        ws.send(Message::text(r#"{"t":"ack"}"#)).await.unwrap();
    }

    #[test]
    fn frame_ws_listens_on_loopback_only_with_a_fresh_token() {
        let server = FrameServer::bind().unwrap();
        let address = server.listener.local_addr().unwrap();
        assert_eq!(address.ip(), Ipv4Addr::LOCALHOST);
        assert_ne!(address.port(), 0);
        assert_eq!(server.token().len(), 2 * TOKEN_BYTES);
        assert!(server
            .token()
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)));
        assert_ne!(server.token(), FrameServer::bind().unwrap().token());
        assert_eq!(server.login_deadline, Duration::from_secs(5));
        assert_eq!(server.no_client_deadline, Duration::from_secs(60));
    }

    #[test]
    fn frame_ws_token_comparison() {
        assert!(same_token(b"abcd", b"abcd"));
        assert!(!same_token(b"abcd", b"abce"));
        assert!(!same_token(b"abcd", b"bbcd"));
        assert!(!same_token(b"abcd", b"abc"));
        assert!(!same_token(b"abcd", b""));
    }

    #[tokio::test]
    async fn frame_ws_a_wrong_token_closes_only_that_connection() {
        let running = start(LOGIN_DEADLINE);
        running.frames.apply(update(4, 3, (0, 0, 3, 2), 0x00102030));

        let mut wrong = connect(running.port).await;
        wrong.send(Message::text("0".repeat(64))).await.unwrap();
        assert_closed(&mut wrong).await;

        // The right token, but not as the first text message.
        let mut binary = connect(running.port).await;
        binary
            .send(Message::binary(running.token.clone().into_bytes()))
            .await
            .unwrap();
        assert_closed(&mut binary).await;

        let mut ws = logged_in(&running).await;
        assert_eq!(header(&next_frame(&mut ws).await), [1, 0, 0, 4, 3, 4, 3]);
    }

    #[tokio::test]
    async fn frame_ws_a_client_without_login_is_dropped_after_the_deadline() {
        let running = start(Duration::from_millis(100));
        running.frames.apply(update(4, 3, (0, 0, 3, 2), 0x00102030));

        let mut silent = connect(running.port).await;
        assert_closed(&mut silent).await;

        let mut ws = logged_in(&running).await;
        assert_eq!(header(&next_frame(&mut ws).await), [1, 0, 0, 4, 3, 4, 3]);
    }

    #[tokio::test]
    async fn frame_ws_a_silent_client_does_not_hold_back_the_login() {
        let running = start(Duration::from_secs(60));
        running.frames.apply(update(4, 3, (0, 0, 3, 2), 0x00102030));

        let _silent = connect(running.port).await;
        let mut ws = logged_in(&running).await;
        assert_eq!(header(&next_frame(&mut ws).await), [1, 0, 0, 4, 3, 4, 3]);
    }

    #[tokio::test]
    async fn frame_ws_refuses_a_second_client() {
        let running = start(LOGIN_DEADLINE);
        running.frames.apply(update(4, 3, (0, 0, 3, 2), 0x00102030));
        let mut ws = logged_in(&running).await;
        next_frame(&mut ws).await;

        let mut second = logged_in(&running).await;
        assert_closed(&mut second).await;

        // The first client streams on.
        running.frames.apply(update(4, 3, (1, 1, 1, 1), 0x00abcdef));
        ack(&mut ws).await;
        assert_eq!(header(&next_frame(&mut ws).await), [1, 1, 1, 1, 1, 4, 3]);
    }

    #[tokio::test]
    async fn frame_ws_a_renewed_token_replaces_the_one_before() {
        let running = start(LOGIN_DEADLINE);
        running.frames.apply(update(4, 3, (0, 0, 3, 2), 0x00102030));
        let renewed = running.tokens.renew(0).unwrap();
        assert_ne!(renewed, running.token);
        assert_eq!(renewed.len(), 2 * TOKEN_BYTES);

        let mut old = logged_in(&running).await;
        assert_closed(&mut old).await;
        let mut ws = with_token(&running, &renewed).await;
        assert_eq!(header(&next_frame(&mut ws).await), [1, 0, 0, 4, 3, 4, 3]);
    }

    #[tokio::test]
    async fn frame_ws_the_session_outlives_its_client_and_a_new_one_gets_the_whole_picture() {
        let mut running = start(LOGIN_DEADLINE);
        running.frames.apply(update(8, 6, (0, 0, 7, 5), 0x00102030));
        let mut ws = logged_in(&running).await;
        next_frame(&mut ws).await;
        running.frames.apply(update(8, 6, (2, 1, 4, 2), 0x00112233));
        ack(&mut ws).await;
        assert_eq!(header(&next_frame(&mut ws).await), [1, 2, 1, 3, 2, 8, 6]);

        ws.close(None).await.unwrap();
        drop(ws);
        tokio::time::sleep(QUIET).await;
        assert!(
            !running.task.is_finished(),
            "the server ended with its client"
        );
        assert!(
            running.input.try_recv().is_err(),
            "a client that went away sent input"
        );

        let token = running.tokens.renew(0).unwrap();
        let mut back = with_token(&running, &token).await;
        let frame = next_frame(&mut back).await;
        assert_eq!(header(&frame), [1, 0, 0, 8, 6, 8, 6]);
        let pixels: Vec<&[u8]> = frame[HEADER_LEN..].chunks(4).collect();
        // (2, 1) in a desktop eight pixels wide carries the second update.
        assert_eq!(pixels[8 + 2], rgba(0x00112233));
        assert_eq!(pixels[0], rgba(0x00102030));

        back.send(Message::text(r#"{"t":"cad"}"#)).await.unwrap();
        assert_eq!(
            timeout(WAIT, running.input.recv()).await.unwrap(),
            Some(Input::CtrlAltDel)
        );
    }

    #[tokio::test]
    async fn frame_ws_a_session_without_a_client_ends_after_the_deadline() {
        let mut running = start_alone(
            LOGIN_DEADLINE,
            Duration::from_secs(3600),
            Duration::from_millis(200),
        );
        let served = timeout(WAIT, &mut running.task).await;
        assert!(
            matches!(served, Ok(Ok(Ok(())))),
            "the server did not end alone: {served:?}"
        );
        // Its end closes the input, which ends the session like a close.
        assert_eq!(timeout(WAIT, running.input.recv()).await.unwrap(), None);
    }

    #[tokio::test]
    async fn frame_ws_a_client_that_comes_back_in_time_keeps_the_session() {
        // Long enough for a login on a slow runner; the test holds the session past it below.
        let alone = Duration::from_secs(2);
        let mut running = start_alone(LOGIN_DEADLINE, Duration::from_secs(3600), alone);
        running.frames.apply(update(4, 3, (0, 0, 3, 2), 0x00102030));
        let mut ws = logged_in(&running).await;
        next_frame(&mut ws).await;
        ws.close(None).await.unwrap();
        drop(ws);
        tokio::time::sleep(alone / 10).await;

        let token = running.tokens.renew(0).unwrap();
        let mut back = with_token(&running, &token).await;
        next_frame(&mut back).await;
        // A client that streams holds the session past the deadline.
        tokio::time::sleep(alone + alone / 2).await;
        assert!(
            !running.task.is_finished(),
            "the server ended while a client streamed"
        );
        running.frames.apply(update(4, 3, (1, 1, 1, 1), 0x00abcdef));
        ack(&mut back).await;
        assert_eq!(header(&next_frame(&mut back).await), [1, 1, 1, 1, 1, 4, 3]);

        // Gone again, it ends after the deadline.
        back.close(None).await.unwrap();
        drop(back);
        let served = timeout(WAIT, &mut running.task).await;
        assert!(
            matches!(served, Ok(Ok(Ok(())))),
            "the server did not end alone: {served:?}"
        );
    }

    #[tokio::test]
    async fn frame_ws_a_new_login_takes_over_from_the_client() {
        let mut running = start(LOGIN_DEADLINE);
        running.frames.apply(update(4, 3, (0, 0, 3, 2), 0x00102030));
        let mut first = logged_in(&running).await;
        next_frame(&mut first).await;

        let token = running.tokens.renew(0).unwrap();
        let mut second = with_token(&running, &token).await;
        // The new client gets the whole picture although the first one has it already.
        assert_eq!(
            header(&next_frame(&mut second).await),
            [1, 0, 0, 4, 3, 4, 3]
        );
        assert_closed(&mut first).await;

        second
            .send(Message::text(r#"{"t":"close"}"#))
            .await
            .unwrap();
        assert_eq!(
            timeout(WAIT, running.input.recv()).await.unwrap(),
            Some(Input::Close)
        );
        timeout(WAIT, &mut running.task)
            .await
            .expect("close did not end the server")
            .unwrap()
            .unwrap();
    }

    #[test]
    fn frame_ws_picture_layout() {
        let frames = Frames::default();
        frames.apply(update(8, 6, (0, 0, 7, 5), 0x00000000));
        let first = frames.take_frame(0).unwrap();
        assert_eq!(header(&first), [1, 0, 0, 8, 6, 8, 6]);
        assert_eq!(first.len(), HEADER_LEN + 8 * 6 * 4);

        frames.apply(update(8, 6, (2, 1, 4, 2), 0x00112233));
        let frame = frames.take_frame(0).unwrap();
        assert_eq!(
            frame[..HEADER_LEN],
            [1, 0, 2, 0, 1, 0, 3, 0, 2, 0, 8, 0, 6, 0]
        );
        assert_eq!(frame[HEADER_LEN..], [0x11, 0x22, 0x33, 0xff].repeat(6));
        assert_eq!(frames.take_frame(0), None, "a picture went out twice");
    }

    #[test]
    fn frame_ws_a_new_desktop_size_sends_the_whole_desktop() {
        let frames = Frames::default();
        frames.apply(update(8, 6, (0, 0, 7, 5), 0x00ffffff));
        frames.take_frame(0).unwrap();

        frames.apply(update(4, 3, (1, 1, 1, 1), 0x00abcdef));
        let frame = frames.take_frame(0).unwrap();
        assert_eq!(header(&frame), [1, 0, 0, 4, 3, 4, 3]);
        let pixels: Vec<&[u8]> = frame[HEADER_LEN..].chunks(4).collect();
        assert_eq!(pixels.len(), 12);
        for (index, pixel) in pixels.iter().enumerate() {
            // (1, 1) in a desktop four pixels wide.
            let expected = if index == 4 + 1 { 0x00abcdef } else { 0 };
            assert_eq!(*pixel, rgba(expected), "pixel {index}");
        }
    }

    #[tokio::test]
    async fn frame_ws_merges_updates_until_the_ack() {
        const WIDTH: u16 = 16;
        const HEIGHT: u16 = 12;
        let running = start(LOGIN_DEADLINE);
        let mut ws = logged_in(&running).await;
        running
            .frames
            .apply(update(WIDTH, HEIGHT, (0, 0, WIDTH - 1, HEIGHT - 1), 0));
        next_frame(&mut ws).await;

        // Ten updates before the receipt, overlapping, each with a newer colour.
        let regions = [
            (1, 1, 5, 5),
            (3, 3, 4, 4),
            (8, 2, 9, 7),
            (2, 6, 6, 6),
            (1, 1, 1, 1),
            (4, 2, 8, 3),
            (5, 5, 9, 7),
            (3, 4, 3, 7),
            (9, 1, 9, 1),
            (2, 2, 3, 3),
        ];
        let mut model = vec![0u32; usize::from(WIDTH) * usize::from(HEIGHT)];
        for (index, &(left, top, right, bottom)) in regions.iter().enumerate() {
            let pixel = 0x0001_0101 * (index as u32 + 1);
            running
                .frames
                .apply(update(WIDTH, HEIGHT, (left, top, right, bottom), pixel));
            for y in top..=bottom {
                for x in left..=right {
                    model[usize::from(y) * usize::from(WIDTH) + usize::from(x)] = pixel;
                }
            }
        }
        assert_quiet(&mut ws).await;

        ack(&mut ws).await;
        let frame = next_frame(&mut ws).await;
        // The enclosing rectangle of the ten: x 1..=9, y 1..=7.
        assert_eq!(header(&frame), [1, 1, 1, 9, 7, WIDTH, HEIGHT]);
        let mut expected = Vec::new();
        for y in 1..=7 {
            for x in 1..=9 {
                expected.extend_from_slice(&rgba(model[y * usize::from(WIDTH) + x]));
            }
        }
        assert_eq!(frame[HEADER_LEN..], expected[..]);

        assert_quiet(&mut ws).await;
        ack(&mut ws).await;
        assert_quiet(&mut ws).await;
    }

    #[tokio::test]
    async fn frame_ws_passes_valid_input_on_and_drops_the_rest() {
        let mut running = start(LOGIN_DEADLINE);
        let mut ws = logged_in(&running).await;
        for malformed in [
            "not json",
            r#"{"t":"jump"}"#,
            r#"{"t":"key"}"#,
            r#"{"t":"key","code":300,"ext":false,"down":true}"#,
            r#"{"t":"mouse","x":-1,"y":0,"buttons":0,"wheel":0}"#,
            r#"{"t":"mouse","x":1,"y":2,"buttons":"left","wheel":0}"#,
            r#"{"t":"size","w":1920,"h":1080}"#,
            r#"{"t":"size","w":70000,"h":1080,"scale":100}"#,
        ] {
            ws.send(Message::text(malformed)).await.unwrap();
        }
        ws.send(Message::binary(vec![1, 2, 3])).await.unwrap();
        for valid in [
            r#"{"t":"key","code":30,"ext":false,"down":true}"#,
            r#"{"t":"key","code":75,"ext":true,"down":false}"#,
            r#"{"t":"mouse","x":640,"y":480,"buttons":1,"wheel":-120}"#,
            r#"{"t":"cad"}"#,
            r#"{"t":"size","w":1921,"h":100,"scale":900}"#,
            r#"{"t":"close"}"#,
        ] {
            ws.send(Message::text(valid)).await.unwrap();
        }

        let mut received = Vec::new();
        while let Ok(Some(event)) = timeout(WAIT, running.input.recv()).await {
            received.push(event);
        }
        assert_eq!(
            received,
            [
                Input::Key {
                    code: 30,
                    extended: false,
                    down: true
                },
                Input::Key {
                    code: 75,
                    extended: true,
                    down: false
                },
                Input::Mouse {
                    x: 640,
                    y: 480,
                    buttons: 1,
                    wheel: -120
                },
                Input::CtrlAltDel,
                Input::Size(Display {
                    width: 1920,
                    height: 200,
                    scale: 500
                }),
                Input::Close,
            ]
        );
        timeout(WAIT, &mut running.task)
            .await
            .expect("close did not end the server")
            .unwrap()
            .unwrap();
    }

    fn viewport(x: u16, y: u16, width: u16, height: u16) -> Viewport {
        Viewport {
            x,
            y,
            width,
            height,
        }
    }

    #[test]
    fn frame_ws_each_screen_shows_its_part_of_the_desktop() {
        let frames = Frames::default();
        frames.apply(update(8, 3, (0, 0, 3, 2), 0x00111111));
        frames.apply(update(8, 3, (4, 0, 7, 2), 0x00222222));
        // Without a layout screen 0 shows the whole desktop and screen 1 nothing.
        assert_eq!(
            header(&frames.take_frame(0).unwrap()),
            [1, 0, 0, 8, 3, 8, 3]
        );
        assert_eq!(frames.take_frame(1), None);
        assert_eq!(frames.take_stats(1, Duration::from_secs(1)), None);

        frames.set_layout(Some([viewport(0, 0, 4, 3), viewport(4, 0, 4, 3)]));
        let left = frames.take_frame(0).unwrap();
        let right = frames.take_frame(1).unwrap();
        assert_eq!(header(&left), [1, 0, 0, 4, 3, 4, 3]);
        assert_eq!(header(&right), [1, 0, 0, 4, 3, 4, 3]);
        assert_eq!(left[HEADER_LEN..], rgba(0x00111111).repeat(12));
        assert_eq!(right[HEADER_LEN..], rgba(0x00222222).repeat(12));
        // The same layout again sends nothing.
        frames.set_layout(Some([viewport(0, 0, 4, 3), viewport(4, 0, 4, 3)]));
        assert_eq!((frames.take_frame(0), frames.take_frame(1)), (None, None));

        // A change goes to the screen it lies on, in that screen's coordinates.
        frames.apply(update(8, 3, (5, 1, 5, 1), 0x00abcdef));
        assert_eq!(frames.take_frame(0), None);
        let frame = frames.take_frame(1).unwrap();
        assert_eq!(header(&frame), [1, 1, 1, 1, 1, 4, 3]);
        assert_eq!(frame[HEADER_LEN..], rgba(0x00abcdef));
        // Across both, each screen gets its part of it.
        frames.apply(update(8, 3, (3, 0, 4, 0), 0x00ffffff));
        assert_eq!(
            header(&frames.take_frame(0).unwrap()),
            [1, 3, 0, 1, 1, 4, 3]
        );
        assert_eq!(
            header(&frames.take_frame(1).unwrap()),
            [1, 0, 0, 1, 1, 4, 3]
        );
        let stats: serde_json::Value =
            serde_json::from_str(&frames.take_stats(1, Duration::from_secs(1)).unwrap()).unwrap();
        assert_eq!(
            (stats["width"].as_u64(), stats["height"].as_u64()),
            (Some(4), Some(3))
        );
    }

    #[test]
    fn frame_ws_a_screen_shows_what_exists_of_its_monitor() {
        // The server has not taken the layout yet: its desktop is smaller than both monitors.
        let frames = Frames::default();
        frames.apply(update(6, 3, (0, 0, 5, 2), 0x00111111));
        frames.set_layout(Some([viewport(0, 1, 4, 3), viewport(4, 0, 4, 2)]));
        assert_eq!(
            header(&frames.take_frame(0).unwrap()),
            [1, 0, 0, 4, 2, 4, 2]
        );
        assert_eq!(
            header(&frames.take_frame(1).unwrap()),
            [1, 0, 0, 2, 2, 2, 2]
        );
        assert_eq!(frames.origin(1), (4, 0));
        // Then it does: each screen gets all of its monitor.
        frames.apply(update(8, 4, (0, 0, 7, 3), 0x00222222));
        assert_eq!(
            header(&frames.take_frame(0).unwrap()),
            [1, 0, 0, 4, 3, 4, 3]
        );
        assert_eq!(
            header(&frames.take_frame(1).unwrap()),
            [1, 0, 0, 4, 2, 4, 2]
        );
        // A monitor outside the desktop shows nothing.
        frames.set_layout(Some([viewport(0, 0, 4, 4), viewport(8, 0, 4, 4)]));
        assert!(frames.take_frame(0).is_some());
        assert_eq!(frames.take_frame(1), None);
        // Without a layout screen 0 shows the whole desktop again.
        frames.set_layout(None);
        assert_eq!(
            header(&frames.take_frame(0).unwrap()),
            [1, 0, 0, 8, 4, 8, 4]
        );
        assert_eq!(frames.take_frame(1), None);
        assert_eq!(frames.origin(1), (0, 0));
    }

    #[tokio::test]
    async fn frame_ws_each_screen_has_its_client_its_token_and_its_ack() {
        let mut running = start(LOGIN_DEADLINE);
        running
            .frames
            .set_layout(Some([viewport(0, 0, 4, 3), viewport(4, 0, 4, 3)]));
        running.frames.apply(update(8, 3, (0, 0, 7, 2), 0x00102030));
        // Screen 1 has no token before one is handed out for it.
        let second_token = running.tokens.renew(1).unwrap();
        let mut first = logged_in(&running).await;
        assert_eq!(header(&next_frame(&mut first).await), [1, 0, 0, 4, 3, 4, 3]);
        // Its token for screen 1 left the one of screen 0 alone, and logs in only once.
        let mut second = with_token(&running, &second_token).await;
        assert_eq!(
            header(&next_frame(&mut second).await),
            [1, 0, 0, 4, 3, 4, 3]
        );
        let mut again = with_token(&running, &second_token).await;
        assert_closed(&mut again).await;

        // A change on both screens: only the screen that acknowledged gets its picture.
        running.frames.apply(update(8, 3, (2, 1, 5, 1), 0x00abcdef));
        ack(&mut second).await;
        assert_eq!(
            header(&next_frame(&mut second).await),
            [1, 0, 1, 2, 1, 4, 3]
        );
        assert_quiet(&mut first).await;
        ack(&mut first).await;
        assert_eq!(header(&next_frame(&mut first).await), [1, 2, 1, 2, 1, 4, 3]);

        // The mouse of screen 1 lies in its monitor, which starts at x 4 of the desktop.
        for ws in [&mut first, &mut second] {
            ws.send(Message::text(
                r#"{"t":"mouse","x":1,"y":2,"buttons":0,"wheel":0}"#,
            ))
            .await
            .unwrap();
        }
        let mut received = Vec::new();
        for _ in 0..2 {
            received.push(timeout(WAIT, running.input.recv()).await.unwrap().unwrap());
        }
        let mouse = |x| Input::Mouse {
            x,
            y: 2,
            buttons: 0,
            wheel: 0,
        };
        assert!(
            received.contains(&mouse(1)) && received.contains(&mouse(5)),
            "{received:?}"
        );
    }

    #[tokio::test]
    async fn frame_ws_passes_a_layout_of_two_monitors_on() {
        let mut running = start(LOGIN_DEADLINE);
        let mut ws = logged_in(&running).await;
        for message in [
            r#"{"t":"layout","monitors":[]}"#,
            r#"{"t":"layout","monitors":[{"x":0,"y":0,"w":1920,"h":1080,"scale":100}]}"#,
            r#"{"t":"layout","monitors":[{"x":0,"y":0,"w":1920,"h":1080,"scale":100},{"x":1920,"y":0,"w":1920,"h":1080,"scale":100},{"x":3840,"y":0,"w":1920,"h":1080,"scale":100}]}"#,
            r#"{"t":"layout","monitors":[{"x":0,"y":0,"w":1920,"h":1080}]}"#,
            r#"{"t":"layout","monitors":[{"x":1000,"y":200,"w":1921,"h":100,"scale":900},{"x":2921,"y":100,"w":1280,"h":1024,"scale":100}]}"#,
        ] {
            ws.send(Message::text(message)).await.unwrap();
        }
        let received = timeout(WAIT, running.input.recv()).await.unwrap().unwrap();
        // Sizes and scales within the limits of `size`, the second placed from the first.
        assert_eq!(
            received,
            Input::Layout(Layout::placed(
                Display::clamped(1920, 200, 500),
                Display::clamped(1280, 1024, 100),
                1921,
                -100,
            ))
        );
        assert_quiet(&mut ws).await;
        assert!(
            running.input.try_recv().is_err(),
            "a layout of other than two monitors went on"
        );
    }

    async fn next_stats(ws: &mut Client) -> serde_json::Value {
        match timeout(WAIT, ws.next()).await {
            Ok(Some(Ok(Message::Text(text)))) => serde_json::from_str(&text).unwrap(),
            other => panic!("expected stats, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn frame_ws_sends_stats_while_there_is_a_picture() {
        let running = start_with(LOGIN_DEADLINE, Duration::from_millis(100));
        let mut ws = logged_in(&running).await;
        assert_quiet(&mut ws).await;

        running.frames.apply(update(4, 3, (0, 0, 3, 2), 0x00102030));
        // A tick between the update and its send brings a stats message before the picture.
        loop {
            match timeout(WAIT, ws.next()).await {
                Ok(Some(Ok(Message::Binary(_)))) => break,
                Ok(Some(Ok(Message::Text(_)))) => {}
                other => panic!("expected a picture, got {other:?}"),
            }
        }
        let first = next_stats(&mut ws).await;
        assert_eq!(first["t"], "stats");
        assert!(first["fps"].as_f64().unwrap() > 0.0, "{first}");
        assert_eq!(
            (first["width"].as_u64(), first["height"].as_u64()),
            (Some(4), Some(3))
        );
        assert!(
            first.get("mbps").is_none() && first.get("rtt_ms").is_none(),
            "{first}"
        );

        running.frames.network(Some(12), Some(25_000));
        let measured = next_stats(&mut ws).await;
        // No ack, so no further picture: the count starts again with every message.
        assert_eq!(measured["fps"].as_f64(), Some(0.0), "{measured}");
        assert_eq!(measured["rtt_ms"].as_u64(), Some(12));
        assert_eq!(measured["mbps"].as_f64(), Some(25.0));
    }

    #[test]
    fn frame_ws_stats_count_since_the_last_message() {
        let frames = Frames::default();
        frames.sent(0);
        assert_eq!(
            frames.take_stats(0, Duration::from_secs(1)),
            None,
            "stats without a picture"
        );

        frames.apply(update(8, 6, (0, 0, 7, 5), 0));
        for _ in 0..3 {
            frames.sent(0);
        }
        frames.network(Some(40), Some(1_234));
        let stats: serde_json::Value =
            serde_json::from_str(&frames.take_stats(0, Duration::from_secs(2)).unwrap()).unwrap();
        assert_eq!(
            stats,
            serde_json::json!({"t": "stats", "fps": 1.5, "width": 8, "height": 6, "mbps": 1.2, "rtt_ms": 40})
        );

        // A new connection has measured nothing yet.
        frames.network(None, None);
        let stats: serde_json::Value =
            serde_json::from_str(&frames.take_stats(0, Duration::from_secs(1)).unwrap()).unwrap();
        assert_eq!(
            stats,
            serde_json::json!({"t": "stats", "fps": 0.0, "width": 8, "height": 6})
        );
    }

    #[test]
    fn frame_ws_png_holds_the_whole_desktop() {
        let frames = Frames::default();
        assert!(frames.png().is_err(), "a PNG without a picture");
        frames.apply(update(3, 2, (0, 0, 2, 1), 0x00102030));
        frames.apply(update(3, 2, (2, 1, 2, 1), 0x00abcdef));
        // What went out to the webview does not matter: the PNG is the whole desktop.
        frames.take_frame(0).unwrap();

        let png = frames.png().unwrap();
        let mut reader = png::Decoder::new(std::io::Cursor::new(png))
            .read_info()
            .unwrap();
        let mut pixels = vec![0; reader.output_buffer_size().unwrap()];
        let info = reader.next_frame(&mut pixels).unwrap();
        assert_eq!((info.width, info.height), (3, 2));
        assert_eq!(info.color_type, png::ColorType::Rgb);
        let mut expected = [0x10, 0x20, 0x30].repeat(5);
        expected.extend_from_slice(&[0xab, 0xcd, 0xef]);
        assert_eq!(pixels[..info.buffer_size()], expected[..]);
    }

    #[test]
    fn frame_ws_csp_allows_the_loopback_socket_and_keeps_script_src() {
        let config: serde_json::Value =
            serde_json::from_str(include_str!("../../tauri.conf.json")).unwrap();
        let csp = config["app"]["security"]["csp"].as_str().unwrap();
        let directives: Vec<&str> = csp.split(';').map(str::trim).collect();
        let connect = directives
            .iter()
            .find(|directive| directive.starts_with("connect-src "))
            .unwrap();
        assert!(
            connect
                .split_whitespace()
                .any(|source| source == "ws://127.0.0.1:*"),
            "{connect}"
        );
        assert!(directives.contains(&"script-src 'self'"), "{csp}");
    }
}
