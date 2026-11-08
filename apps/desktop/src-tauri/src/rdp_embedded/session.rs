// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! One embedded RDP session (docs/features/arch-rdp-backend.md): IronRDP and the frame WebSocket
//! on a thread of their own, and the phases the webview sees.

use std::io;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use ironrdp_cfg::AudioMode;
use ironrdp_client::config::{ClipboardType, Config, ConfigBuilder, Destination};
use ironrdp_client::output_channel::{output_channel, OutputEventReceiver};
use ironrdp_client::rdp::{
    AutoReconnectDecision, RdpClient, RdpInputEvent, RdpInputSender, RdpOutputEvent,
    RdpdrBackendFactory,
};
use ironrdp_connector::{ConnectorError, ConnectorErrorKind};
use ironrdp_displaycontrol::pdu::{
    DeviceScaleFactor, DisplayControlMonitorLayout, MonitorLayoutEntry,
};
use ironrdp_pdu::input::fast_path::{FastPathInputEvent, KeyboardFlags};
use ironrdp_pdu::input::mouse::PointerFlags;
use ironrdp_pdu::input::MousePdu;
use ironrdp_pdu::rdp::capability_sets::MajorPlatformType;
use ironrdp_pdu::rdp::client_info::PerformanceFlags;
use ironrdp_pdu::rdp::session_info::LogonErrorNotificationType;
use ironrdp_session::{GracefulDisconnectReason, SessionResult};
use ironrdp_tls::CertificateValidation;
use serde::{Deserialize, Serialize};
use tokio::sync::{mpsc, oneshot};
use tokio::task::{JoinHandle, LocalSet};
use tokio::time::MissedTickBehavior;
use zeroize::Zeroizing;

use super::frame_ws::{FrameServer, Frames, Input, Tokens, Viewport};
use super::tofu::{validation_callback, CertPolicy, CertProblem, CertReport, CALLBACK_SCOPE};
use super::watchdog::{Verdict, Watchdog};
use crate::error::AppError;
use crate::models::{RdpAudio, RdpPerformanceProfile};

/// The desktop of a session the webview asked for no size.
const DESKTOP_WIDTH: u16 = 1280;
const DESKTOP_HEIGHT: u16 = 720;
/// The limits of a monitor in MS-RDPEDISP (DISPLAYCONTROL_MONITOR_LAYOUT): 200 to 8192 pixels, an
/// even width, a desktop scale factor of 100 to 500 percent.
const MIN_SIDE: u16 = 200;
const MAX_SIDE: u16 = 8192;
const MIN_SCALE: u32 = 100;
const MAX_SCALE: u32 = 500;
/// IronRDP's own reconnects of a session that lost its connection, before it gives up.
const AUTO_RECONNECTS: u32 = 3;
/// How often the watchdog looks at the clock.
const TICK: Duration = Duration::from_secs(1);
const INPUT_QUEUE: usize = 256;
const OUTPUT_QUEUE: usize = 64;
const DEFAULT_CLIENT_NAME: &str = "AdminHelper";
/// What mstsc reports; IronRDP's own clients send the same.
const CLIENT_DIR: &str = "C:\\Windows\\System32\\mstscax.dll";
/// The button bits of the webview's `mouse` message and the RDP pointer flag of each.
const BUTTONS: [(u8, PointerFlags); 3] = [
    (1, PointerFlags::LEFT_BUTTON),
    (2, PointerFlags::RIGHT_BUTTON),
    (4, PointerFlags::MIDDLE_BUTTON_OR_WHEEL),
];
const BUTTON_MASK: u8 = 0b111;
/// The one drive a session shares; device ID 0 belongs to the smartcard.
const DRIVE_ID: u32 = 1;
const DRIVE_NAME: &str = "Downloads";
/// The scancodes of Ctrl, Alt and Del (E0 prefix); pressed in this order, released the other way.
/// Windows answers this sequence with its secure attention screen (checked against Windows Server).
const CTRL_ALT_DEL: [(u8, bool); 3] = [(0x1D, false), (0x38, false), (0x53, true)];

/// What a session connects to, resolved and checked by the start command.
pub(crate) struct Target {
    pub(crate) destination: Destination,
    /// The desktop the session starts with.
    pub(crate) display: Display,
    pub(crate) username: String,
    pub(crate) domain: Option<String>,
    pub(crate) password: Zeroizing<String>,
    pub(crate) policy: CertPolicy,
    /// `options.rdp.audio` of the connection; unset plays locally, as the OS client does.
    pub(crate) audio: Option<RdpAudio>,
    /// The folder the server sees as the `Downloads` drive; `None` shares no drive.
    pub(crate) drive: Option<PathBuf>,
    /// NLA (CredSSP) before the session; off only for `options.rdp.nla: false`, as the OS client.
    pub(crate) credssp: bool,
    /// The connection's own profile, else `rdp_performance_profile` of the settings.
    pub(crate) performance: RdpPerformanceProfile,
}

/// The size of the desktop in pixels and its scale factor in percent, within the limits of
/// MS-RDPEDISP. The webview asks for it; IronRDP fits it to the server once more.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
pub(crate) struct Display {
    pub(crate) width: u16,
    pub(crate) height: u16,
    pub(crate) scale: u32,
}

impl Display {
    pub(crate) fn clamped(width: u16, height: u16, scale: u32) -> Self {
        Display {
            // MAX_SIDE is even, so rounding down stays in the range.
            width: width.clamp(MIN_SIDE, MAX_SIDE) & !1,
            height: height.clamp(MIN_SIDE, MAX_SIDE),
            scale: scale.clamp(MIN_SCALE, MAX_SCALE),
        }
    }

    /// The device scale factor that goes with `scale`: servers ignore a desktop scale factor
    /// without one of 100, 140 or 180 percent. The plateaus are IronRDP's
    /// (`DeviceScaleFactor::from_desktop_scale_factor`).
    fn device_scale(self) -> u32 {
        match self.scale {
            ..140 => 100,
            140..180 => 140,
            _ => 180,
        }
    }
}

impl Default for Display {
    fn default() -> Self {
        Display {
            width: DESKTOP_WIDTH,
            height: DESKTOP_HEIGHT,
            scale: MIN_SCALE,
        }
    }
}

/// A desktop across two monitors (R-1101): the first is the primary at (0, 0), the second lies
/// at `left`, `top` beside it, touching it along an edge as MS-RDPEDISP demands.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct Layout {
    pub(crate) first: Display,
    pub(crate) second: Display,
    left: i32,
    top: i32,
}

impl Layout {
    /// The layout nearest to the second monitor lying at `left`, `top` from the first, as the
    /// client's screens lie: it moves to the side it lies on most and slides along it until the
    /// two touch.
    pub(crate) fn placed(first: Display, second: Display, left: i32, top: i32) -> Self {
        let (w0, h0) = (i32::from(first.width), i32::from(first.height));
        let (w1, h1) = (i32::from(second.width), i32::from(second.height));
        // Twice the distance of the centres, which keeps it in integers.
        let cx = 2 * i64::from(left) + i64::from(w1) - i64::from(w0);
        let cy = 2 * i64::from(top) + i64::from(h1) - i64::from(h0);
        let (left, top) = if cx.abs() >= cy.abs() {
            (if cx >= 0 { w0 } else { -w1 }, top.clamp(1 - h1, h0 - 1))
        } else {
            (left.clamp(1 - w1, w0 - 1), if cy >= 0 { h0 } else { -h1 })
        };
        Layout {
            first,
            second,
            left,
            top,
        }
    }

    /// Where the two monitors lie in the desktop picture, which starts at their top left corner.
    pub(crate) fn viewports(self) -> [Viewport; 2] {
        // Both offsets lie within one monitor's size, so they fit u16.
        let x = (-self.left.min(0)) as u16;
        let y = (-self.top.min(0)) as u16;
        [
            Viewport {
                x,
                y,
                width: self.first.width,
                height: self.first.height,
            },
            Viewport {
                x: (i32::from(x) + self.left) as u16,
                y: (i32::from(y) + self.top) as u16,
                width: self.second.width,
                height: self.second.height,
            },
        ]
    }

    /// The desktop that holds both monitors, for a connection that starts with this layout.
    fn bounds(self) -> Display {
        let [first, second] = self.viewports();
        let end = |start: u16, length: u16| u32::from(start) + u32::from(length);
        let side = |a: u32, b: u32| u16::try_from(a.max(b)).unwrap_or(u16::MAX);
        Display::clamped(
            side(end(first.x, first.width), end(second.x, second.width)),
            side(end(first.y, first.height), end(second.y, second.height)),
            self.first.scale,
        )
    }

    /// The Display Control message of this layout.
    fn message(self) -> ironrdp_pdu::EncodeResult<DisplayControlMonitorLayout> {
        let entry = |display: Display, entry: MonitorLayoutEntry| -> ironrdp_pdu::EncodeResult<_> {
            Ok(entry
                .with_desktop_scale_factor(display.scale)?
                .with_device_scale_factor(DeviceScaleFactor::from_desktop_scale_factor(
                    display.scale,
                )))
        };
        let first = entry(
            self.first,
            MonitorLayoutEntry::new_primary(self.first.width.into(), self.first.height.into())?,
        )?;
        let second = entry(
            self.second,
            MonitorLayoutEntry::new_secondary(self.second.width.into(), self.second.height.into())?
                .with_position(self.left, self.top)?,
        )?;
        DisplayControlMonitorLayout::new(&[first, second])
    }
}

/// What the webview asks the server for: one monitor, or two across a detached window each.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Desktop {
    One(Display),
    Two(Layout),
}

impl Desktop {
    /// The desktop a new connection starts with: two monitors start as the desktop around both,
    /// and get their layout once the connection is live.
    fn start(self) -> Display {
        match self {
            Desktop::One(display) => display,
            Desktop::Two(layout) => layout.bounds(),
        }
    }

    fn scale(self) -> u32 {
        match self {
            Desktop::One(display) => display.scale,
            Desktop::Two(layout) => layout.first.scale,
        }
    }
}

impl Default for Desktop {
    fn default() -> Self {
        Desktop::One(Display::default())
    }
}

/// Why a session ended: the `code` of the `failed` and `disconnected` phases.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub(crate) enum Code {
    /// TLS failed for another reason than the pin.
    Tls,
    /// The server refused the credentials.
    Auth,
    /// The server refused the logon after the credentials.
    Logon,
    /// The picture stopped and the reconnects did not bring it back.
    Watchdog,
    /// The server sent the session to another target.
    Redirect,
    Panic,
    /// No connection came about.
    Connect,
    /// The user or the webview ended the session.
    Closed,
    /// The server ended the session.
    Server,
    /// The connection broke.
    Network,
}

