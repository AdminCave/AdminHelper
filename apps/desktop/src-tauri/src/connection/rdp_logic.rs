// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! Pure RDP helper logic (size parsing, window sizing, xfreerdp output
//! classification), extracted from `rdp.rs` so it is unit-testable without
//! spawning processes. Compiled on all platforms by design — some helpers are
//! only *called* from the Unix code path, hence the `allow(dead_code)` there.

use std::io::{ErrorKind, Read};

use crate::error::AppError;
use crate::models::ClientInfo;

const AUTH_FAILED_MESSAGE: &str =
    "RDP Anmeldung fehlgeschlagen. Bitte Benutzer, Passwort und Domaene pruefen.";
const CONNECT_FAILED_MESSAGE: &str =
    "RDP Verbindung fehlgeschlagen. Bitte Host, Port und Netzwerk pruefen.";

/// Classification of an xfreerdp error line.
#[derive(Clone, Copy)]
enum ErrorClass {
    Auth,
    Connect,
}

impl ErrorClass {
    fn message(self) -> &'static str {
        match self {
            ErrorClass::Auth => AUTH_FAILED_MESSAGE,
            ErrorClass::Connect => CONNECT_FAILED_MESSAGE,
        }
    }
}

/// One rule per row: a line matches when it contains *all* needles
/// (case-insensitive). Rows are checked in order, first match wins — the auth
/// rules deliberately come before the broader connect rules (e.g. the plain
/// `errconnect_` catch-all), mirroring the original if-cascade.
const ERROR_RULES: &[(&[&str], ErrorClass)] = &[
    (&["errconnect_logon_failure"], ErrorClass::Auth),
    (&["errconnect_authentication_failed"], ErrorClass::Auth),
    (&["errconnect_password_expired"], ErrorClass::Auth),
    (&["errconnect_account_locked_out"], ErrorClass::Auth),
    (&["errconnect_account_disabled"], ErrorClass::Auth),
    (&["errconnect_username_password_missing"], ErrorClass::Auth),
    (&["nt_status_logon_failure"], ErrorClass::Auth),
    (&["status_logon_failure"], ErrorClass::Auth),
    (&["status_password_expired"], ErrorClass::Auth),
    (&["status_account_locked_out"], ErrorClass::Auth),
    (&["status_account_disabled"], ErrorClass::Auth),
    (&["authentication", "failed"], ErrorClass::Auth),
    (&["logon", "failure"], ErrorClass::Auth),
    (&["logon", "failed"], ErrorClass::Auth),
    (&["errconnect_", "auth"], ErrorClass::Auth),
    (&["credssp", "failed"], ErrorClass::Auth),
    (&["account", "locked"], ErrorClass::Auth),
    (&["password", "expired"], ErrorClass::Auth),
    (&["errconnect_"], ErrorClass::Connect),
    (&["connect", "failed"], ErrorClass::Connect),
    (&["connect", "failure"], ErrorClass::Connect),
    (&["transport", "failed"], ErrorClass::Connect),
    (&["dns", "error"], ErrorClass::Connect),
    (&["name", "resolve", "fail"], ErrorClass::Connect),
    (&["connection timeout"], ErrorClass::Connect),
    (&["connection timed out"], ErrorClass::Connect),
];

/// Heuristic classification of xfreerdp output into a user-facing error
/// message. Returns `None` when no known failure pattern is present.
#[cfg_attr(not(unix), allow(dead_code))]
pub fn parse_freerdp_error(stderr: &[u8]) -> Option<String> {
    let output = String::from_utf8_lossy(stderr);
    for line in output.lines() {
        let lower = line.to_lowercase();
        for (needles, class) in ERROR_RULES {
            if needles.iter().all(|needle| lower.contains(needle)) {
                return Some(class.message().to_string());
            }
        }
    }
    None
}

