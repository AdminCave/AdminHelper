// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use crate::error::AppError;
use crate::models::{ClientInfo, Connection, RdpErrorPayload, RdpOptions};
#[cfg(any(unix, target_os = "windows"))]
use crate::models::{RdpPerformanceProfile, RdpScalingMode, RdpWindowMode};

#[cfg(any(unix, target_os = "windows"))]
use super::rdp_logic::parse_custom_size;
#[cfg(unix)]
use super::rdp_logic::{buffer_has_connected, fit_window_size, hdpi_scale, parse_freerdp_error};

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

// --- RDP connection-monitoring tuning ---
// The login-failure heuristic hangs on these: a connect that exits sooner than
// LOGIN_FAIL_THRESHOLD_MS *after* connecting is read as a server-side login abort.
// CONNECT_TIMEOUT must stay above a slow VPN's connect time, or a valid login is
// misreported as "Anmeldung fehlgeschlagen".
#[cfg(unix)]
const CONNECT_TIMEOUT: Duration = Duration::from_secs(12);
#[cfg(unix)]
const LOGIN_FAIL_THRESHOLD_MS: u64 = 8000;
#[cfg(unix)]
const OUTPUT_BUFFER_CAP: usize = 8192; // cap the retained xfreerdp stderr tail
#[cfg(unix)]
const PREFLIGHT_TIMEOUT: Duration = Duration::from_secs(3); // TCP reachability probe

/// The .rdp launch file lingers this long after spawn so mstsc can read it, then
/// is deleted — long enough for a slow mstsc start, short enough not to leak.
#[cfg(target_os = "windows")]
const RDP_FILE_CLEANUP_DELAY: std::time::Duration = std::time::Duration::from_secs(30);

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
            check_rdp_auth(
                rdp_binary,
                host,
                port,
                username,
                domain,
                connection.trust_cert,
                secret,
            )?;
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

/// The context every RDP output/exit monitor shares (audit 2.13): bundling the
/// five hand-threaded fields keeps a new one from having to be added to three
/// 7-arg signatures at once. Cheap to clone — Arcs, a String and an AppHandle.
#[cfg(unix)]
#[derive(Clone)]
struct RdpWatch {
    emitted: Arc<AtomicBool>,
    connected: Arc<AtomicBool>,
    connected_at_ms: Arc<AtomicU64>,
    started_at: Instant,
    correlation_id: String,
    app: tauri::AppHandle,
}