/// A phase of the session; the last one ends it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum Report {
    Connecting,
    Connected,
    Reconnecting,
    /// The pin refused the server's certificate; the user may confirm it and start again.
    Certificate(CertProblem),
    Disconnected(Code),
    Failed(Code),
}

impl Report {
    pub(crate) fn ends(&self) -> bool {
        matches!(
            self,
            Report::Certificate(_) | Report::Disconnected(_) | Report::Failed(_)
        )
    }
}

#[derive(Debug, PartialEq, Eq)]
enum Flow {
    Continue,
    Report(Report),
    /// Replace the connection with a new one.
    Reconnect,
    End(Report),
}

/// What the session knows between the events: the picture, the watchdog and what the server last
/// heard from the webview.
#[derive(Default)]
struct Machine {
    frames: Frames,
    watchdog: Watchdog,
    cert: CertReport,
    /// Between `Connected` and the loss of the connection; only then does input go to the server.
    live: bool,
    /// The server refused the logon, which explains the end that follows.
    logon_failed: bool,
    /// The buttons the server last heard pressed.
    buttons: u8,
    /// The desktop the webview asked for last; a new connection starts with it.
    display: Desktop,
    /// The desktop the server has or was last asked for.
    applied: Desktop,
    /// The desktop IronRDP connects again with: the start size of the attempt, or the size of a
    /// resize it fell back to reconnecting for. A resize that worked in place leaves it alone.
    configured: Desktop,
    last: Option<Report>,
}

impl Machine {
    /// `report`, unless it repeats the last one (each automatic reconnect attempt reports again).
    fn report(&mut self, report: Report) -> Option<Report> {
        if self.last.as_ref() == Some(&report) {
            return None;
        }
        self.last = Some(report.clone());
        Some(report)
    }

    fn flow(&mut self, report: Report) -> Flow {
        match self.report(report) {
            Some(report) => Flow::Report(report),
            None => Flow::Continue,
        }
    }

    /// A new attempt connects with the desktop the webview asked for.
    fn started(&mut self) {
        self.applied = Desktop::One(self.display.start());
        self.configured = self.applied;
    }

    /// The desktop to ask the server for: the one the webview wants, if the live connection has
    /// another.
    fn size_due(&self) -> Option<Desktop> {
        (self.live && self.display != self.applied).then_some(self.display)
    }

    fn on_event(&mut self, event: RdpOutputEvent, now: Instant) -> Flow {
        match event {
            RdpOutputEvent::Connected | RdpOutputEvent::AutoReconnected => {
                self.live = true;
                self.logon_failed = false;
                self.flow(Report::Connected)
            }
            RdpOutputEvent::LoginComplete => {
                self.watchdog.login_complete(now);
                Flow::Continue
            }
            RdpOutputEvent::DesktopUpdate(update) => {
                self.frames.apply(update);
                self.watchdog.frame();
                Flow::Continue
            }
            RdpOutputEvent::AutoReconnecting { response, .. } => {
                // IronRDP waits for this answer; the watchdog decides when reconnecting is futile.
                let _ = response.send(AutoReconnectDecision::Continue);
                self.applied = self.configured;
                self.lose();
                self.watchdog.reconnecting();
                self.flow(Report::Reconnecting)
            }
            RdpOutputEvent::NetworkCharacteristics {
                bandwidth_kbps,
                average_rtt_ms,
                ..
            } => {
                self.frames.network(Some(average_rtt_ms), bandwidth_kbps);
                Flow::Continue
            }
            RdpOutputEvent::LogonError(info) => {
                if logon_fails(info.error_type) {
                    log::warn!(
                        "the RDP server refused the logon: {:?} ({:?})",
                        info.error_type,
                        info.error_data
                    );
                    self.logon_failed = true;
                } else {
                    log::info!(
                        "logon notice of the RDP server: {:?} ({:?})",
                        info.error_type,
                        info.error_data
                    );
                }
                Flow::Continue
            }
            RdpOutputEvent::DisplayResizeFallback(reason) => {
                // The server cannot resize the session in place: IronRDP connects again with the
                // new size and reports `Connected` once that session is up.
                log::info!("the RDP session reconnects to resize its desktop: {reason:?}");
                // IronRDP takes over the size of the resize, not its scale; a layout it connects
                // again with as a whole.
                self.configured = match self.applied {
                    Desktop::One(display) => Desktop::One(Display {
                        scale: self.configured.scale(),
                        ..display
                    }),
                    two @ Desktop::Two(_) => two,
                };
                self.applied = self.configured;
                self.lose();
                self.watchdog.reconnecting();
                self.flow(Report::Reconnecting)
            }
            RdpOutputEvent::ServerRedirected { target } => {
                // IronRDP connects to the new target in the same task. Ending here drops that
                // attempt at its next await, which comes before TLS and the credentials; the pin
                // callback would refuse a later handshake with another endpoint as well.
                log::warn!(
                    "the RDP server redirected the session to {target:?}; embedded sessions do \
                     not follow redirects"
                );
                Flow::End(Report::Failed(Code::Redirect))
            }
            RdpOutputEvent::ConnectionFailure(error) => {
                log::warn!("the RDP connection failed: {}", error.report());
                let failed = Report::Failed(failure(&error));
                Flow::End(self.ended(failed))
            }
            RdpOutputEvent::Terminated(result) => {
                let ended = terminated(result);
                Flow::End(self.ended(ended))
            }
            RdpOutputEvent::MonitorLayoutRejected => {
                // The session keeps its desktop; both screens show it as one again.
                log::warn!("the RDP server cannot show the session across two monitors");
                self.frames.set_layout(None);
                Flow::Continue
            }
            _ => Flow::Continue,
        }
    }

    /// IronRDP's events stopped without a last one.
    fn lost(&mut self) -> Flow {
        Flow::End(self.ended(Report::Disconnected(Code::Network)))
    }

    /// `otherwise`, unless a refused certificate or logon explains the end.
    fn ended(&mut self, otherwise: Report) -> Report {
        if let Some(problem) = self.cert.take() {
            return Report::Certificate(problem);
        }
        if self.logon_failed {
            return Report::Failed(Code::Logon);
        }
        otherwise
    }

    /// The connection is gone: the next one starts without input, without pressed buttons and
    /// without the measurements of this one.
    fn lose(&mut self) {
        self.live = false;
        self.buttons = 0;
        self.frames.network(None, None);
    }

    fn tick(&mut self, now: Instant) -> Flow {
        match self.watchdog.tick(now) {
            Verdict::Ok => Flow::Continue,
            Verdict::Reconnect => {
                log::warn!("the RDP session shows no picture; reconnecting");
                self.lose();
                self.logon_failed = false;
                Flow::Reconnect
            }
            Verdict::GiveUp => {
                log::warn!("the RDP session shows no picture after its reconnects; giving up");
                Flow::End(Report::Failed(Code::Watchdog))
            }
        }
    }

    /// The fast-path events for one message of the webview; none while no connection is live.
    fn input(&mut self, input: Input, now: Instant) -> Vec<FastPathInputEvent> {
        if !self.live {
            return Vec::new();
        }
        match input {
            Input::Key {
                code,
                extended,
                down,
            } => {
                let mut flags = KeyboardFlags::empty();
                if !down {
                    flags |= KeyboardFlags::RELEASE;
                }
                if extended {
                    flags |= KeyboardFlags::EXTENDED;
                }
                if down && !is_modifier(code, extended) {
                    self.watchdog.input_sent(now);
                }
                vec![FastPathInputEvent::KeyboardEvent(flags, code)]
            }
            Input::CtrlAltDel => {
                self.watchdog.input_sent(now);
                let key = |(code, extended): (u8, bool), release: bool| {
                    let mut flags = KeyboardFlags::empty();
                    if release {
                        flags |= KeyboardFlags::RELEASE;
                    }
                    if extended {
                        flags |= KeyboardFlags::EXTENDED;
                    }
                    FastPathInputEvent::KeyboardEvent(flags, code)
                };
                CTRL_ALT_DEL
                    .into_iter()
                    .map(|code| key(code, false))
                    .chain(CTRL_ALT_DEL.into_iter().rev().map(|code| key(code, true)))
                    .collect()
            }
            Input::Mouse {
                x,
                y,
                buttons,
                wheel,
            } => {
                let at = |flags, units| {
                    FastPathInputEvent::MouseEvent(MousePdu {
                        flags,
                        number_of_wheel_rotation_units: units,
                        x_position: x,
                        y_position: y,
                    })
                };
                let buttons = buttons & BUTTON_MASK;
                let mut events = vec![at(PointerFlags::MOVE, 0)];
                for (bit, flag) in BUTTONS {
                    let pressed = buttons & bit != 0;
                    if pressed == (self.buttons & bit != 0) {
                        continue;
                    }
                    if pressed {
                        self.watchdog.input_sent(now);
                        events.push(at(flag | PointerFlags::DOWN, 0));
                    } else {
                        events.push(at(flag, 0));
                    }
                }
                self.buttons = buttons;
                if wheel != 0 {
                    let range = MousePdu::WHEEL_ROTATION_RANGE;
                    let units = wheel.clamp(*range.start(), *range.end());
                    events.push(at(PointerFlags::VERTICAL_WHEEL, units));
                }
                events
            }
            // `forward` resizes; `run` ends the session.
            Input::Size(_) | Input::Layout(_) | Input::Close => Vec::new(),
        }
    }
}

/// Shift, Ctrl, Alt, the Windows keys and the locks: pressing one alone changes no picture.
fn is_modifier(code: u8, extended: bool) -> bool {
    if extended {
        matches!(code, 0x1D | 0x38 | 0x5B | 0x5C)
    } else {
        matches!(code, 0x1D | 0x2A | 0x36 | 0x38 | 0x3A | 0x45 | 0x46)
    }
}

/// Whether a logon notice of the server (MS-RDPBCGR 2.2.10.1.1.4.1.1) refuses the logon. The
/// others inform: `SessionContinue` and `SessionTerminate` come with every logon and logoff.
fn logon_fails(kind: LogonErrorNotificationType) -> bool {
    match kind {
        LogonErrorNotificationType::DisconnectRefused
        | LogonErrorNotificationType::NoPermission
        | LogonErrorNotificationType::AccessDenied => true,
        // NTSTATUS: the severity "error" has both top bits set.
        LogonErrorNotificationType::NtStatus(status) => status >= 0xC000_0000,
        LogonErrorNotificationType::SessionBusyOptions
        | LogonErrorNotificationType::BumpOptions
        | LogonErrorNotificationType::ReconnectOptions
        | LogonErrorNotificationType::SessionTerminate
        | LogonErrorNotificationType::SessionContinue => false,
    }
}