/// Whether the captured xfreerdp output indicates an established connection.
#[cfg_attr(not(unix), allow(dead_code))]
pub fn buffer_has_connected(buffer: &[u8]) -> bool {
    let output = String::from_utf8_lossy(buffer);
    let lower = output.to_lowercase();
    lower.contains("connected to") || lower.contains("connection established")
}

/// The last `cap` bytes of one xfreerdp output stream, and whether
/// `buffer_has_connected` was ever true for it. The flag sticks: in a long
/// session the marker leaves the tail long before xfreerdp exits.
#[cfg_attr(not(unix), allow(dead_code))]
pub struct OutputTail {
    bytes: Vec<u8>,
    cap: usize,
    connected: bool,
}

#[cfg_attr(not(unix), allow(dead_code))]
impl OutputTail {
    pub fn new(cap: usize) -> Self {
        Self {
            bytes: Vec::new(),
            cap,
            connected: false,
        }
    }

    fn push(&mut self, chunk: &[u8]) {
        self.bytes.extend_from_slice(chunk);
        // Checked before trimming: a chunk as long as `cap` would otherwise cut
        // off the first half of a marker split over two reads.
        if !self.connected && buffer_has_connected(&self.bytes) {
            self.connected = true;
        }
        if self.bytes.len() > self.cap {
            self.bytes.drain(..self.bytes.len() - self.cap);
        }
    }

    fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    fn connected(&self) -> bool {
        self.connected
    }
}

/// Reads `reader` up to EOF or a read error into an `OutputTail`. It never
/// stops earlier: xfreerdp blocks once the pipe it writes to is full.
#[cfg_attr(not(unix), allow(dead_code))]
pub fn drain_into_tail(mut reader: impl Read, cap: usize) -> OutputTail {
    let mut tail = OutputTail::new(cap);
    let mut chunk = [0u8; 8192];
    loop {
        match reader.read(&mut chunk) {
            Ok(0) => break,
            Ok(count) => tail.push(&chunk[..count]),
            Err(error) if error.kind() == ErrorKind::Interrupted => continue,
            Err(_) => break,
        }
    }
    tail
}

/// The message for the end of an interactive xfreerdp run: the first known
/// error line, stderr before stdout; else the connect failure if neither
/// stream ever showed the connection; else none.
#[cfg_attr(not(unix), allow(dead_code))]
pub fn interactive_exit_message(stderr: &OutputTail, stdout: &OutputTail) -> Option<String> {
    parse_freerdp_error(stderr.bytes())
        .or_else(|| parse_freerdp_error(stdout.bytes()))
        .or_else(|| {
            (!stderr.connected() && !stdout.connected()).then(|| CONNECT_FAILED_MESSAGE.to_string())
        })
}

pub fn parse_custom_size(raw: Option<&str>) -> Result<(u32, u32), AppError> {
    let value = raw
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
        .ok_or_else(|| {
            AppError::Validation(
                "Benutzerdefinierte RDP-Groesse fehlt (Format WxH, z.B. 1920x1080)".to_string(),
            )
        })?;
    let lower = value.to_ascii_lowercase();
    let parts: Vec<&str> = lower.split('x').collect();
    if parts.len() != 2 {
        return Err(AppError::Validation(format!(
            "Ungueltige RDP-Groesse '{value}'. Format: WxH (z.B. 1920x1080)"
        )));
    }
    let width: u32 = parts[0].parse().map_err(|_| {
        AppError::Validation(format!(
            "Ungueltige RDP-Breite '{}'. Muss eine Zahl sein.",
            parts[0]
        ))
    })?;
    let height: u32 = parts[1].parse().map_err(|_| {
        AppError::Validation(format!(
            "Ungueltige RDP-Hoehe '{}'. Muss eine Zahl sein.",
            parts[1]
        ))
    })?;
    if !(640..=7680).contains(&width) || !(480..=4320).contains(&height) {
        return Err(AppError::Validation(format!(
            "RDP-Groesse {width}x{height} ausserhalb des gueltigen Bereichs (640x480 bis 7680x4320)"
        )));
    }
    Ok((width, height))
}

