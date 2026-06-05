// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use crate::error::AppError;
use crate::models::{ClientInfo, Connection, RdpErrorPayload, RdpOptions};
#[cfg(any(unix, target_os = "windows"))]
use crate::models::{RdpPerformanceProfile, RdpScalingMode, RdpWindowMode};

#[cfg(unix)]
fn emit_rdp_error(app: &tauri::AppHandle, correlation_id: &str, message: impl Into<String>) {
    let _ = app.emit(
        "rdp-error",
        RdpErrorPayload {
            correlation_id: correlation_id.to_string(),
            message: message.into(),
        },
    );
}

#[cfg(unix)]
use std::io::{Read, Write};
#[cfg(unix)]
use std::net::{TcpStream, ToSocketAddrs};
#[cfg(unix)]
use std::process::{Command, Stdio};
#[cfg(unix)]
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
#[cfg(unix)]
use std::sync::Arc;
#[cfg(unix)]
use std::time::{Duration, Instant};
#[cfg(unix)]
use tauri::Emitter;

#[cfg(unix)]
use crate::terminal::which;

pub fn open_rdp(
    connection: &Connection,
    password: Option<&str>,
    client: Option<&ClientInfo>,
    rdp: RdpOptions,
    ui_language: Option<&str>,
    correlation_id: &str,
    app: &tauri::AppHandle,
) -> Result<(), AppError> {
    let host = connection
        .host
        .as_ref()
        .ok_or_else(|| AppError::Validation("Host fehlt".to_string()))?;
    let port = connection.port.unwrap_or(3389);
    let username = connection
        .username
        .as_ref()
        .map(|value| value.trim())
        .unwrap_or("");
    let domain = connection
        .domain
        .as_ref()
        .map(|value| value.trim())
        .unwrap_or("");

    #[cfg(not(unix))]
    let _ = password;
    #[cfg(not(unix))]
    let _ = app;
    #[cfg(not(unix))]
    let _ = client;
    #[cfg(not(unix))]
    let _ = ui_language;
    #[cfg(not(unix))]
    let _ = rdp.scaling_mode;
    #[cfg(not(unix))]
    let _ = correlation_id;

    #[cfg(target_os = "windows")]
    {
        return open_rdp_windows(
            host,
            port,
            username,
            domain,
            connection,
            rdp.window_mode,
            rdp.custom_size,
            rdp.performance_profile,
        );
    }

    #[cfg(unix)]
    {
        let rdp_binary = detect_rdp_binary()?;
        preflight_rdp(host, port)?;

        let mut args = build_rdp_args(connection, host, port, client, rdp, ui_language)?;
        let password = password.filter(|value| !value.is_empty());

        if let Some(secret) = password {
            if username.is_empty() {
                return Err(AppError::Validation("Benutzer fehlt".to_string()));
            }
            match check_rdp_auth(
                rdp_binary,
                host,
                port,
                username,
                domain,
                connection.trust_cert,
                secret,
            ) {
                Ok(true) => {}
                Ok(false) => {}
                Err(message) => return Err(message),
            }
            args.push("/from-stdin:force".to_string());
            args.push("/log-level:INFO".to_string());
            spawn_rdp_with_password(rdp_binary, args, secret, correlation_id, app)?;
        } else {
            args.push("/log-level:INFO".to_string());
            spawn_rdp_interactive(rdp_binary, args, correlation_id, app)?;
        }
        Ok(())
    }

    #[cfg(not(any(target_os = "windows", unix)))]
    {
        let _ = rdp;
        Err(AppError::Connection(
            "RDP wird auf diesem Betriebssystem nicht unterstuetzt".to_string(),
        ))
    }
}

#[cfg(target_os = "windows")]
fn open_rdp_windows(
    host: &str,
    port: u16,
    username: &str,
    domain: &str,
    connection: &Connection,
    rdp_window_mode: RdpWindowMode,
    rdp_custom_size: Option<&str>,
    rdp_performance_profile: RdpPerformanceProfile,
) -> Result<(), AppError> {
    use std::process::Command;

    let rdp_path = write_rdp_file(
        host,
        port,
        username,
        domain,
        connection.trust_cert,
        rdp_window_mode,
        rdp_custom_size,
        rdp_performance_profile,
    )?;
    Command::new("mstsc").arg(rdp_path).spawn()?;
    Ok(())
}