fn failure(error: &ConnectorError) -> Code {
    match error.kind() {
        ConnectorErrorKind::Credssp(_)
        | ConnectorErrorKind::AccessDenied
        | ConnectorErrorKind::EntraAuth(_) => Code::Auth,
        _ if is_tls(error) => Code::Tls,
        _ => Code::Connect,
    }
}

fn is_tls(error: &ConnectorError) -> bool {
    let error: &(dyn std::error::Error + 'static) = error;
    crate::error::find_rustls(Some(error), &|_| Some(())).is_some()
}

fn terminated(result: SessionResult<GracefulDisconnectReason>) -> Report {
    match result {
        Ok(GracefulDisconnectReason::UserInitiated) => Report::Disconnected(Code::Closed),
        Ok(reason) => {
            log::info!("the RDP server ended the session: {reason}");
            Report::Disconnected(Code::Server)
        }
        Err(error) => {
            log::warn!("the RDP session broke: {}", error.report());
            Report::Disconnected(Code::Network)
        }
    }
}

/// The build number the server logs, from the app version the way IronRDP's viewer forms it.
fn client_build() -> u32 {
    let part = |number: &str| number.parse::<u32>().unwrap_or(0);
    part(env!("CARGO_PKG_VERSION_MAJOR")) * 100
        + part(env!("CARGO_PKG_VERSION_MINOR")) * 10
        + part(env!("CARGO_PKG_VERSION_PATCH"))
}

/// The name the server shows for the session: this machine's.
fn client_name() -> String {
    let name = gethostname::gethostname();
    let name = name.to_string_lossy();
    match name.trim() {
        "" => DEFAULT_CLIENT_NAME.to_string(),
        name => name.to_string(),
    }
}

fn platform() -> MajorPlatformType {
    if cfg!(windows) {
        MajorPlatformType::WINDOWS
    } else if cfg!(target_os = "macos") {
        MajorPlatformType::MACINTOSH
    } else {
        MajorPlatformType::UNIX
    }
}

/// The audio of a session for `audio` of its connection. At f96f664 `PlayOnServer` asks the server
/// for no audio at all, like `Disabled` (docs/features/kern-rdp-2.md).
fn audio_mode(audio: Option<RdpAudio>) -> AudioMode {
    // Windows keeps audio off: the probe on a Windows runner did not pass (R-1092), and audio needs
    // a run on a Windows with an audio device first (condition 12 of
    // docs/features/arch-rdp-embedded.md, R-1192).
    if cfg!(windows) {
        return AudioMode::Disabled;
    }
    match audio {
        None | Some(RdpAudio::Local) => AudioMode::RedirectToClient,
        Some(RdpAudio::Remote) => AudioMode::PlayOnServer,
        Some(RdpAudio::Off) => AudioMode::Disabled,
    }
}

/// What the server leaves out of the desktop for `profile`; `Auto` is `Lan`
/// (docs/features/kern-rdp-1.md).
fn performance_flags(profile: RdpPerformanceProfile) -> PerformanceFlags {
    match profile {
        RdpPerformanceProfile::Auto | RdpPerformanceProfile::Lan => {
            PerformanceFlags::ENABLE_FONT_SMOOTHING | PerformanceFlags::ENABLE_DESKTOP_COMPOSITION
        }
        RdpPerformanceProfile::Broadband => {
            PerformanceFlags::DISABLE_WALLPAPER
                | PerformanceFlags::DISABLE_FULLWINDOWDRAG
                | PerformanceFlags::DISABLE_MENUANIMATIONS
                | PerformanceFlags::ENABLE_FONT_SMOOTHING
        }
        RdpPerformanceProfile::Low => {
            PerformanceFlags::DISABLE_WALLPAPER
                | PerformanceFlags::DISABLE_FULLWINDOWDRAG
                | PerformanceFlags::DISABLE_MENUANIMATIONS
                | PerformanceFlags::DISABLE_THEMING
                | PerformanceFlags::DISABLE_CURSOR_SHADOW
        }
    }
}

fn config(target: &Target, display: Display, cert: &CertReport) -> Result<Config, String> {
    let builder = ConfigBuilder::new()
        .with_destination(target.destination.clone())
        .with_username(target.username.as_str())
        .with_password(target.password.as_str())
        .with_client_build(client_build())
        .with_client_dir(CLIENT_DIR)
        .with_client_name(client_name())
        .with_platform(platform())
        .with_desktop_width(display.width)
        .with_desktop_height(display.height)
        .with_desktop_scale_factor(display.scale)
        .with_device_scale_factor(display.device_scale())
        .with_performance_flags(performance_flags(target.performance))
        .with_tls(true)
        .with_credssp(target.credssp)
        .with_autologon(true)
        // Bulk compression stays off (spec, condition 1); GFX carries the picture (condition 9).
        .with_compression(false)
        .with_graphics_pipeline(true)
        // Text and pictures over the clipboard, no files (docs/features/kern-rdp-2.md). On Windows
        // start_attempt() brings the backend; elsewhere IronRDP takes the native one.
        .with_clipboard(ClipboardType::Enable)
        .with_audio_mode(audio_mode(target.audio))
        .with_audio_capture(false)
        // Device redirection carries the drive only: no printers, ports or smartcard.
        .with_rdpdr(target.drive.is_some())
        .with_printers(false)
        .with_ports(false);
    let builder = match &target.domain {
        Some(domain) => builder.with_domain(domain.as_str()),
        None => builder,
    };
    let builder = match &target.policy {
        CertPolicy::TrustAll => builder.with_certificate_validation(
            CertificateValidation::DangerouslyAcceptInvalidCertificate,
        ),
        CertPolicy::Pinned { .. } => builder
            .with_certificate_validation(CertificateValidation::Strict)
            .with_certificate_validation_callback(validation_callback(
                target.policy.clone(),
                cert.clone(),
            ))
            .with_certificate_validation_callback_scope(CALLBACK_SCOPE),
    };
    builder.build().map_err(|e| format!("{e:#}"))
}

/// The backend that serves the server's requests on `folder` as the `Downloads` drive. IronRDP
/// resolves every path the server sends beneath `folder` without following links (on Windows
/// without reparse points), so the server reaches nothing outside it.
pub(crate) fn rdpdr_factory(folder: &Path) -> Result<Box<dyn RdpdrBackendFactory + Send>, String> {
    // `RedirectedDrive::new` takes a folder that does not exist.
    if !folder.is_dir() {
        return Err(format!("{} is no folder", folder.display()));
    }
    #[cfg(windows)]
    {
        use ironrdp_rdpdr_native::{RedirectedDrive, WindowsRdpdrBackendFactory};
        let drive = RedirectedDrive::new(DRIVE_ID, DRIVE_NAME, folder, false)
            .map_err(|error| error.to_string())?;
        Ok(Box::new(WindowsRdpdrBackendFactory::new(drive)))
    }
    #[cfg(not(windows))]
    {
        use ironrdp_rdpdr_native::backend::NixRdpdrBackendFactory;
        let Some(base) = folder.to_str() else {
            return Err(format!("{} is no UTF-8 path", folder.display()));
        };
        Ok(Box::new(
            NixRdpdrBackendFactory::new(base.to_string()).with_drive(DRIVE_ID, DRIVE_NAME.into()),
        ))
    }
}

/// One `RdpClient` run; a watchdog reconnect replaces it.
struct Attempt {
    run: JoinHandle<()>,
    events: OutputEventReceiver,
    input: RdpInputSender,
    /// `run` finished; its handle must not be polled again.
    done: bool,
    /// Lives as long as the attempt's client; `None` when the clipboard could not start.
    #[cfg(windows)]
    _clipboard: Option<super::clipboard_win::ClipboardThread>,
}

impl Drop for Attempt {
    fn drop(&mut self) {
        self.run.abort();
    }
}

fn start_attempt(target: &Target, display: Display, cert: &CertReport) -> Result<Attempt, String> {
    let config = config(target, display, cert)?;
    let (sender, events) = output_channel(OUTPUT_QUEUE);
    let client = RdpClient::new(config, sender)
        .with_auto_reconnect(AUTO_RECONNECTS)
        .with_desktop_updates();
    let input = client.input_sender();
    // The start checked the folder; should it be gone since, the attempt shares no drive: without
    // a factory IronRDP opens no device redirection.
    let client = match target.drive.as_deref().map(rdpdr_factory) {
        Some(Ok(factory)) => client.with_rdpdr_backend_factory(factory),
        Some(Err(error)) => {
            log::warn!("the RDP session shares no drive: {error}");
            client
        }
        None => client,
    };
    // Without a factory of its own IronRDP would offer files over the clipboard on Windows.
    #[cfg(windows)]
    let (client, _clipboard) = match super::clipboard_win::ClipboardThread::start(input.clone()) {
        Ok((thread, factory)) => (client.with_cliprdr_backend_factory(factory), Some(thread)),
        Err(error) => {
            log::warn!("the clipboard of the RDP session is off: {error}");
            let factory = ironrdp_cliprdr_native::StubClipboard::new().backend_factory();
            (client.with_cliprdr_backend_factory(factory), None)
        }
    };
    // `RdpClient::run` is not Send: it runs on the session thread's LocalSet.
    let run = tokio::task::spawn_local(client.run());
    Ok(Attempt {
        run,
        events,
        input,
        done: false,
        #[cfg(windows)]
        _clipboard,
    })
}

/// Passes one message of the webview on. The queue slot comes first, so a message that finds the
/// queue full leaves the machine as it was: the next one sends the button changes again.
fn forward(machine: &mut Machine, input: &RdpInputSender, message: Input) {
    match message {
        Input::Size(display) => return resize(machine, input, Desktop::One(display)),
        Input::Layout(layout) => return resize(machine, input, Desktop::Two(layout)),
        _ => {}
    }
    if !machine.live {
        return;
    }
    let Ok(permit) = input.try_reserve() else {
        // Not the message itself: a key event carries what the user types, passwords included.
        log::debug!("the RDP input queue is full; dropped an input event");
        return;
    };
    let events = machine.input(message, Instant::now());
    if !events.is_empty() {
        permit.send(RdpInputEvent::FastPath(events.into()));
    }
}

/// Takes the desktop the webview asks for and passes it on (`send_size`).
fn resize(machine: &mut Machine, input: &RdpInputSender, display: Desktop) {
    machine.display = display;
    send_size(machine, input);
}

/// Asks the live connection for the desktop the webview wants, once; a connection that comes up
/// with another size gets it as soon as it is live. IronRDP holds back a resize until Display
/// Control is ready and keeps only the last one while another is under way.
fn send_size(machine: &mut Machine, input: &RdpInputSender) {
    let Some(desktop) = machine.size_due() else {
        return;
    };
    let (event, viewports) = match desktop {
        Desktop::One(display) => (
            RdpInputEvent::Resize {
                width: display.width,
                height: display.height,
                scale_factor: display.scale,
                physical_size: None,
            },
            None,
        ),
        Desktop::Two(layout) => match layout.message() {
            Ok(message) => (
                RdpInputEvent::MonitorLayout(message),
                Some(layout.viewports()),
            ),
            Err(error) => {
                // `placed` and `clamped` keep to the rules; this would be a bug of ours.
                log::error!("could not build the monitor layout {layout:?}: {error}");
                machine.applied = desktop;
                return;
            }
        },
    };
    let Ok(permit) = input.try_reserve() else {
        // The next message or event of the session tries again.
        log::debug!("the RDP input queue is full; held back a resize");
        return;
    };
    machine.applied = desktop;
    permit.send(event);
    // Each screen shows its monitor from now on; until the server has the new desktop, the part
    // of it that exists.
    machine.frames.set_layout(viewports);
}

/// The end once the WebSocket stopped passing input on.
async fn served(serve: &mut JoinHandle<io::Result<()>>) -> Report {
    match serve.await {
        Ok(Ok(())) => Report::Disconnected(Code::Closed),
        Ok(Err(error)) => {
            log::warn!("the frame WebSocket of the RDP session failed: {error}");
            Report::Failed(Code::Connect)
        }
        Err(error) if error.is_panic() => {
            log::error!("the frame WebSocket of the RDP session panicked: {error}");
            Report::Failed(Code::Panic)
        }
        Err(_) => Report::Disconnected(Code::Closed),
    }
}

async fn run(
    target: Target,
    server: FrameServer,
    frames: Frames,
    mut stop: oneshot::Receiver<()>,
    report: &dyn Fn(Report),
) -> Report {
    if let CertPolicy::Pinned { endpoint, .. } = &target.policy {
        // Strict validation needs the platform's root certificates. Without them IronRDP fails
        // before the pin callback can run, which would look like a network error.
        if let Err(error) =
            ironrdp_tls::rustls_client_config(CertificateValidation::Strict, endpoint, None)
        {
            log::warn!("no TLS validation for the RDP session: {error}");
            return Report::Failed(Code::Tls);
        }
    }
    let mut machine = Machine {
        frames,
        display: Desktop::One(target.display),
        ..Machine::default()
    };
    let (input_tx, mut input_rx) = mpsc::channel(INPUT_QUEUE);
    let mut serve = tokio::task::spawn_local(server.serve(machine.frames.clone(), input_tx));
    let mut tick = tokio::time::interval(TICK);
    tick.set_missed_tick_behavior(MissedTickBehavior::Delay);
    let mut phase = Report::Connecting;
    let end = 'session: loop {
        if let Some(phase) = machine.report(phase.clone()) {
            report(phase);
        }
        machine.started();
        let mut attempt = match start_attempt(&target, machine.display.start(), &machine.cert) {
            Ok(attempt) => attempt,
            Err(error) => {
                log::warn!("could not configure the RDP session: {error}");
                break Report::Failed(Code::Connect);
            }
        };
        loop {
            let flow = tokio::select! {
                biased;
                _ = &mut stop => Flow::End(Report::Disconnected(Code::Closed)),
                joined = &mut attempt.run, if !attempt.done => {
                    attempt.done = true;
                    match joined {
                        Err(error) if error.is_panic() => {
                            log::error!("the RDP client panicked: {error}");
                            Flow::End(Report::Failed(Code::Panic))
                        }
                        // Its last events are still in the queue.
                        _ => Flow::Continue,
                    }
                }
                event = attempt.events.recv() => match event {
                    Some(event) => {
                        let flow = machine.on_event(event, Instant::now());
                        send_size(&mut machine, &attempt.input);
                        flow
                    }
                    None => machine.lost(),
                },
                message = input_rx.recv() => match message {
                    Some(Input::Close) => Flow::End(Report::Disconnected(Code::Closed)),
                    Some(message) => {
                        forward(&mut machine, &attempt.input, message);
                        Flow::Continue
                    }
                    None => Flow::End(served(&mut serve).await),
                },
                _ = tick.tick() => machine.tick(Instant::now()),
            };
            match flow {
                Flow::Continue => {}
                Flow::Report(report_now) => report(report_now),
                Flow::Reconnect => {
                    phase = Report::Reconnecting;
                    continue 'session;
                }
                Flow::End(end) => break 'session end,
            }
        }
    };
    serve.abort();
    end
}

