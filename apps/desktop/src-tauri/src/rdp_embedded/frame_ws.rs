// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! The local WebSocket that carries the desktop picture to the webview and its input back
//! (docs/features/arch-rdp-backend.md, "WebSocket-Protokoll").
//!
//! One server per session, on 127.0.0.1 with a port the system picks. The first client that
//! sends the session's token as its first text message is the only one: the server stops
//! listening once it has logged in. Pictures go out one at a time, the next after the client's
//! `{"t":"ack"}`; whatever changes in between is merged into one enclosing rectangle, so no
//! backlog builds up behind a slow webview.

use std::io;
use std::net::Ipv4Addr;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use futures_util::{SinkExt, StreamExt};
use ironrdp_client::rdp::DesktopUpdate;
use serde::Deserialize;
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::{mpsc, Notify};
use tokio::task::JoinSet;
use tokio::time::timeout;
use tokio_tungstenite::tungstenite::protocol::WebSocketConfig;
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::{accept_async_with_config, WebSocketStream};

const TOKEN_BYTES: usize = 32;
const LOGIN_DEADLINE: Duration = Duration::from_secs(5);
/// Logins that run side by side. Each ends at the deadline, so a local process that opens
/// connections and stays silent holds back the webview's login by one deadline at most.
const MAX_PENDING_LOGINS: usize = 8;
/// The client sends the token and small JSON messages; anything larger is not ours.
const MAX_CLIENT_MESSAGE: usize = 4096;
const FRAME_VERSION: u16 = 1;
/// Version, x, y, width, height, desktop width, desktop height: seven u16, little-endian.
const HEADER_LEN: usize = 14;

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
    Close,
}

pub(crate) struct FrameServer {
    listener: std::net::TcpListener,
    token: String,
    login_deadline: Duration,
}

impl FrameServer {
    /// Binds before the session starts, so port and token can go to the webview right away.
    pub(crate) fn bind() -> io::Result<Self> {
        let listener = std::net::TcpListener::bind((Ipv4Addr::LOCALHOST, 0))?;
        listener.set_nonblocking(true)?;
        let mut bytes = [0u8; TOKEN_BYTES];
        crate::tofu::ring_provider()
            .secure_random
            .fill(&mut bytes)
            .map_err(|_| io::Error::other("no random bytes for the frame token"))?;
        let token = bytes.iter().map(|byte| format!("{byte:02x}")).collect();
        Ok(Self {
            listener,
            token,
            login_deadline: LOGIN_DEADLINE,
        })
    }

    pub(crate) fn port(&self) -> io::Result<u16> {
        Ok(self.listener.local_addr()?.port())
    }

    pub(crate) fn token(&self) -> &str {
        &self.token
    }

    /// Waits for the client, then streams `frames` to it and passes its input on, until the
    /// client closes or goes away. Must run inside a tokio runtime.
    pub(crate) async fn serve(self, frames: Frames, input: mpsc::Sender<Input>) -> io::Result<()> {
        let listener = TcpListener::from_std(self.listener)?;
        // A wrong token, or none in time, closes only that connection, and logins do not wait for
        // each other: a local process that connects first must not lock the webview out.
        let mut pending = JoinSet::new();
        let ws = loop {
            tokio::select! {
                accepted = listener.accept(), if pending.len() < MAX_PENDING_LOGINS => {
                    let (tcp, _) = accepted?;
                    let (token, deadline) = (self.token.clone(), self.login_deadline);
                    pending.spawn(async move { timeout(deadline, login(tcp, &token)).await });
                }
                Some(done) = pending.join_next() => {
                    if let Ok(Ok(Some(ws))) = done {
                        break ws;
                    }
                }
            }
        };
        // One client per session: the other logins end here, and a later client finds the port
        // closed.
        drop(pending);
        drop(listener);
        stream(ws, frames, input).await;
        Ok(())
    }
}