#[cfg(unix)]
fn spawn_output_monitor(mut reader: impl Read + Send + 'static, watch: RdpWatch) {
    let RdpWatch {
        emitted,
        connected,
        connected_at_ms,
        started_at,
        correlation_id,
        app,
    } = watch;
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
            if buffer.len() > OUTPUT_BUFFER_CAP {
                buffer.drain(0..buffer.len().saturating_sub(OUTPUT_BUFFER_CAP));
            }
            if !connected.load(Ordering::SeqCst) && buffer_has_connected(&buffer) {
                let elapsed_ms = started_at.elapsed().as_millis() as u64;
                // Timestamp first, then the flag: a reader that sees
                // `connected == true` must observe the final timestamp.
                connected_at_ms.store(elapsed_ms, Ordering::SeqCst);
                connected.store(true, Ordering::SeqCst);
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
fn monitor_rdp_exit(mut child: std::process::Child, watch: RdpWatch) {
    let RdpWatch {
        emitted,
        connected,
        connected_at_ms,
        started_at,
        correlation_id,
        app,
    } = watch;
    // Timeout thread
    {
        let emitted = emitted.clone();
        let connected = connected.clone();
        let app = app.clone();
        let correlation_id = correlation_id.clone();
        std::thread::spawn(move || {
            std::thread::sleep(CONNECT_TIMEOUT);
            if !connected.load(Ordering::SeqCst) && !emitted.swap(true, Ordering::SeqCst) {
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
            if !connected.load(Ordering::SeqCst) {
                emit_rdp_error(
                    &app,
                    &correlation_id,
                    "RDP Verbindung fehlgeschlagen. Bitte Host, Port und Netzwerk pruefen.",
                );
            } else if elapsed_ms.saturating_sub(connected_at_ms.load(Ordering::SeqCst))
                < LOGIN_FAIL_THRESHOLD_MS
            {
                emit_rdp_error(
                    &app,
                    &correlation_id,
                    "RDP Anmeldung fehlgeschlagen. Bitte Benutzer, Passwort und Domaene pruefen.",
                );
            }
        }
    });
}

/// Feed a password to a spawned child's stdin, then scrub the local copy. The
/// security-critical secret-handling shared by the RDP launch and the auth probe,
/// so a later hardening (e.g. zeroize, or a forgotten kill on BrokenPipe) can't
/// land in only one of the two copies.
#[cfg(unix)]
fn feed_password_stdin(child: &mut std::process::Child, password: &str) -> Result<(), AppError> {
    if let Some(mut stdin) = child.stdin.take() {
        let mut payload = format!("{password}\n");
        let write_result = stdin.write_all(payload.as_bytes());
        // Scrub the password copy regardless of the write outcome (parity with the
        // Windows credential path in password.rs).
        unsafe {
            for byte in payload.as_bytes_mut() {
                *byte = 0;
            }
        }
        if let Err(e) = write_result {
            // A BrokenPipe (child already exited / refused stdin) would otherwise
            // leave the spawned process around — reap it before propagating.
            let _ = child.kill();
            return Err(e.into());
        }
    }
    Ok(())
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

    feed_password_stdin(&mut child, password)?;

    // Separate "connected" flag instead of `connected_at_ms == 0`: a
    // sub-millisecond connect would also store 0 and look like "never
    // connected", producing a false connection-failed toast.
    let watch = RdpWatch {
        emitted: Arc::new(AtomicBool::new(false)),
        connected: Arc::new(AtomicBool::new(false)),
        connected_at_ms: Arc::new(AtomicU64::new(0)),
        started_at,
        correlation_id: correlation_id.to_string(),
        app: app.clone(),
    };

    if let Some(stdout) = child.stdout.take() {
        spawn_output_monitor(stdout, watch.clone());
    }

    if let Some(stderr) = child.stderr.take() {
        spawn_output_monitor(stderr, watch.clone());
    }

    monitor_rdp_exit(child, watch);
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
pub fn preflight_rdp(host: &str, port: u16) -> Result<(), AppError> {
    let addr = format!("{host}:{port}");
    let addrs = addr.to_socket_addrs().map_err(|_| {
        AppError::Connection(format!("Host konnte nicht aufgeloest werden: {host}"))
    })?;
    let timeout = PREFLIGHT_TIMEOUT;
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
) -> Result<(), AppError> {
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

    feed_password_stdin(&mut child, password)?;

    let output = child.wait_with_output()?;
    let mut combined = output.stderr;
    combined.extend_from_slice(&output.stdout);
    let output_text = String::from_utf8_lossy(&combined);
    let output_lower = output_text.to_lowercase();

    // An xfreerdp too old for +auth-only rejects the probe flag; skip the check and
    // let the real launch surface any auth failure.
    let auth_only_unsupported = ["unknown option", "unrecognized option", "invalid option"]
        .iter()
        .any(|m| output_lower.contains(m))
        && output_lower.contains("auth-only");
    if auth_only_unsupported {
        return Ok(());
    }

    if output.status.success() {
        return Ok(());
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
        std::thread::sleep(RDP_FILE_CLEANUP_DELAY);
        let _ = std::fs::remove_file(&cleanup_path);
    });

    Ok(path)
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    #[test]
    fn feed_password_stdin_writes_and_returns_ok() {
        // `cat` accepts the piped stdin; the helper must write, scrub, and succeed.
        let mut child = Command::new("cat")
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .spawn()
            .expect("cat available");
        assert!(feed_password_stdin(&mut child, "s3cret").is_ok());
        // stdin was consumed by the helper, so cat sees EOF and exits.
        let _ = child.wait();
    }
}

// Security invariants of the xfreerdp arg builder: /cert:ignore only with trust_cert, the window
// title is sanitized, and the password never reaches argv (fed via stdin instead) (6.31).
#[cfg(all(test, unix))]
mod args_tests {
    use super::*;
    use crate::models::{ConnectionKind, RdpPerformanceProfile, RdpScalingMode, RdpWindowMode};

    fn conn(name: &str, trust_cert: bool) -> Connection {
        Connection {
            id: "id".into(),
            name: name.into(),
            kind: ConnectionKind::Rdp,
            host: Some("h".into()),
            port: Some(3389),
            username: Some("user".into()),
            domain: Some("dom".into()),
            key_path: None,
            url: None,
            notes: None,
            tags: vec![],
            trust_cert,
            last_used: None,
            server_id: None,
        }
    }

    fn opts() -> RdpOptions<'static> {
        RdpOptions {
            scaling_mode: RdpScalingMode::Normal,
            window_mode: RdpWindowMode::Fit,
            custom_size: None,
            performance_profile: RdpPerformanceProfile::Auto,
        }
    }

    #[test]
    fn cert_ignore_only_with_trust_cert() {
        let without = build_rdp_args(&conn("n", false), "h", 3389, None, opts(), None).unwrap();
        assert!(
            !without.iter().any(|a| a == "/cert:ignore"),
            "no trust_cert must not disable the TLS check: {without:?}"
        );
        let with = build_rdp_args(&conn("n", true), "h", 3389, None, opts(), None).unwrap();
        assert!(
            with.iter().any(|a| a == "/cert:ignore"),
            "trust_cert -> /cert:ignore"
        );
    }

    #[test]
    fn window_title_is_sanitized() {
        let args = build_rdp_args(
            &conn("evil; rm -rf $HOME", false),
            "h",
            3389,
            None,
            opts(),
            None,
        )
        .unwrap();
        let title = args
            .iter()
            .find(|a| a.starts_with("/title:"))
            .expect("has a /title: arg");
        assert!(
            !title.contains(';') && !title.contains('$'),
            "title metacharacters not sanitized: {title}"
        );
    }

    #[test]
    fn password_never_in_argv() {
        // build_rdp_args takes no password; the secret is fed via stdin (feed_password_stdin).
        let args = build_rdp_args(&conn("n", false), "h", 3389, None, opts(), None).unwrap();
        assert!(
            !args.iter().any(|a| a.starts_with("/p:")),
            "password must never land in argv: {args:?}"
        );
    }
}