/// Starts a session on a thread of its own and returns the port of its WebSocket, the token of
/// the first login and where the tokens of later ones come from. `report` hears every phase;
/// after the one that ends the session, the thread is gone.
pub(crate) fn spawn(
    target: Target,
    frames: Frames,
    stop: oneshot::Receiver<()>,
    report: impl Fn(Report) + Send + 'static,
) -> Result<(u16, String, Tokens), AppError> {
    let server = FrameServer::bind()?;
    let port = server.port()?;
    let (token, tokens) = (server.token(), server.tokens());
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    std::thread::Builder::new()
        .name("rdp-session".into())
        .spawn(move || {
            let end = catch_unwind(AssertUnwindSafe(|| {
                LocalSet::new().block_on(&runtime, run(target, server, frames, stop, &report))
            }))
            .unwrap_or_else(|_| {
                log::error!("the RDP session thread panicked");
                Report::Failed(Code::Panic)
            });
            report(end);
        })?;
    Ok((port, token, tokens))
}

#[cfg(test)]
mod tests {
    use std::num::NonZeroU16;
    use std::sync::mpsc as std_mpsc;

    use ironrdp_cfg::PropertySetExt as _;
    use ironrdp_client::rdp::DisplayResizeFallbackReason;
    use ironrdp_pdu::geometry::InclusiveRectangle;
    use ironrdp_pdu::rdp::session_info::{LogonErrorNotificationData, LogonErrorsInfo};

    use super::*;
    use crate::rdp_embedded::tofu::CertReason;
    use crate::tofu::fingerprint;

    const WAIT: Duration = Duration::from_secs(10);
    const LATER: Duration = Duration::from_secs(60);

    fn live() -> Machine {
        let mut machine = Machine::default();
        machine.on_event(RdpOutputEvent::Connected, Instant::now());
        machine
    }

    fn picture() -> RdpOutputEvent {
        let update = ironrdp_client::rdp::DesktopUpdate::new(
            vec![0; 4],
            NonZeroU16::new(2).unwrap(),
            NonZeroU16::new(2).unwrap(),
            InclusiveRectangle {
                left: 0,
                top: 0,
                right: 1,
                bottom: 1,
            },
        )
        .unwrap();
        RdpOutputEvent::DesktopUpdate(update)
    }

    fn logon(kind: LogonErrorNotificationType) -> RdpOutputEvent {
        RdpOutputEvent::LogonError(LogonErrorsInfo {
            error_type: kind,
            error_data: LogonErrorNotificationData::SessionId(1),
        })
    }

    fn key(code: u8, extended: bool, down: bool) -> Input {
        Input::Key {
            code,
            extended,
            down,
        }
    }

    fn mouse(buttons: u8, wheel: i16) -> Input {
        Input::Mouse {
            x: 10,
            y: 20,
            buttons,
            wheel,
        }
    }

    fn pointer(flags: PointerFlags, units: i16) -> FastPathInputEvent {
        FastPathInputEvent::MouseEvent(MousePdu {
            flags,
            number_of_wheel_rotation_units: units,
            x_position: 10,
            y_position: 20,
        })
    }

    fn target(destination: Destination, policy: CertPolicy) -> Target {
        Target {
            destination,
            display: Display::default(),
            username: "e2e".into(),
            domain: None,
            password: Zeroizing::new("secret".into()),
            policy,
            audio: None,
            drive: None,
            credssp: true,
            performance: RdpPerformanceProfile::Auto,
        }
    }

    fn pinned(pin: Option<&str>) -> CertPolicy {
        CertPolicy::Pinned {
            identity: "rdp/w-0000000a/192.0.2.10:3389".into(),
            pin: pin.map(str::to_string),
            endpoint: "192.0.2.10:3389".into(),
        }
    }

    #[test]
    fn session_reports_the_phases_of_a_connection_once() {
        let now = Instant::now();
        let mut machine = Machine::default();
        assert_eq!(machine.report(Report::Connecting), Some(Report::Connecting));
        assert_eq!(machine.report(Report::Connecting), None);
        assert_eq!(
            machine.on_event(RdpOutputEvent::Connected, now),
            Flow::Report(Report::Connected)
        );
        assert_eq!(
            machine.on_event(RdpOutputEvent::LoginComplete, now),
            Flow::Continue
        );
        assert_eq!(machine.on_event(picture(), now), Flow::Continue);

        let (response, mut decision) = oneshot::channel();
        let reconnecting = RdpOutputEvent::AutoReconnecting {
            disconnect_reason: 0,
            attempt: 1,
            maximum_attempts: AUTO_RECONNECTS,
            response,
        };
        assert_eq!(
            machine.on_event(reconnecting, now),
            Flow::Report(Report::Reconnecting)
        );
        assert_eq!(decision.try_recv(), Ok(AutoReconnectDecision::Continue));
        assert!(!machine.live);
        let (response, _decision) = oneshot::channel();
        let again = RdpOutputEvent::AutoReconnecting {
            disconnect_reason: 0,
            attempt: 2,
            maximum_attempts: AUTO_RECONNECTS,
            response,
        };
        assert_eq!(machine.on_event(again, now), Flow::Continue);
        assert_eq!(
            machine.on_event(RdpOutputEvent::AutoReconnected, now),
            Flow::Report(Report::Connected)
        );
        assert!(machine.live);
    }

    #[test]
    fn session_reports_a_refused_certificate_instead_of_the_connection_failure() {
        let mut machine = Machine::default();
        let callback = validation_callback(pinned(None), machine.cert.clone());
        assert!(!callback(
            b"certificate",
            "192.0.2.10:3389",
            "unknown issuer"
        ));
        let failure = RdpOutputEvent::ConnectionFailure(ironrdp_connector::general_err!("TLS"));
        assert_eq!(
            machine.on_event(failure, Instant::now()),
            Flow::End(Report::Certificate(CertProblem {
                identity: "rdp/w-0000000a/192.0.2.10:3389".into(),
                fingerprint: fingerprint(b"certificate"),
                reason: CertReason::Unknown,
            }))
        );
    }