async fn login(tcp: TcpStream, token: &str) -> Option<WebSocketStream<TcpStream>> {
    let limits = WebSocketConfig::default()
        .max_message_size(Some(MAX_CLIENT_MESSAGE))
        .max_frame_size(Some(MAX_CLIENT_MESSAGE));
    let mut ws = accept_async_with_config(tcp, Some(limits)).await.ok()?;
    match ws.next().await {
        Some(Ok(Message::Text(text))) if same_token(token.as_bytes(), text.as_bytes()) => Some(ws),
        _ => {
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

async fn stream(mut ws: WebSocketStream<TcpStream>, frames: Frames, input: mpsc::Sender<Input>) {
    // The first picture needs no receipt; every further one waits for the client's ack.
    let mut acked = true;
    loop {
        tokio::select! {
            () = frames.changed(), if acked => {
                if let Some(frame) = frames.take_frame() {
                    if ws.send(Message::binary(frame)).await.is_err() {
                        return;
                    }
                    acked = false;
                }
            }
            message = ws.next() => {
                let text = match message {
                    Some(Ok(Message::Text(text))) => text,
                    Some(Ok(Message::Close(_)) | Err(_)) | None => return,
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
                    Ok(ClientMessage::Mouse { x, y, buttons, wheel }) => Input::Mouse {
                        x,
                        y,
                        buttons,
                        wheel,
                    },
                    Ok(ClientMessage::Close) => Input::Close,
                    // Unknown or malformed: dropped, the session goes on.
                    Err(_) => continue,
                };
                if input.send(event).await.is_err() || event == Input::Close {
                    return;
                }
            }
        }
    }
}

/// The desktop picture, shared between the session (which applies IronRDP's updates) and the
/// WebSocket (which sends what changed).
#[derive(Clone, Default)]
pub(crate) struct Frames(Arc<Shared>);

#[derive(Default)]
struct Shared {
    buffer: Mutex<Framebuffer>,
    changed: Notify,
}

#[derive(Default)]
struct Framebuffer {
    width: u16,
    height: u16,
    /// `0x00RRGGBB`, row by row, as IronRDP delivers them.
    pixels: Vec<u32>,
    /// What changed since the last picture went out.
    dirty: Option<Rect>,
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

    fn width(self) -> u16 {
        self.right - self.left + 1
    }

    fn height(self) -> u16 {
        self.bottom - self.top + 1
    }
}

impl Frames {
    pub(crate) fn apply(&self, update: DesktopUpdate) {
        self.0
            .buffer
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .apply(update);
        self.0.changed.notify_one();
    }

    fn has_changes(&self) -> bool {
        self.0
            .buffer
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .dirty
            .is_some()
    }

    /// Returns once there is something to send. A notification without a change (its picture
    /// already went out) waits on.
    async fn changed(&self) {
        while !self.has_changes() {
            self.0.changed.notified().await;
        }
    }

    fn take_frame(&self) -> Option<Vec<u8>> {
        self.0
            .buffer
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .take_frame()
    }
}

impl Framebuffer {
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
            // The client's picture has another size, or there is none yet: the next one covers
            // the whole desktop.
            self.dirty = Some(Rect {
                left: 0,
                top: 0,
                right: width - 1,
                bottom: height - 1,
            });
        }
        // DesktopUpdate::new checked that the region lies in the desktop and `pixels` fills it.
        let row_len = usize::from(region.width());
        for (row, line) in pixels.chunks_exact(row_len).enumerate() {
            let start =
                (usize::from(region.top) + row) * usize::from(width) + usize::from(region.left);
            self.pixels[start..start + row_len].copy_from_slice(line);
        }
        self.dirty = Some(self.dirty.map_or(region, |dirty| dirty.union(region)));
    }

    fn take_frame(&mut self) -> Option<Vec<u8>> {
        let dirty = self.dirty.take()?;
        let row_len = usize::from(dirty.width());
        let mut frame = Vec::with_capacity(HEADER_LEN + row_len * usize::from(dirty.height()) * 4);
        for value in [
            FRAME_VERSION,
            dirty.left,
            dirty.top,
            dirty.width(),
            dirty.height(),
            self.width,
            self.height,
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
        frames: Frames,
        input: mpsc::Receiver<Input>,
        task: JoinHandle<io::Result<()>>,
    }

    fn start(login_deadline: Duration) -> Running {
        let mut server = FrameServer::bind().unwrap();
        server.login_deadline = login_deadline;
        let (port, token) = (server.port().unwrap(), server.token().to_string());
        let frames = Frames::default();
        let (sender, input) = mpsc::channel(16);
        let task = tokio::spawn(server.serve(frames.clone(), sender));
        Running {
            port,
            token,
            frames,
            input,
            task,
        }
    }

    async fn logged_in(running: &Running) -> Client {
        let mut ws = connect(running.port).await;
        ws.send(Message::text(running.token.clone())).await.unwrap();
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

        let refused = match TcpStream::connect((Ipv4Addr::LOCALHOST, running.port)).await {
            Err(_) => true,
            // A handshake that hangs means the port is still open: not refused.
            Ok(tcp) => {
                let url = format!("ws://127.0.0.1:{}/", running.port);
                matches!(timeout(WAIT, client_async(url, tcp)).await, Ok(Err(_)))
            }
        };
        assert!(refused, "a second client was not refused");
    }

    #[test]
    fn frame_ws_picture_layout() {
        let frames = Frames::default();
        frames.apply(update(8, 6, (0, 0, 7, 5), 0x00000000));
        let first = frames.take_frame().unwrap();
        assert_eq!(header(&first), [1, 0, 0, 8, 6, 8, 6]);
        assert_eq!(first.len(), HEADER_LEN + 8 * 6 * 4);

        frames.apply(update(8, 6, (2, 1, 4, 2), 0x00112233));
        let frame = frames.take_frame().unwrap();
        assert_eq!(
            frame[..HEADER_LEN],
            [1, 0, 2, 0, 1, 0, 3, 0, 2, 0, 8, 0, 6, 0]
        );
        assert_eq!(frame[HEADER_LEN..], [0x11, 0x22, 0x33, 0xff].repeat(6));
        assert_eq!(frames.take_frame(), None, "a picture went out twice");
    }

    #[test]
    fn frame_ws_a_new_desktop_size_sends_the_whole_desktop() {
        let frames = Frames::default();
        frames.apply(update(8, 6, (0, 0, 7, 5), 0x00ffffff));
        frames.take_frame().unwrap();

        frames.apply(update(4, 3, (1, 1, 1, 1), 0x00abcdef));
        let frame = frames.take_frame().unwrap();
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
        ] {
            ws.send(Message::text(malformed)).await.unwrap();
        }
        ws.send(Message::binary(vec![1, 2, 3])).await.unwrap();
        for valid in [
            r#"{"t":"key","code":30,"ext":false,"down":true}"#,
            r#"{"t":"key","code":75,"ext":true,"down":false}"#,
            r#"{"t":"mouse","x":640,"y":480,"buttons":1,"wheel":-120}"#,
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
                Input::Close,
            ]
        );
        timeout(WAIT, &mut running.task)
            .await
            .expect("close did not end the server")
            .unwrap()
            .unwrap();
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
