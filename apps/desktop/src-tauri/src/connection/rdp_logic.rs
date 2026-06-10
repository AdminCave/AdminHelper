// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! Pure RDP helper logic (size parsing, window sizing, xfreerdp output
//! classification), extracted from `rdp.rs` so it is unit-testable without
//! spawning processes. Compiled on all platforms by design — some helpers are
//! only *called* from the Unix code path, hence the `allow(dead_code)` there.

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
}