    #[test]
    fn session_a_logon_notice_is_no_failure() {
        let now = Instant::now();
        let mut machine = live();
        let notice = logon(LogonErrorNotificationType::SessionContinue);
        assert_eq!(machine.on_event(notice, now), Flow::Continue);
        let ended = RdpOutputEvent::Terminated(Ok(GracefulDisconnectReason::ServerInitiated));
        assert_eq!(
            machine.on_event(ended, now),
            Flow::End(Report::Disconnected(Code::Server))
        );
    }

    #[test]
    fn session_a_refused_logon_explains_the_end() {
        let now = Instant::now();
        let mut machine = live();
        let refused = logon(LogonErrorNotificationType::NtStatus(0xC000_006D));
        assert_eq!(machine.on_event(refused, now), Flow::Continue);
        let ended = RdpOutputEvent::Terminated(Ok(GracefulDisconnectReason::ServerInitiated));
        assert_eq!(
            machine.on_event(ended, now),
            Flow::End(Report::Failed(Code::Logon))
        );
    }

    #[test]
    fn session_tells_refusals_from_notices() {
        use LogonErrorNotificationType as Kind;
        let refusals = [
            Kind::DisconnectRefused,
            Kind::NoPermission,
            Kind::AccessDenied,
            Kind::NtStatus(0xC000_006D),
        ];
        for kind in refusals {
            assert!(logon_fails(kind), "{kind:?}");
        }
        let notices = [
            Kind::SessionBusyOptions,
            Kind::BumpOptions,
            Kind::ReconnectOptions,
            Kind::SessionTerminate,
            Kind::SessionContinue,
            Kind::NtStatus(0x8000_0005),
            Kind::NtStatus(0),
        ];
        for kind in notices {
            assert!(!logon_fails(kind), "{kind:?}");
        }
    }

    #[test]
    fn session_does_not_follow_a_redirect() {
        let redirect = RdpOutputEvent::ServerRedirected {
            target: "198.51.100.7:3389".into(),
        };
        assert_eq!(
            live().on_event(redirect, Instant::now()),
            Flow::End(Report::Failed(Code::Redirect))
        );
    }

    #[test]
    fn session_names_how_a_connection_ended() {
        let now = Instant::now();
        let closed = RdpOutputEvent::Terminated(Ok(GracefulDisconnectReason::UserInitiated));
        assert_eq!(
            live().on_event(closed, now),
            Flow::End(Report::Disconnected(Code::Closed))
        );
        let broken = RdpOutputEvent::Terminated(Err(ironrdp_session::general_err!("read")));
        assert_eq!(
            live().on_event(broken, now),
            Flow::End(Report::Disconnected(Code::Network))
        );
        assert_eq!(
            live().lost(),
            Flow::End(Report::Disconnected(Code::Network))
        );
    }

    #[test]
    fn session_names_the_connect_failures() {
        let tls = io::Error::new(
            io::ErrorKind::InvalidData,
            rustls::Error::General("handshake".into()),
        );
        let tls = ironrdp_connector::custom_err!("TLS upgrade", tls);
        assert_eq!(failure(&tls), Code::Tls);
        let refused = ConnectorError::new("CredSSP", ConnectorErrorKind::AccessDenied);
        assert_eq!(failure(&refused), Code::Auth);
        assert_eq!(
            failure(&ironrdp_connector::general_err!("connect")),
            Code::Connect
        );
    }

    #[test]
    fn session_watchdog_ignores_a_modifier() {
        let now = Instant::now();
        let mut machine = live();
        machine.input(key(0x2A, false, true), now);
        machine.input(key(0x1D, true, true), now);
        assert_eq!(machine.tick(now + LATER), Flow::Continue);
    }

    #[test]
    fn session_reconnects_when_a_key_gets_no_picture() {
        let now = Instant::now();
        let mut machine = live();
        machine.input(key(0x1E, false, true), now);
        assert_eq!(machine.tick(now + LATER), Flow::Reconnect);
        assert!(!machine.live);
    }

    #[test]
    fn session_gives_up_when_no_reconnect_brings_a_picture() {
        let mut now = Instant::now();
        let mut machine = live();
        for _ in 0..10 {
            machine.on_event(RdpOutputEvent::LoginComplete, now);
            now += LATER;
            match machine.tick(now) {
                Flow::Reconnect => continue,
                flow => {
                    assert_eq!(flow, Flow::End(Report::Failed(Code::Watchdog)));
                    return;
                }
            }
        }
        panic!("the watchdog never gave up");
    }

    #[test]
    fn session_watchdog_is_content_with_the_first_picture() {
        let now = Instant::now();
        let mut machine = live();
        machine.on_event(RdpOutputEvent::LoginComplete, now);
        machine.on_event(picture(), now);
        assert_eq!(machine.tick(now + LATER), Flow::Continue);
        assert!(machine.live);
    }

    #[test]
    fn session_watchdog_is_content_with_an_answered_key() {
        let now = Instant::now();
        let mut machine = live();
        machine.input(key(0x1E, false, true), now);
        machine.on_event(picture(), now);
        assert_eq!(machine.tick(now + LATER), Flow::Continue);
    }

    #[test]
    fn session_reconnects_when_a_click_gets_no_picture() {
        let now = Instant::now();
        let mut machine = live();
        machine.input(mouse(1, 0), now);
        assert_eq!(machine.tick(now + LATER), Flow::Reconnect);
    }

    #[test]
    fn session_translates_keys() {
        let now = Instant::now();
        let mut machine = live();
        assert_eq!(
            machine.input(key(0x1E, false, true), now),
            [FastPathInputEvent::KeyboardEvent(
                KeyboardFlags::empty(),
                0x1E
            )]
        );
        assert_eq!(
            machine.input(key(0x48, true, false), now),
            [FastPathInputEvent::KeyboardEvent(
                KeyboardFlags::RELEASE | KeyboardFlags::EXTENDED,
                0x48
            )]
        );
    }

    #[test]
    fn session_sends_button_changes_only() {
        let now = Instant::now();
        let mut machine = live();
        assert_eq!(
            machine.input(mouse(0b1001, 0), now),
            [
                pointer(PointerFlags::MOVE, 0),
                pointer(PointerFlags::LEFT_BUTTON | PointerFlags::DOWN, 0),
            ]
        );
        assert_eq!(
            machine.input(mouse(0b0001, 0), now),
            [pointer(PointerFlags::MOVE, 0)]
        );
        assert_eq!(
            machine.input(mouse(0b0110, 0), now),
            [
                pointer(PointerFlags::MOVE, 0),
                pointer(PointerFlags::LEFT_BUTTON, 0),
                pointer(PointerFlags::RIGHT_BUTTON | PointerFlags::DOWN, 0),
                pointer(PointerFlags::MIDDLE_BUTTON_OR_WHEEL | PointerFlags::DOWN, 0),
            ]
        );
    }

    #[test]
    fn session_clamps_the_wheel() {
        let now = Instant::now();
        let mut machine = live();
        assert_eq!(
            machine.input(mouse(0, i16::MAX), now),
            [
                pointer(PointerFlags::MOVE, 0),
                pointer(PointerFlags::VERTICAL_WHEEL, 255),
            ]
        );
        assert_eq!(
            machine.input(mouse(0, i16::MIN), now),
            [
                pointer(PointerFlags::MOVE, 0),
                pointer(PointerFlags::VERTICAL_WHEEL, -256),
            ]
        );
    }

    #[test]
    fn session_sends_nothing_without_a_live_connection() {
        let now = Instant::now();
        let mut machine = Machine::default();
        assert!(machine.input(key(0x1E, false, true), now).is_empty());
        assert!(machine.input(mouse(1, 0), now).is_empty());
        assert_eq!(machine.buttons, 0);
    }

    #[test]
    fn display_keeps_to_the_limits_of_display_control() {
        assert_eq!(
            Display::clamped(1921, 1080, 150),
            Display {
                width: 1920,
                height: 1080,
                scale: 150
            }
        );
        assert_eq!(
            Display::clamped(0, 0, 0),
            Display {
                width: 200,
                height: 200,
                scale: 100
            }
        );
        assert_eq!(
            Display::clamped(u16::MAX, u16::MAX, u32::MAX),
            Display {
                width: 8192,
                height: 8192,
                scale: 500
            }
        );
        let device = |scale| Display::clamped(1280, 720, scale).device_scale();
        assert_eq!(
            [
                device(100),
                device(139),
                device(140),
                device(179),
                device(180),
                device(500)
            ],
            [100, 100, 140, 140, 180, 180]
        );
    }

    fn sent(receiver: &mut mpsc::Receiver<RdpInputEvent>) -> Vec<(u16, u16, u32)> {
        let mut sizes = Vec::new();
        while let Ok(event) = receiver.try_recv() {
            match event {
                RdpInputEvent::Resize {
                    width,
                    height,
                    scale_factor,
                    physical_size: None,
                } => sizes.push((width, height, scale_factor)),
                other => panic!("expected a resize, got {other:?}"),
            }
        }
        sizes
    }

    #[test]
    fn a_new_size_goes_to_the_server_once() {
        let (input, mut receiver) = RdpInputSender::channel(INPUT_QUEUE);
        let mut machine = live();
        let wide = Display::clamped(1920, 1080, 100);

        forward(&mut machine, &input, Input::Size(Display::default()));
        assert!(sent(&mut receiver).is_empty());
        forward(&mut machine, &input, Input::Size(wide));
        forward(&mut machine, &input, Input::Size(wide));
        assert_eq!(sent(&mut receiver), [(1920, 1080, 100)]);
        forward(
            &mut machine,
            &input,
            Input::Size(Display::clamped(1920, 1080, 150)),
        );
        assert_eq!(sent(&mut receiver), [(1920, 1080, 150)]);
    }

    /// One event as the session loop handles it.
    fn event(machine: &mut Machine, input: &RdpInputSender, event: RdpOutputEvent) -> Flow {
        let flow = machine.on_event(event, Instant::now());
        send_size(machine, input);
        flow
    }

    #[test]
    fn a_size_while_connecting_goes_to_the_server_once_it_is_up() {
        let (input, mut receiver) = RdpInputSender::channel(INPUT_QUEUE);
        let mut machine = Machine::default();
        machine.started();
        let wide = Display::clamped(1920, 1080, 125);

        forward(&mut machine, &input, Input::Size(wide));
        assert!(sent(&mut receiver).is_empty());
        event(&mut machine, &input, RdpOutputEvent::Connected);
        assert_eq!(sent(&mut receiver), [(1920, 1080, 125)]);
        forward(&mut machine, &input, Input::Size(wide));
        event(&mut machine, &input, RdpOutputEvent::LoginComplete);
        assert!(sent(&mut receiver).is_empty());
    }