#[cfg_attr(not(unix), allow(dead_code))]
pub fn fit_window_size(client: Option<&ClientInfo>) -> (u32, u32) {
    let (screen_w, screen_h) = client
        .and_then(|info| match (info.screen_width, info.screen_height) {
            (Some(w), Some(h)) if w > 0 && h > 0 => Some((w, h)),
            _ => None,
        })
        .unwrap_or((1280, 800));

    let width = ((screen_w as f64) * 0.85) as u32;
    let height = (((screen_h as f64) * 0.85) as u32).saturating_sub(80);
    let width = width.max(1024);
    let height = height.max(720);
    (width, height)
}

#[cfg_attr(not(unix), allow(dead_code))]
pub fn hdpi_scale(client: Option<&ClientInfo>) -> Option<u32> {
    let info = client?;
    let scale_factor = info.scale_factor.unwrap_or(1.0);
    let width = info.screen_width.unwrap_or(0) as f64;
    let height = info.screen_height.unwrap_or(0) as f64;

    let is_hdpi = scale_factor >= 1.5 || (width >= 3000.0 && height >= 1600.0);
    if !is_hdpi {
        return None;
    }

    if scale_factor >= 2.0 || width >= 3800.0 || height >= 2100.0 {
        Some(180)
    } else {
        Some(140)
    }
}