#[cfg(unix)]
fn detect_rdp_binary() -> Result<&'static str, AppError> {
    if which("xfreerdp3").is_some() {
        Ok("xfreerdp3")
    } else if which("xfreerdp").is_some() {
        Ok("xfreerdp")
    } else {
        Err(AppError::Connection(
            "xfreerdp ist nicht installiert".to_string(),
        ))
    }
}

#[cfg(unix)]
fn build_rdp_args(
    connection: &Connection,
    host: &str,
    port: u16,
    client: Option<&ClientInfo>,
    rdp: RdpOptions,
    ui_language: Option<&str>,
) -> Result<Vec<String>, AppError> {
    let mut args = vec![format!("/v:{host}:{port}")];
    let username = connection
        .username
        .as_ref()
        .map(|value| value.trim())
        .unwrap_or("");
    let domain = connection
        .domain
        .as_ref()
        .map(|value| value.trim())
        .unwrap_or("");

    // Window size + dynamic-resolution depending on the mode
    match rdp.window_mode {
        RdpWindowMode::Fit => {
            let (w, h) = fit_window_size(client);
            args.push(format!("/size:{w}x{h}"));
            args.push("/dynamic-resolution".to_string());
        }
        RdpWindowMode::Fullscreen => {
            args.push("/f".to_string());
        }
        RdpWindowMode::Multimon => {
            args.push("/multimon".to_string());
        }
        RdpWindowMode::Custom => {
            let (w, h) = parse_custom_size(rdp.custom_size)?;
            args.push(format!("/size:{w}x{h}"));
            args.push("/dynamic-resolution".to_string());
        }
    }

    if connection.trust_cert {
        args.push("/cert:ignore".to_string());
    }
    if !username.is_empty() {
        args.push(format!("/u:{username}"));
    }
    if !domain.is_empty() {
        args.push(format!("/d:{domain}"));
    }
    match rdp.scaling_mode {
        RdpScalingMode::Auto => {
            if let Some(scale) = hdpi_scale(client) {
                args.push(format!("/scale:{scale}"));
            }
        }
        RdpScalingMode::Normal => {}
        RdpScalingMode::Hdpi => {
            let scale = hdpi_scale(client).unwrap_or(180);
            args.push(format!("/scale:{scale}"));
        }
    }
    #[cfg(target_os = "linux")]
    args.push(linux_keyboard_layout_arg_from_ui_language(ui_language));

    args.push("+clipboard".to_string());
    let title = crate::validation::sanitize_window_title(&connection.name);
    if !title.is_empty() {
        args.push(format!("/title:{title}"));
    }

    args.extend(performance_args(rdp.performance_profile));

    Ok(args)
}