    #[test]
    fn a_new_attempt_starts_with_the_size_and_sends_it_no_more() {
        let (input, mut receiver) = RdpInputSender::channel(INPUT_QUEUE);
        let mut machine = Machine::default();
        let wide = Display::clamped(1920, 1080, 100);

        forward(&mut machine, &input, Input::Size(wide));
        machine.started();
        event(&mut machine, &input, RdpOutputEvent::Connected);
        assert!(sent(&mut receiver).is_empty());
    }

    #[test]
    fn an_automatic_reconnect_gets_the_size_again() {
        let (input, mut receiver) = RdpInputSender::channel(INPUT_QUEUE);
        let mut machine = live();
        let wide = Display::clamped(1920, 1080, 100);
        forward(&mut machine, &input, Input::Size(wide));
        assert_eq!(sent(&mut receiver), [(1920, 1080, 100)]);

        // IronRDP reconnects with the size it started with, not with one resized in place.
        let (response, _decision) = oneshot::channel();
        let reconnecting = RdpOutputEvent::AutoReconnecting {
            disconnect_reason: 0,
            attempt: 1,
            maximum_attempts: AUTO_RECONNECTS,
            response,
        };
        event(&mut machine, &input, reconnecting);
        assert!(sent(&mut receiver).is_empty());
        event(&mut machine, &input, RdpOutputEvent::AutoReconnected);
        assert_eq!(sent(&mut receiver), [(1920, 1080, 100)]);
    }

    #[test]
    fn a_resize_by_reconnecting_keeps_its_size_for_the_next_reconnect() {
        let (input, mut receiver) = RdpInputSender::channel(INPUT_QUEUE);
        let mut machine = live();
        let wide = Display::clamped(1920, 1080, 100);
        forward(&mut machine, &input, Input::Size(wide));
        assert_eq!(sent(&mut receiver), [(1920, 1080, 100)]);

        let fallback = RdpOutputEvent::DisplayResizeFallback(
            DisplayResizeFallbackReason::CapabilitiesTimedOut,
        );
        event(&mut machine, &input, fallback);
        event(&mut machine, &input, RdpOutputEvent::Connected);
        assert!(sent(&mut receiver).is_empty());
        assert_eq!(machine.configured, Desktop::One(wide));
    }

    /// A whole desktop of `width` x `height` as IronRDP delivers it.
    fn desktop(width: u16, height: u16) -> RdpOutputEvent {
        let update = ironrdp_client::rdp::DesktopUpdate::new(
            vec![0; usize::from(width) * usize::from(height)],
            NonZeroU16::new(width).unwrap(),
            NonZeroU16::new(height).unwrap(),
            InclusiveRectangle {
                left: 0,
                top: 0,
                right: width - 1,
                bottom: height - 1,
            },
        )
        .unwrap();
        RdpOutputEvent::DesktopUpdate(update)
    }

    /// Position, size and scale of a monitor in a layout sent.
    type SentMonitor = ((i32, i32), (u32, u32), Option<u32>);

    /// The monitors of the layouts sent.
    fn sent_layouts(receiver: &mut mpsc::Receiver<RdpInputEvent>) -> Vec<Vec<SentMonitor>> {
        let mut layouts = Vec::new();
        while let Ok(event) = receiver.try_recv() {
            match event {
                RdpInputEvent::MonitorLayout(layout) => layouts.push(
                    layout
                        .monitors()
                        .iter()
                        .map(|monitor| {
                            (
                                monitor.position().unwrap_or((0, 0)),
                                monitor.dimensions(),
                                monitor.desktop_scale_factor(),
                            )
                        })
                        .collect(),
                ),
                other => panic!("expected a monitor layout, got {other:?}"),
            }
        }
        layouts
    }

    fn side_by_side() -> Layout {
        Layout::placed(
            Display::clamped(1920, 1080, 100),
            Display::clamped(1280, 1024, 150),
            1920,
            0,
        )
    }

    #[test]
    fn a_layout_goes_to_the_server_once_and_shows_on_both_screens() {
        let (input, mut receiver) = RdpInputSender::channel(INPUT_QUEUE);
        let mut machine = live();
        let layout = side_by_side();

        forward(&mut machine, &input, Input::Layout(layout));
        forward(&mut machine, &input, Input::Layout(layout));
        assert_eq!(
            sent_layouts(&mut receiver),
            [vec![
                ((0, 0), (1920, 1080), Some(100)),
                ((1920, 0), (1280, 1024), Some(150)),
            ]]
        );
        assert_eq!(
            layout.viewports(),
            [
                Viewport {
                    x: 0,
                    y: 0,
                    width: 1920,
                    height: 1080
                },
                Viewport {
                    x: 1920,
                    y: 0,
                    width: 1280,
                    height: 1024
                },
            ]
        );
        // The frames show each monitor on its screen.
        machine.on_event(desktop(3200, 1080), Instant::now());
        assert_eq!(machine.frames.origin(1), (1920, 0));

        // Back to one monitor: a size of its own, and screen 0 shows the whole desktop again.
        let wide = Display::clamped(1920, 1080, 100);
        forward(&mut machine, &input, Input::Size(wide));
        assert_eq!(sent(&mut receiver), [(1920, 1080, 100)]);
        assert_eq!(machine.frames.origin(1), (0, 0));
    }

    #[test]
    fn a_new_connection_starts_around_both_monitors_and_gets_the_layout_again() {
        let (input, mut receiver) = RdpInputSender::channel(INPUT_QUEUE);
        let mut machine = live();
        // The second monitor left of and above the first: the desktop starts at its corner.
        let layout = Layout::placed(
            Display::clamped(1920, 1080, 100),
            Display::clamped(1280, 1024, 100),
            -1280,
            -200,
        );
        forward(&mut machine, &input, Input::Layout(layout));
        assert_eq!(
            sent_layouts(&mut receiver),
            [vec![
                ((0, 0), (1920, 1080), Some(100)),
                ((-1280, -200), (1280, 1024), Some(100)),
            ]]
        );
        assert_eq!(
            machine.display.start(),
            Display {
                width: 3200,
                height: 1280,
                scale: 100
            }
        );

        // A new attempt connects with the desktop around both and sends the layout once live.
        machine.lose();
        machine.started();
        assert_eq!(machine.applied, Desktop::One(machine.display.start()));
        event(&mut machine, &input, RdpOutputEvent::Connected);
        assert_eq!(sent_layouts(&mut receiver).len(), 1);

        // A resize that fell back to reconnecting connects again with the layout itself.
        let fallback = RdpOutputEvent::DisplayResizeFallback(
            DisplayResizeFallbackReason::CapabilitiesTimedOut,
        );
        event(&mut machine, &input, fallback);
        event(&mut machine, &input, RdpOutputEvent::Connected);
        assert!(sent_layouts(&mut receiver).is_empty());
        assert_eq!(machine.configured, Desktop::Two(layout));
    }

    #[test]
    fn a_rejected_layout_shows_the_desktop_on_one_screen_again() {
        let (input, mut receiver) = RdpInputSender::channel(INPUT_QUEUE);
        let mut machine = live();
        forward(&mut machine, &input, Input::Layout(side_by_side()));
        assert_eq!(sent_layouts(&mut receiver).len(), 1);
        machine.on_event(desktop(3200, 1080), Instant::now());
        assert_eq!(machine.frames.origin(1), (1920, 0));

        let flow = event(&mut machine, &input, RdpOutputEvent::MonitorLayoutRejected);
        assert_eq!(flow, Flow::Continue);
        assert_eq!(machine.frames.origin(1), (0, 0));
        assert!(
            sent_layouts(&mut receiver).is_empty(),
            "the layout went again"
        );
    }

    // MS-RDPEDISP: one primary at (0, 0), no overlap, the second touching it. `placed` keeps
    // to that wherever the client's second screen lies, and so does its message.
    #[test]
    fn a_placed_layout_keeps_to_the_rules_wherever_the_second_screen_lies() {
        let sizes = [
            (200, 200),
            (1920, 1080),
            (1080, 1920),
            (8192, 8192),
            (1280, 1024),
        ];
        let offsets = [
            -20000, -8192, -1921, -1080, -1, 0, 1, 1079, 1920, 8192, 20000,
        ];
        for (w0, h0) in sizes {
            for (w1, h1) in sizes {
                for left in offsets {
                    for top in offsets {
                        let first = Display::clamped(w0, h0, 100);
                        let second = Display::clamped(w1, h1, 180);
                        let layout = Layout::placed(first, second, left, top);
                        assert!(layout.message().is_ok(), "{layout:?} breaks MS-RDPEDISP");
                        let start = layout.bounds();
                        assert!(start.width >= MIN_SIDE && start.height >= MIN_SIDE);
                    }
                }
            }
        }
        // The second screen lies where the client's does, on the side it lies on most.
        let first = Display::clamped(1920, 1080, 100);
        let second = Display::clamped(1280, 1024, 100);
        let place = |left, top| {
            let [a, b] = Layout::placed(first, second, left, top).viewports();
            (
                i32::from(b.x) - i32::from(a.x),
                i32::from(b.y) - i32::from(a.y),
            )
        };
        assert_eq!(place(1920, 0), (1920, 0));
        assert_eq!(place(1900, 30), (1920, 30));
        assert_eq!(place(-1280, 56), (-1280, 56));
        assert_eq!(place(300, 1080), (300, 1080));
        assert_eq!(place(0, -1024), (0, -1024));
        // A gap or an overlap closes; a screen past the corner slides back to touch.
        assert_eq!(place(2500, 0), (1920, 0));
        assert_eq!(place(100, 100), (-1280, 100));
        assert_eq!(place(1920, 5000), (1919, 1080));
    }

    #[test]
    fn a_size_that_finds_the_queue_full_is_not_taken_for_sent() {
        let (input, mut receiver) = RdpInputSender::channel(1);
        let mut machine = live();
        let wide = Display::clamped(1920, 1080, 100);
        forward(
            &mut machine,
            &input,
            Input::Size(Display::clamped(1600, 900, 100)),
        );

        forward(&mut machine, &input, Input::Size(wide));
        assert_eq!(sent(&mut receiver), [(1600, 900, 100)]);
        forward(&mut machine, &input, Input::Size(wide));
        assert_eq!(sent(&mut receiver), [(1920, 1080, 100)]);
    }

    #[test]
    fn a_resize_by_reconnecting_is_a_reconnect_not_a_failure() {
        let mut machine = live();
        let now = Instant::now();
        machine.watchdog.login_complete(now);

        let fallback = RdpOutputEvent::DisplayResizeFallback(
            DisplayResizeFallbackReason::DisplayControlUnavailable,
        );
        assert_eq!(
            machine.on_event(fallback, now),
            Flow::Report(Report::Reconnecting)
        );
        assert!(!machine.live);
        // IronRDP's new connection is no stall of the old one.
        assert_eq!(machine.tick(now + LATER), Flow::Continue);
        assert_eq!(
            machine.on_event(RdpOutputEvent::Connected, now),
            Flow::Report(Report::Connected)
        );
        assert!(machine.live);
    }