/// True when xfreerdp rejected the `+auth-only` probe flag as an unknown option — i.e. it is too old
/// to support the auth-only precheck, so the check is skipped and the real launch surfaces any auth
/// failure. Both halves are required: an unknown/unrecognized/invalid-option mention AND `auth-only`,
/// so a genuine auth error ("auth-only failed") is not mistaken for an unsupported flag (6.105).
pub fn auth_only_unsupported(output_lower: &str) -> bool {
    ["unknown option", "unrecognized option", "invalid option"]
        .iter()
        .any(|m| output_lower.contains(m))
        && output_lower.contains("auth-only")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn classify(line: &str) -> Option<String> {
        parse_freerdp_error(line.as_bytes())
    }

    #[test]
    fn parse_freerdp_error_classifies_auth_failures() {
        let lines = [
            "[ERROR][com.freerdp.core] - freerdp_set_last_error_ex ERRCONNECT_LOGON_FAILURE [0x00020014]",
            "[ERROR][com.freerdp.core] - freerdp_set_last_error_ex ERRCONNECT_AUTHENTICATION_FAILED [0x00020009]",
            "[ERROR][com.freerdp.core] - freerdp_set_last_error_ex ERRCONNECT_PASSWORD_EXPIRED [0x0002000E]",
            "[ERROR][com.freerdp.core] - freerdp_set_last_error_ex ERRCONNECT_ACCOUNT_LOCKED_OUT [0x00020015]",
            "[ERROR][com.freerdp.core] - freerdp_set_last_error_ex ERRCONNECT_ACCOUNT_DISABLED [0x00020012]",
            "[ERROR][com.winpr.sspi.NTLM] - NT_STATUS_LOGON_FAILURE",
            "[ERROR][com.freerdp.core.nla] - CredSSP authentication failed",
            "[ERROR][com.freerdp.core] - Logon failure: unknown user name or bad password",
            "[WARN][com.freerdp.core] - Account is locked out",
            "[WARN][com.freerdp.core] - Password has expired for this user",
        ];
        for line in lines {
            assert_eq!(
                classify(line).as_deref(),
                Some(AUTH_FAILED_MESSAGE),
                "line: {line}"
            );
        }
    }

    #[test]
    fn parse_freerdp_error_classifies_connect_failures() {
        let lines = [
            "[ERROR][com.freerdp.core] - freerdp_set_last_error_ex ERRCONNECT_CONNECT_FAILED [0x00020006]",
            "[ERROR][com.freerdp.core] - freerdp_set_last_error_ex ERRCONNECT_TLS_CONNECT_FAILED [0x00020008]",
            "[ERROR][com.freerdp.core] - freerdp_set_last_error_ex ERRCONNECT_DNS_NAME_NOT_FOUND [0x00020005]",
            "[ERROR][com.freerdp.core.transport] - transport layer failed to connect",
            "[ERROR][com.freerdp.core] - connection timeout waiting for server",
            "[ERROR][com.freerdp.core] - connection timed out",
            "[ERROR][com.freerdp.core] - DNS error: no address found",
            "[ERROR][com.freerdp.core] - failed to resolve host name",
        ];
        for line in lines {
            assert_eq!(
                classify(line).as_deref(),
                Some(CONNECT_FAILED_MESSAGE),
                "line: {line}"
            );
        }
    }

    #[test]
    fn parse_freerdp_error_prefers_auth_over_generic_errconnect() {
        // ERRCONNECT_LOGON_FAILURE also matches the plain `errconnect_`
        // connect catch-all — the auth rule must win (rule order).
        let line = "[ERROR][com.freerdp.core] - ERRCONNECT_LOGON_FAILURE";
        assert_eq!(classify(line).as_deref(), Some(AUTH_FAILED_MESSAGE));
    }

    #[test]
    fn parse_freerdp_error_uses_first_matching_line() {
        let buffer = b"[INFO][com.freerdp.core] - starting\n\
            [ERROR][com.freerdp.core] - ERRCONNECT_LOGON_FAILURE\n\
            [ERROR][com.freerdp.core] - connection timed out\n";
        assert_eq!(
            parse_freerdp_error(buffer).as_deref(),
            Some(AUTH_FAILED_MESSAGE)
        );
    }

    #[test]
    fn parse_freerdp_error_ignores_benign_output() {
        assert_eq!(
            classify("[INFO][com.freerdp.client.x11] - Connected to 192.168.1.10:3389"),
            None
        );
        assert_eq!(
            classify("[INFO][com.freerdp.gdi] - Local framebuffer format PIXEL_FORMAT_BGRX32"),
            None
        );
        assert_eq!(parse_freerdp_error(b""), None);
    }

    #[test]
    fn buffer_has_connected_detects_connection_lines() {
        assert!(buffer_has_connected(
            b"[INFO][com.freerdp.client.x11] - Connected to 192.168.1.10:3389"
        ));
        assert!(buffer_has_connected(
            b"[INFO][com.freerdp.core] - Connection established"
        ));
        assert!(!buffer_has_connected(
            b"[INFO][com.freerdp.core] - starting"
        ));
        assert!(!buffer_has_connected(b""));
    }

    const CAP: usize = 8192;
    const MARKER: &str = "[INFO][com.freerdp.client.x11] - Connected to 192.0.2.10:3389\n";
    const LOGON_FAILURE: &str = "[ERROR][com.freerdp.core] - freerdp_set_last_error_ex ERRCONNECT_LOGON_FAILURE [0x00020014]\n";
    const TRANSPORT_FAILURE: &str =
        "[ERROR][com.freerdp.core.transport] - transport layer failed to connect\n";

    /// 4 MiB of lines that are neither the marker nor an error.
    fn filler() -> Vec<u8> {
        let line = "[INFO][com.freerdp.gdi] - frame update\n";
        line.repeat(4 * 1024 * 1024 / line.len() + 1).into_bytes()
    }

    fn tail_of(input: &[u8]) -> OutputTail {
        drain_into_tail(input, CAP)
    }

    /// Hands out one byte per read.
    struct OneByteReader<'a>(&'a [u8]);

    impl Read for OneByteReader<'_> {
        fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
            match (self.0.split_first(), buf.first_mut()) {
                (Some((byte, rest)), Some(slot)) => {
                    *slot = *byte;
                    self.0 = rest;
                    Ok(1)
                }
                _ => Ok(0),
            }
        }
    }

    #[test]
    fn drain_into_tail_keeps_only_the_end_of_a_long_stream() {
        let input = filler();
        let tail = tail_of(&input);
        assert!(
            tail.bytes().len() <= CAP,
            "held {} bytes of {}",
            tail.bytes().len(),
            input.len()
        );
        assert!(
            tail.bytes() == &input[input.len() - CAP..],
            "the tail is the end of the stream"
        );
        assert!(!tail.connected());
    }

    #[test]
    fn drain_into_tail_remembers_a_connection_whose_marker_left_the_tail() {
        let mut input = MARKER.as_bytes().to_vec();
        input.extend(filler());
        let stdout = tail_of(&input);
        assert!(
            stdout.bytes().len() <= CAP,
            "held {} bytes",
            stdout.bytes().len()
        );
        assert!(
            !buffer_has_connected(stdout.bytes()),
            "the marker is out of the tail"
        );
        assert!(stdout.connected());
        assert_eq!(
            interactive_exit_message(&OutputTail::new(CAP), &stdout),
            None
        );
    }

    #[test]
    fn interactive_exit_message_finds_an_error_line_at_the_end_of_a_long_stream() {
        let mut input = filler();
        input.extend_from_slice(LOGON_FAILURE.as_bytes());
        let stderr = tail_of(&input);
        assert_eq!(
            interactive_exit_message(&stderr, &OutputTail::new(CAP)).as_deref(),
            Some(AUTH_FAILED_MESSAGE)
        );
    }

    #[test]
    fn interactive_exit_message_without_marker_or_error_is_the_connect_failure() {
        let stderr = tail_of(b"[INFO][com.freerdp.core] - starting\n");
        let stdout = tail_of(b"");
        assert_eq!(
            interactive_exit_message(&stderr, &stdout).as_deref(),
            Some(CONNECT_FAILED_MESSAGE)
        );
    }

    #[test]
    fn interactive_exit_message_takes_the_error_line_of_stderr_first() {
        let auth = tail_of(LOGON_FAILURE.as_bytes());
        let transport = tail_of(TRANSPORT_FAILURE.as_bytes());
        assert_eq!(
            interactive_exit_message(&auth, &transport).as_deref(),
            Some(AUTH_FAILED_MESSAGE)
        );
        assert_eq!(
            interactive_exit_message(&transport, &auth).as_deref(),
            Some(CONNECT_FAILED_MESSAGE)
        );
    }

    #[test]
    fn interactive_exit_message_finds_an_error_line_only_on_stdout() {
        // An auth line: its message differs from the connect-failure fallback,
        // so the result shows that stdout was parsed at all.
        assert_eq!(
            interactive_exit_message(&OutputTail::new(CAP), &tail_of(LOGON_FAILURE.as_bytes()))
                .as_deref(),
            Some(AUTH_FAILED_MESSAGE)
        );
    }

    #[test]
    fn interactive_exit_message_counts_a_marker_only_on_stderr() {
        let stderr = tail_of(MARKER.as_bytes());
        assert!(stderr.connected());
        assert_eq!(
            interactive_exit_message(&stderr, &OutputTail::new(CAP)),
            None
        );
    }

    #[test]
    fn drain_into_tail_sees_a_marker_read_one_byte_at_a_time() {
        let stdout = drain_into_tail(OneByteReader(MARKER.as_bytes()), CAP);
        assert!(stdout.connected());
        assert_eq!(
            interactive_exit_message(&OutputTail::new(CAP), &stdout),
            None
        );
    }

    #[test]
    fn output_tail_sees_a_marker_split_before_a_chunk_that_fills_the_tail() {
        let mut tail = OutputTail::new(CAP);
        tail.push(b"[INFO][com.freerdp.client.x11] - Conn");
        let mut rest = b"ected to 192.0.2.10:3389\n".to_vec();
        rest.resize(CAP, b'.');
        tail.push(&rest);
        assert!(
            !buffer_has_connected(tail.bytes()),
            "the kept tail alone no longer holds the marker"
        );
        assert!(tail.connected());
    }

    #[test]
    fn parse_custom_size_accepts_wxh() {
        assert_eq!(parse_custom_size(Some("1920x1080")).unwrap(), (1920, 1080));
        // Trims whitespace and accepts an upper-case X separator.
        assert_eq!(
            parse_custom_size(Some(" 2560X1440 ")).unwrap(),
            (2560, 1440)
        );
    }

    #[test]
    fn parse_custom_size_accepts_range_boundaries() {
        assert_eq!(parse_custom_size(Some("640x480")).unwrap(), (640, 480));
        assert_eq!(parse_custom_size(Some("7680x4320")).unwrap(), (7680, 4320));
    }

    #[test]
    fn parse_custom_size_rejects_out_of_range() {
        assert!(parse_custom_size(Some("639x480")).is_err());
        assert!(parse_custom_size(Some("640x479")).is_err());
        assert!(parse_custom_size(Some("7681x4320")).is_err());
        assert!(parse_custom_size(Some("7680x4321")).is_err());
    }

    #[test]
    fn parse_custom_size_rejects_malformed_input() {
        assert!(parse_custom_size(None).is_err());
        assert!(parse_custom_size(Some("")).is_err());
        assert!(parse_custom_size(Some("   ")).is_err());
        assert!(parse_custom_size(Some("1920")).is_err());
        assert!(parse_custom_size(Some("1920x1080x60")).is_err());
        assert!(parse_custom_size(Some("widthxheight")).is_err());
        assert!(parse_custom_size(Some("-1920x1080")).is_err());
    }

    fn client(width: u32, height: u32, scale_factor: Option<f64>) -> ClientInfo {
        ClientInfo {
            screen_width: Some(width),
            screen_height: Some(height),
            scale_factor,
        }
    }

    #[test]
    fn hdpi_scale_returns_none_without_client_or_on_low_dpi() {
        assert_eq!(hdpi_scale(None), None);
        assert_eq!(hdpi_scale(Some(&client(1920, 1080, Some(1.0)))), None);
        assert_eq!(hdpi_scale(Some(&ClientInfo::default())), None);
    }

    #[test]
    fn hdpi_scale_maps_moderate_and_high_dpi() {
        // Scale factor drives the decision...
        assert_eq!(hdpi_scale(Some(&client(2560, 1440, Some(1.5)))), Some(140));
        assert_eq!(hdpi_scale(Some(&client(1920, 1080, Some(2.0)))), Some(180));
        // ...and resolution alone classifies when no scale factor is reported.
        assert_eq!(hdpi_scale(Some(&client(3840, 2160, None))), Some(180));
        assert_eq!(hdpi_scale(Some(&client(3000, 1600, None))), Some(140));
    }

    #[test]
    fn fit_window_size_scales_screen_and_enforces_minimums() {
        // No client info: 85% of the 1280x800 fallback, floored at 1024x720.
        assert_eq!(fit_window_size(None), (1088, 720));
        assert_eq!(
            fit_window_size(Some(&client(2560, 1440, None))),
            (2176, 1144)
        );
        // Tiny screens get clamped to the minimum window size.
        assert_eq!(fit_window_size(Some(&client(640, 480, None))), (1024, 720));
    }

    #[test]
    fn auth_only_unsupported_needs_both_an_unknown_option_and_auth_only() {
        // Both signals required: an unknown/unrecognized/invalid-option mention AND "auth-only".
        assert!(auth_only_unsupported("error: unknown option: +auth-only"));
        assert!(auth_only_unsupported("unrecognized option '+auth-only'"));
        assert!(auth_only_unsupported("invalid option auth-only here"));
        // Missing either half -> not the "too old for the probe" case.
        assert!(!auth_only_unsupported("unknown option: --foo")); // no auth-only
        assert!(!auth_only_unsupported("auth-only failed: bad password")); // no unknown-option
        assert!(!auth_only_unsupported(""));
    }
}