#[cfg(unix)]
fn fit_window_size(client: Option<&ClientInfo>) -> (u32, u32) {
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

fn parse_custom_size(raw: Option<&str>) -> Result<(u32, u32), AppError> {
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

#[cfg(unix)]
fn performance_args(profile: RdpPerformanceProfile) -> Vec<String> {
    match profile {
        RdpPerformanceProfile::Auto => {
            vec!["/network:auto".to_string(), "+compression".to_string()]
        }
        RdpPerformanceProfile::Lan => vec![
            "/network:lan".to_string(),
            "+compression".to_string(),
            "/gfx:avc444".to_string(),
        ],
        RdpPerformanceProfile::Broadband => vec![
            "/network:wan".to_string(),
            "+compression".to_string(),
            "/gfx:avc420".to_string(),
        ],
        RdpPerformanceProfile::Low => vec![
            "/network:broadband-low".to_string(),
            "+compression".to_string(),
            "-wallpaper".to_string(),
            "-aero".to_string(),
            "-window-drag".to_string(),
            "-menu-anims".to_string(),
            "-themes".to_string(),
            "-fonts".to_string(),
            "/bpp:16".to_string(),
        ],
    }
}

#[cfg(target_os = "linux")]
fn linux_keyboard_layout_arg_from_ui_language(ui_language: Option<&str>) -> String {
    let language = ui_language.unwrap_or("en").trim().to_ascii_lowercase();
    let lang_id: u32 = if language.starts_with("de") {
        0x0407
    } else {
        0x0409
    };
    format!("/kbd:layout:0x{lang_id:08X},lang:0x{lang_id:04X}")
}

#[cfg(unix)]
fn spawn_output_monitor(
    mut reader: impl Read + Send + 'static,
    emitted: Arc<AtomicBool>,
    connected_at_ms: Arc<AtomicU64>,
    started_at: Instant,
    correlation_id: String,
    app: tauri::AppHandle,
) {
    std::thread::spawn(move || {
        let mut buffer: Vec<u8> = Vec::new();
        let mut chunk = [0u8; 1024];
        loop {
            let read = match reader.read(&mut chunk) {
                Ok(0) => break,
                Ok(count) => count,
                Err(_) => break,
            };
            buffer.extend_from_slice(&chunk[..read]);
            if buffer.len() > 8192 {
                buffer.drain(0..buffer.len().saturating_sub(8192));
            }
            if connected_at_ms.load(Ordering::SeqCst) == 0 && buffer_has_connected(&buffer) {
                let elapsed_ms = started_at.elapsed().as_millis() as u64;
                connected_at_ms.store(elapsed_ms, Ordering::SeqCst);
            }
            if let Some(message) = parse_freerdp_error(&buffer) {
                if !emitted.swap(true, Ordering::SeqCst) {
                    emit_rdp_error(&app, &correlation_id, message);
                }
                break;
            }
        }
    });
}

#[cfg(unix)]
fn monitor_rdp_exit(
    mut child: std::process::Child,
    emitted: Arc<AtomicBool>,
    connected_at_ms: Arc<AtomicU64>,
    started_at: Instant,
    correlation_id: String,
    app: tauri::AppHandle,
) {
    // Timeout thread
    {
        let emitted = emitted.clone();
        let connected_at_ms = connected_at_ms.clone();
        let app = app.clone();
        let correlation_id = correlation_id.clone();
        std::thread::spawn(move || {
            std::thread::sleep(Duration::from_secs(12));
            if connected_at_ms.load(Ordering::SeqCst) == 0 && !emitted.swap(true, Ordering::SeqCst)
            {
                emit_rdp_error(
                    &app,
                    &correlation_id,
                    "RDP Anmeldung fehlgeschlagen. Bitte Benutzer, Passwort und Domaene pruefen.",
                );
            }
        });
    }

    // Exit monitoring thread
    std::thread::spawn(move || {
        if child.wait().is_ok() && !emitted.load(Ordering::SeqCst) {
            let elapsed_ms = started_at.elapsed().as_millis() as u64;
            let connected_ms = connected_at_ms.load(Ordering::SeqCst);
            if connected_ms == 0 {
                emit_rdp_error(
                    &app,
                    &correlation_id,
                    "RDP Verbindung fehlgeschlagen. Bitte Host, Port und Netzwerk pruefen.",
                );
            } else if elapsed_ms.saturating_sub(connected_ms) < 8000 {
                emit_rdp_error(
                    &app,
                    &correlation_id,
                    "RDP Anmeldung fehlgeschlagen. Bitte Benutzer, Passwort und Domaene pruefen.",
                );
            }
        }
    });
}

#[cfg(unix)]
fn spawn_rdp_with_password(
    binary: &str,
    args: Vec<String>,
    password: &str,
    correlation_id: &str,
    app: &tauri::AppHandle,
) -> Result<(), AppError> {
    let started_at = Instant::now();
    let mut command = Command::new(binary);
    command
        .args(&args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .env("WLOG_APPENDER", "console");
    let mut child = command.spawn()?;

    if let Some(mut stdin) = child.stdin.take() {
        let payload = format!("{password}\n");
        stdin.write_all(payload.as_bytes())?;
    }

    let emitted = Arc::new(AtomicBool::new(false));
    let connected_at_ms = Arc::new(AtomicU64::new(0));
    let cid = correlation_id.to_string();

    if let Some(stdout) = child.stdout.take() {
        spawn_output_monitor(
            stdout,
            emitted.clone(),
            connected_at_ms.clone(),
            started_at,
            cid.clone(),
            app.clone(),
        );
    }

    if let Some(stderr) = child.stderr.take() {
        spawn_output_monitor(
            stderr,
            emitted.clone(),
            connected_at_ms.clone(),
            started_at,
            cid.clone(),
            app.clone(),
        );
    }

    monitor_rdp_exit(
        child,
        emitted,
        connected_at_ms,
        started_at,
        cid,
        app.clone(),
    );
    Ok(())
}

#[cfg(unix)]
fn spawn_rdp_interactive(
    binary: &str,
    args: Vec<String>,
    correlation_id: &str,
    app: &tauri::AppHandle,
) -> Result<(), AppError> {
    let mut command = Command::new(binary);
    command
        .args(&args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .env("WLOG_APPENDER", "console");
    let child = command.spawn()?;

    let app_handle = app.clone();
    let cid = correlation_id.to_string();
    std::thread::spawn(move || {
        if let Ok(output) = child.wait_with_output() {
            let mut combined = output.stderr;
            combined.extend_from_slice(&output.stdout);
            let parsed = parse_freerdp_error(&combined);
            if let Some(message) = parsed {
                emit_rdp_error(&app_handle, &cid, message);
            } else if !buffer_has_connected(&combined) {
                emit_rdp_error(
                    &app_handle,
                    &cid,
                    "RDP Verbindung fehlgeschlagen. Bitte Host, Port und Netzwerk pruefen.",
                );
            }
        }
    });
    Ok(())
}

#[cfg(unix)]
pub fn parse_freerdp_error(stderr: &[u8]) -> Option<String> {
    let output = String::from_utf8_lossy(stderr);
    for line in output.lines() {
        let lower = line.to_lowercase();
        let is_auth = lower.contains("authentication") && lower.contains("failed");
        let is_logon =
            lower.contains("logon") && (lower.contains("failure") || lower.contains("failed"));
        let has_errconnect = lower.contains("errconnect_");

        if lower.contains("errconnect_logon_failure")
            || lower.contains("errconnect_authentication_failed")
            || lower.contains("errconnect_password_expired")
            || lower.contains("errconnect_account_locked_out")
            || lower.contains("errconnect_account_disabled")
            || lower.contains("errconnect_username_password_missing")
            || lower.contains("nt_status_logon_failure")
            || lower.contains("status_logon_failure")
            || lower.contains("status_password_expired")
            || lower.contains("status_account_locked_out")
            || lower.contains("status_account_disabled")
            || is_auth
            || is_logon
            || (has_errconnect && lower.contains("auth"))
            || (lower.contains("credssp") && lower.contains("failed"))
            || (lower.contains("account") && lower.contains("locked"))
            || (lower.contains("password") && lower.contains("expired"))
        {
            return Some(
                "RDP Anmeldung fehlgeschlagen. Bitte Benutzer, Passwort und Domaene pruefen."
                    .to_string(),
            );
        }

        if has_errconnect
            || (lower.contains("connect")
                && (lower.contains("failed") || lower.contains("failure")))
            || (lower.contains("transport") && lower.contains("failed"))
            || (lower.contains("dns") && lower.contains("error"))
            || (lower.contains("name") && lower.contains("resolve") && lower.contains("fail"))
            || lower.contains("connection timeout")
            || lower.contains("connection timed out")
        {
            return Some(
                "RDP Verbindung fehlgeschlagen. Bitte Host, Port und Netzwerk pruefen.".to_string(),
            );
        }
    }
    None
}

#[cfg(unix)]
pub fn buffer_has_connected(buffer: &[u8]) -> bool {
    let output = String::from_utf8_lossy(buffer);
    let lower = output.to_lowercase();
    lower.contains("connected to") || lower.contains("connection established")
}

#[cfg(unix)]
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

#[cfg(unix)]
pub fn preflight_rdp(host: &str, port: u16) -> Result<(), AppError> {
    let addr = format!("{host}:{port}");
    let addrs = addr.to_socket_addrs().map_err(|_| {
        AppError::Connection(format!("Host konnte nicht aufgeloest werden: {host}"))
    })?;
    let timeout = Duration::from_secs(3);
    for socket in addrs {
        if TcpStream::connect_timeout(&socket, timeout).is_ok() {
            return Ok(());
        }
    }
    Err(AppError::Connection(
        "RDP Verbindung fehlgeschlagen. Bitte Host, Port und Netzwerk pruefen.".to_string(),
    ))
}

#[cfg(unix)]
pub fn check_rdp_auth(
    rdp_binary: &str,
    host: &str,
    port: u16,
    username: &str,
    domain: &str,
    trust_cert: bool,
    password: &str,
) -> Result<bool, AppError> {
    let mut args = vec![
        format!("/v:{host}:{port}"),
        "+auth-only".to_string(),
        "/from-stdin:force".to_string(),
        "/log-level:ERROR".to_string(),
    ];
    if trust_cert {
        args.push("/cert:ignore".to_string());
    }
    if !username.is_empty() {
        args.push(format!("/u:{username}"));
    }
    if !domain.is_empty() {
        args.push(format!("/d:{domain}"));
    }

    let mut command = Command::new(rdp_binary);
    command
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .env("WLOG_APPENDER", "console");
    let mut child = command.spawn()?;

    if let Some(mut stdin) = child.stdin.take() {
        let payload = format!("{password}\n");
        stdin.write_all(payload.as_bytes())?;
    }

    let output = child.wait_with_output()?;
    let mut combined = output.stderr;
    combined.extend_from_slice(&output.stdout);
    let output_text = String::from_utf8_lossy(&combined);
    let output_lower = output_text.to_lowercase();

    if output_lower.contains("unknown option") && output_lower.contains("auth-only") {
        return Ok(false);
    }
    if output_lower.contains("unrecognized option") && output_lower.contains("auth-only") {
        return Ok(false);
    }
    if output_lower.contains("invalid option") && output_lower.contains("auth-only") {
        return Ok(false);
    }

    if output.status.success() {
        return Ok(true);
    }

    if let Some(message) = parse_freerdp_error(combined.as_slice()) {
        return Err(AppError::Connection(message));
    }

    Err(AppError::Connection(
        "RDP Anmeldung fehlgeschlagen. Bitte Benutzer, Passwort und Domaene pruefen.".to_string(),
    ))
}

#[cfg(target_os = "windows")]
fn performance_rdp_lines(profile: RdpPerformanceProfile) -> Vec<String> {
    match profile {
        RdpPerformanceProfile::Auto => vec![
            "networkautodetect:i:1".to_string(),
            "bandwidthautodetect:i:1".to_string(),
            "connection type:i:7".to_string(),
        ],
        RdpPerformanceProfile::Lan => vec![
            "networkautodetect:i:0".to_string(),
            "bandwidthautodetect:i:0".to_string(),
            "connection type:i:6".to_string(),
            "allow desktop composition:i:1".to_string(),
            "allow font smoothing:i:1".to_string(),
        ],
        RdpPerformanceProfile::Broadband => vec![
            "networkautodetect:i:0".to_string(),
            "bandwidthautodetect:i:0".to_string(),
            "connection type:i:4".to_string(),
        ],
        RdpPerformanceProfile::Low => vec![
            "networkautodetect:i:0".to_string(),
            "bandwidthautodetect:i:0".to_string(),
            "connection type:i:2".to_string(),
            "disable wallpaper:i:1".to_string(),
            "disable full window drag:i:1".to_string(),
            "disable menu anims:i:1".to_string(),
            "disable themes:i:1".to_string(),
            "disable cursor setting:i:1".to_string(),
        ],
    }
}

#[cfg(target_os = "windows")]
pub fn write_rdp_file(
    host: &str,
    port: u16,
    username: &str,
    domain: &str,
    trust_cert: bool,
    rdp_window_mode: RdpWindowMode,
    rdp_custom_size: Option<&str>,
    rdp_performance_profile: RdpPerformanceProfile,
) -> Result<std::path::PathBuf, AppError> {
    use std::time::{SystemTime, UNIX_EPOCH};
    let mut path = std::env::temp_dir();
    let suffix = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_nanos())
        .unwrap_or(0);
    path.push(format!("adminhelper-{suffix}.rdp"));

    let mut lines = Vec::new();
    lines.push(format!("full address:s:{host}:{port}"));
    if !username.is_empty() {
        lines.push(format!("username:s:{username}"));
    }
    if !domain.is_empty() {
        lines.push(format!("domain:s:{domain}"));
    }
    if trust_cert {
        lines.push("authentication level:i:0".to_string());
    }

    // Window size
    match rdp_window_mode {
        RdpWindowMode::Fit => {
            lines.push("screen mode id:i:1".to_string());
            lines.push("smart sizing:i:1".to_string());
        }
        RdpWindowMode::Fullscreen => {
            lines.push("screen mode id:i:2".to_string());
        }
        RdpWindowMode::Multimon => {
            lines.push("screen mode id:i:2".to_string());
            lines.push("use multimon:i:1".to_string());
        }
        RdpWindowMode::Custom => {
            let (w, h) = parse_custom_size(rdp_custom_size)?;
            lines.push("screen mode id:i:1".to_string());
            lines.push(format!("desktopwidth:i:{w}"));
            lines.push(format!("desktopheight:i:{h}"));
        }
    }

    // Explicitly enable the clipboard (default, but documented)
    lines.push("redirectclipboard:i:1".to_string());

    // Performance
    lines.extend(performance_rdp_lines(rdp_performance_profile));

    let contents = lines.join("\r\n");
    std::fs::write(&path, contents)?;

    let cleanup_path = path.clone();
    std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_secs(30));
        let _ = std::fs::remove_file(&cleanup_path);
    });

    Ok(path)
}