    #[test]
    fn session_starts_with_the_size_the_webview_asked_for() {
        let destination = Destination::from_parts("192.0.2.10", 3389);
        let config = config(
            &target(destination, CertPolicy::TrustAll),
            Display::clamped(1920, 1200, 150),
            &CertReport::default(),
        )
        .unwrap();
        let connector = config.connector();
        assert_eq!(
            (connector.desktop_size.width, connector.desktop_size.height),
            (1920, 1200)
        );
        assert_eq!(connector.desktop_scale_factor, 150);
        assert_eq!(connector.device_scale_factor, Some(140));
    }

    #[test]
    fn session_configures_tls_gfx_and_its_channels() {
        let destination = Destination::from_parts("192.0.2.10", 3389);
        let trusted = config(
            &target(destination.clone(), CertPolicy::TrustAll),
            Display::default(),
            &CertReport::default(),
        )
        .unwrap();
        let connector = trusted.connector();
        assert_eq!(
            (connector.desktop_size.width, connector.desktop_size.height),
            (DESKTOP_WIDTH, DESKTOP_HEIGHT)
        );
        assert!(connector.enable_tls);
        assert!(connector.enable_credssp);
        assert!(!connector.enable_standard_rdp_security);
        assert_eq!(connector.compression_type, None);
        assert!(connector.support_dyn_vc_gfx_protocol);
        assert_eq!(trusted.channels().clipboard, ClipboardType::Enable);
        let rdpdr = &trusted.channels().rdpdr;
        assert!(!rdpdr.enabled);
        assert!(!rdpdr.printers);
        assert!(!rdpdr.ports);
        assert_eq!(
            trusted.certificate_validation(),
            CertificateValidation::DangerouslyAcceptInvalidCertificate
        );
        assert!(trusted.certificate_validation_callback().is_none());

        let pinned = config(
            &target(destination, pinned(None)),
            Display::default(),
            &CertReport::default(),
        )
        .unwrap();
        assert_eq!(
            pinned.certificate_validation(),
            CertificateValidation::Strict
        );
        assert!(pinned.certificate_validation_callback().is_some());
        assert_eq!(
            pinned.certificate_validation_callback_scope(),
            ironrdp_tls::CertificateValidationCallbackScope::AllCertificates
        );
    }

    #[test]
    fn session_asks_the_server_for_the_desktop_of_its_profile() {
        let flags = |profile| {
            let mut target = target(
                Destination::from_parts("192.0.2.10", 3389),
                CertPolicy::TrustAll,
            );
            target.performance = profile;
            config(&target, Display::default(), &CertReport::default())
                .unwrap()
                .connector()
                .performance_flags
        };
        let full =
            PerformanceFlags::ENABLE_FONT_SMOOTHING | PerformanceFlags::ENABLE_DESKTOP_COMPOSITION;
        assert_eq!(flags(RdpPerformanceProfile::Auto), full);
        assert_eq!(flags(RdpPerformanceProfile::Lan), full);
        let broadband = flags(RdpPerformanceProfile::Broadband);
        assert!(broadband.contains(PerformanceFlags::DISABLE_WALLPAPER));
        assert!(!broadband.contains(PerformanceFlags::DISABLE_THEMING));
        let low = flags(RdpPerformanceProfile::Low);
        for off in [
            PerformanceFlags::DISABLE_WALLPAPER,
            PerformanceFlags::DISABLE_THEMING,
            PerformanceFlags::DISABLE_MENUANIMATIONS,
            PerformanceFlags::DISABLE_FULLWINDOWDRAG,
        ] {
            assert!(low.contains(off), "{off:?} in {low:?}");
        }
        assert!(!low.contains(PerformanceFlags::ENABLE_FONT_SMOOTHING));
        assert!(!low.contains(PerformanceFlags::ENABLE_DESKTOP_COMPOSITION));
    }

    #[test]
    fn session_sends_ctrl_alt_del_as_one_key_sequence() {
        let mut machine = live();
        let now = Instant::now();
        let press = |code| FastPathInputEvent::KeyboardEvent(KeyboardFlags::empty(), code);
        let release = |code| FastPathInputEvent::KeyboardEvent(KeyboardFlags::RELEASE, code);
        let del = |flags| FastPathInputEvent::KeyboardEvent(KeyboardFlags::EXTENDED | flags, 0x53);
        assert_eq!(
            machine.input(Input::CtrlAltDel, now),
            [
                press(0x1D),
                press(0x38),
                del(KeyboardFlags::empty()),
                del(KeyboardFlags::RELEASE),
                release(0x38),
                release(0x1D),
            ]
        );
        // The secure attention screen is a picture the key sequence must bring.
        assert_eq!(machine.tick(now + LATER), Flow::Reconnect);

        let mut offline = Machine::default();
        assert!(offline.input(Input::CtrlAltDel, now).is_empty());
    }

    #[test]
    fn session_stats_forget_the_measurements_of_a_lost_connection() {
        let mut machine = live();
        let now = Instant::now();
        machine.on_event(picture(), now);
        let stats = |machine: &Machine| -> serde_json::Value {
            serde_json::from_str(
                &machine
                    .frames
                    .take_stats(0, Duration::from_secs(1))
                    .unwrap(),
            )
            .unwrap()
        };
        machine.on_event(
            RdpOutputEvent::NetworkCharacteristics {
                base_rtt_ms: Some(5),
                bandwidth_kbps: Some(80_000),
                average_rtt_ms: 9,
            },
            now,
        );
        let measured = stats(&machine);
        assert_eq!(
            (measured["rtt_ms"].as_u64(), measured["mbps"].as_f64()),
            (Some(9), Some(80.0))
        );

        // A watchdog reconnect and one of IronRDP's own both start without them.
        assert_eq!(machine.tick(now + LATER), Flow::Continue);
        machine.input(key(0x1E, false, true), now + LATER);
        assert_eq!(machine.tick(now + LATER + LATER), Flow::Reconnect);
        let after = stats(&machine);
        assert!(
            after.get("rtt_ms").is_none() && after.get("mbps").is_none(),
            "{after}"
        );
        assert_eq!(
            (after["width"].as_u64(), after["height"].as_u64()),
            (Some(2), Some(2))
        );

        let mut machine = live();
        machine.on_event(picture(), now);
        machine.on_event(
            RdpOutputEvent::NetworkCharacteristics {
                base_rtt_ms: None,
                bandwidth_kbps: None,
                average_rtt_ms: 30,
            },
            now,
        );
        let (response, _answer) = oneshot::channel();
        machine.on_event(
            RdpOutputEvent::AutoReconnecting {
                disconnect_reason: 0,
                attempt: 1,
                maximum_attempts: 3,
                response,
            },
            now,
        );
        assert!(stats(&machine).get("rtt_ms").is_none());
    }

    #[test]
    fn session_goes_without_credssp_only_when_nla_is_off() {
        let mut tls_only = target(
            Destination::from_parts("192.0.2.10", 3389),
            CertPolicy::TrustAll,
        );
        tls_only.credssp = false;
        let config = config(&tls_only, Display::default(), &CertReport::default()).unwrap();
        let connector = config.connector();
        assert!(connector.enable_tls);
        assert!(!connector.enable_credssp);
        assert!(!connector.enable_standard_rdp_security);
    }

    #[test]
    fn session_redirects_devices_only_for_a_drive() {
        let mut shared = target(
            Destination::from_parts("192.0.2.10", 3389),
            CertPolicy::TrustAll,
        );
        shared.drive = Some(std::env::temp_dir());
        let config = config(&shared, Display::default(), &CertReport::default()).unwrap();
        let rdpdr = &config.channels().rdpdr;
        assert!(rdpdr.enabled);
        assert!(!rdpdr.printers);
        assert!(!rdpdr.ports);
    }

    #[test]
    fn drive_backend_announces_the_downloads_folder_only() {
        let folder = std::env::temp_dir().join(format!("ah-rdp-drive-{}", std::process::id()));
        std::fs::create_dir_all(&folder).unwrap();
        let product = rdpdr_factory(&folder)
            .map(|factory| factory.build_rdpdr_backend().map_err(|e| e.to_string()));
        let _ = std::fs::remove_dir_all(&folder);
        let product = match product {
            Ok(Ok(product)) => product,
            Ok(Err(error)) | Err(error) => panic!("no drive backend: {error}"),
        };
        let drives: Vec<_> = product
            .initial_drives()
            .iter()
            .map(|drive| (drive.device_id(), drive.name().to_string()))
            .collect();
        assert_eq!(drives, [(DRIVE_ID, DRIVE_NAME.to_string())]);
        assert!(product.printers().is_empty());
        assert!(product.ports().is_empty());
    }

    #[test]
    fn drive_backend_refuses_a_missing_folder() {
        let folder = std::env::temp_dir().join(format!("ah-rdp-no-drive-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&folder);
        assert!(rdpdr_factory(&folder).is_err());
    }

    /// The channel, the client info and the property `config()` derives from one audio mode.
    fn audio_of(audio: Option<RdpAudio>) -> (bool, bool, bool, Option<AudioMode>) {
        let mut target = target(
            Destination::from_parts("192.0.2.10", 3389),
            CertPolicy::TrustAll,
        );
        target.audio = audio;
        let config = config(&target, Display::default(), &CertReport::default()).unwrap();
        (
            config.channels().sound,
            config.connector().enable_audio_playback,
            config.channels().audio_capture,
            config.properties().audio_mode().unwrap(),
        )
    }

    #[cfg(not(windows))]
    #[test]
    fn session_plays_audio_as_the_connection_options_say() {
        let local = (true, true, false, Some(AudioMode::RedirectToClient));
        assert_eq!(audio_of(None), local);
        assert_eq!(audio_of(Some(RdpAudio::Local)), local);
        assert_eq!(
            audio_of(Some(RdpAudio::Remote)),
            (false, false, false, Some(AudioMode::PlayOnServer))
        );
        assert_eq!(
            audio_of(Some(RdpAudio::Off)),
            (false, false, false, Some(AudioMode::Disabled))
        );
    }

    #[cfg(windows)]
    #[test]
    fn session_keeps_audio_off_on_windows() {
        for audio in [
            None,
            Some(RdpAudio::Local),
            Some(RdpAudio::Remote),
            Some(RdpAudio::Off),
        ] {
            assert_eq!(
                audio_of(audio),
                (false, false, false, Some(AudioMode::Disabled)),
                "{audio:?}"
            );
        }
    }

    fn reports() -> (impl Fn(Report) + Send + 'static, std_mpsc::Receiver<Report>) {
        let (sender, receiver) = std_mpsc::channel();
        (
            move |report| {
                let _ = sender.send(report);
            },
            receiver,
        )
    }

    #[test]
    fn session_fails_without_a_server() {
        let closed = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = closed.local_addr().unwrap().port();
        drop(closed);
        let (report, phases) = reports();
        let (_stop, stop) = oneshot::channel();
        let destination = Destination::from_parts("127.0.0.1", port);
        spawn(
            target(destination, CertPolicy::TrustAll),
            Frames::default(),
            stop,
            report,
        )
        .unwrap();
        assert_eq!(phases.recv_timeout(WAIT), Ok(Report::Connecting));
        assert_eq!(phases.recv_timeout(WAIT), Ok(Report::Failed(Code::Connect)));
    }

    #[test]
    fn session_stop_ends_the_session_and_its_websocket() {
        // Accepts and stays silent: the connection sequence waits for the server's answer.
        let silent = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = silent.local_addr().unwrap().port();
        let (report, phases) = reports();
        let (stop_tx, stop) = oneshot::channel();
        let destination = Destination::from_parts("127.0.0.1", port);
        let (ws_port, _, _) = spawn(
            target(destination, CertPolicy::TrustAll),
            Frames::default(),
            stop,
            report,
        )
        .unwrap();
        assert_eq!(phases.recv_timeout(WAIT), Ok(Report::Connecting));
        stop_tx.send(()).unwrap();
        assert_eq!(
            phases.recv_timeout(WAIT),
            Ok(Report::Disconnected(Code::Closed))
        );
        assert!(std::net::TcpStream::connect(("127.0.0.1", ws_port)).is_err());
        drop(silent);
    }

    /// Against the xrdp container of `scripts/tests/desktop_e2e_rdp_embedded.sh`, which sets the
    /// AH_RDP_E2E_* variables; the fingerprint is that of the container's certificate.
    #[test]
    #[ignore = "needs the xrdp container (scripts/tests/desktop_e2e_rdp_embedded.sh)"]
    fn xrdp_live_session() {
        live_session::run();
    }

    mod live_session {
        use futures_util::{SinkExt, StreamExt};
        use tokio::net::TcpStream;
        use tokio::sync::mpsc::{unbounded_channel, UnboundedReceiver};
        use tokio::time::timeout;
        use tokio_tungstenite::tungstenite::Message;
        use tokio_tungstenite::{client_async, WebSocketStream};

        use super::*;

        type Client = WebSocketStream<TcpStream>;

        const QUIET: Duration = Duration::from_secs(2);

        fn var(name: &str) -> String {
            std::env::var(name).unwrap_or_else(|_| panic!("{name} is not set"))
        }

        struct Live {
            destination: Destination,
            user: String,
            password: String,
            fingerprint: String,
        }

        impl Live {
            fn policy(&self, pin: Option<&str>) -> CertPolicy {
                CertPolicy::Pinned {
                    identity: "rdp/e2e/xrdp".into(),
                    pin: pin.map(str::to_string),
                    endpoint: self.destination.to_string(),
                }
            }

            fn start(&self, pin: Option<&str>) -> Session {
                let target = Target {
                    destination: self.destination.clone(),
                    display: Display::default(),
                    username: self.user.clone(),
                    domain: None,
                    password: Zeroizing::new(self.password.clone()),
                    policy: self.policy(pin),
                    audio: None,
                    drive: None,
                    credssp: true,
                    performance: RdpPerformanceProfile::Auto,
                };
                let (sender, phases) = unbounded_channel();
                let (stop, stop_rx) = oneshot::channel();
                let (port, token, tokens) =
                    spawn(target, Frames::default(), stop_rx, move |report| {
                        let _ = sender.send(report);
                    })
                    .unwrap();
                Session {
                    port,
                    token,
                    tokens,
                    stop: Some(stop),
                    phases,
                }
            }
        }

        struct Session {
            port: u16,
            token: String,
            tokens: Tokens,
            stop: Option<oneshot::Sender<()>>,
            phases: UnboundedReceiver<Report>,
        }

        impl Session {
            async fn phase(&mut self) -> Report {
                timeout(Duration::from_secs(30), self.phases.recv())
                    .await
                    .expect("no phase in time")
                    .expect("the session went away without a last phase")
            }
        }

        async fn connect(port: u16, token: &str) -> Client {
            let tcp = TcpStream::connect(("127.0.0.1", port)).await.unwrap();
            let mut ws = client_async(format!("ws://127.0.0.1:{port}/"), tcp)
                .await
                .unwrap()
                .0;
            ws.send(Message::text(token)).await.unwrap();
            ws
        }

        async fn next_frame(ws: &mut Client) -> Vec<u8> {
            loop {
                match timeout(Duration::from_secs(15), ws.next()).await {
                    Ok(Some(Ok(Message::Binary(frame)))) => return frame.to_vec(),
                    Ok(Some(Ok(Message::Ping(_) | Message::Pong(_)))) => continue,
                    other => panic!("expected a picture, got {other:?}"),
                }
            }
        }

        fn header(frame: &[u8]) -> [u16; 7] {
            std::array::from_fn(|i| u16::from_le_bytes([frame[2 * i], frame[2 * i + 1]]))
        }

        async fn type_a(ws: &mut Client) {
            for down in [true, false] {
                let message = format!(r#"{{"t":"key","code":30,"ext":false,"down":{down}}}"#);
                ws.send(Message::text(message)).await.unwrap();
            }
        }

        /// The server closes the connection: no picture, and the stream ends in time.
        async fn assert_closed(ws: &mut Client) {
            loop {
                match timeout(Duration::from_secs(10), ws.next()).await {
                    Err(_) => panic!("the connection stayed open"),
                    Ok(Some(Ok(Message::Binary(_)))) => panic!("a picture after the end"),
                    Ok(Some(Ok(Message::Close(_)) | Err(_)) | None) => return,
                    Ok(Some(Ok(_))) => continue,
                }
            }
        }

        #[tokio::main(flavor = "current_thread")]
        pub(super) async fn run() {
            let host = var("AH_RDP_E2E_HOST");
            let port: u16 = var("AH_RDP_E2E_PORT").parse().unwrap();
            let live = Live {
                destination: Destination::from_parts(host, port),
                user: var("AH_RDP_E2E_USER"),
                password: var("AH_RDP_E2E_PASSWORD"),
                fingerprint: var("AH_RDP_E2E_FINGERPRINT").to_lowercase(),
            };

            // First contact: no pin, so the user is asked about the container's certificate.
            let mut first = live.start(None);
            assert_eq!(first.phase().await, Report::Connecting);
            match first.phase().await {
                Report::Certificate(problem) => {
                    assert_eq!(problem.reason, CertReason::Unknown);
                    assert_eq!(problem.fingerprint, live.fingerprint);
                }
                other => panic!("expected the certificate phase, got {other:?}"),
            }

            // Pinned: the session connects and streams.
            let mut session = live.start(Some(&live.fingerprint));
            assert_eq!(session.phase().await, Report::Connecting);
            assert_eq!(session.phase().await, Report::Connected);
            let mut stranger = connect(session.port, "wrong-token").await;
            assert_closed(&mut stranger).await;
            let mut ws = connect(session.port, &session.token).await;
            let frame = next_frame(&mut ws).await;
            assert_eq!(header(&frame)[5..], [DESKTOP_WIDTH, DESKTOP_HEIGHT]);
            // Without a receipt nothing more comes, although typing changes the picture.
            type_a(&mut ws).await;
            // The stats come every second as text; only a picture breaks the receipt rule (R-1195).
            let quiet = async {
                loop {
                    match ws.next().await {
                        Some(Ok(Message::Text(_))) => continue,
                        message => break message,
                    }
                }
            };
            if let Ok(message) = timeout(QUIET, quiet).await {
                panic!("a picture without a receipt: {message:?}");
            }
            ws.send(Message::text(r#"{"t":"ack"}"#)).await.unwrap();
            next_frame(&mut ws).await;

            // A resize: the pictures take the new desktop size, without a failed phase.
            ws.send(Message::text(
                r#"{"t":"size","w":1024,"h":768,"scale":100}"#,
            ))
            .await
            .unwrap();
            ws.send(Message::text(r#"{"t":"ack"}"#)).await.unwrap();
            let resized = async {
                loop {
                    // Stats come once a second besides the pictures.
                    let frame = match ws.next().await {
                        Some(Ok(Message::Binary(frame))) => frame,
                        Some(Ok(Message::Text(_) | Message::Ping(_) | Message::Pong(_))) => {
                            continue
                        }
                        other => panic!("expected a picture, got {other:?}"),
                    };
                    if header(&frame)[5..] == [1024, 768] {
                        break;
                    }
                    ws.send(Message::text(r#"{"t":"ack"}"#)).await.unwrap();
                }
            };
            timeout(Duration::from_secs(30), resized)
                .await
                .expect("the desktop never took the new size");
            while let Ok(phase) = session.phases.try_recv() {
                assert!(
                    matches!(phase, Report::Reconnecting | Report::Connected),
                    "a resize ended in {phase:?}"
                );
            }

            // The client goes, the session stays; a new login gets the whole desktop (R-1101).
            ws.close(None).await.unwrap();
            drop(ws);
            let token = session.tokens.renew(0).unwrap();
            let mut ws = connect(session.port, &token).await;
            let whole = async {
                loop {
                    match ws.next().await {
                        Some(Ok(Message::Binary(frame))) => break frame,
                        Some(Ok(Message::Text(_) | Message::Ping(_) | Message::Pong(_))) => {}
                        other => panic!("expected a picture, got {other:?}"),
                    }
                }
            };
            let frame = timeout(Duration::from_secs(15), whole)
                .await
                .expect("no picture after the new login");
            assert_eq!(header(&frame), [1, 0, 0, 1024, 768, 1024, 768]);
            assert!(
                session.phases.try_recv().is_err(),
                "the client going away changed the phase"
            );

            session.stop.take().unwrap().send(()).unwrap();
            assert_eq!(session.phase().await, Report::Disconnected(Code::Closed));
            assert_closed(&mut ws).await;

            // A pin that does not match: the certificate changed.
            let mut changed = live.start(Some(&"0".repeat(64)));
            assert_eq!(changed.phase().await, Report::Connecting);
            match changed.phase().await {
                Report::Certificate(problem) => {
                    assert_eq!(problem.reason, CertReason::Changed);
                    assert_eq!(problem.fingerprint, live.fingerprint);
                }
                other => panic!("expected the certificate phase, got {other:?}"),
            }
        }
    }
}
