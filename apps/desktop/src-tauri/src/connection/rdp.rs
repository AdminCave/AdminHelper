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
use super::rdp_logic::{
    auth_only_unsupported, buffer_has_connected, drain_into_tail, fit_window_size, hdpi_scale,
    interactive_exit_message, parse_freerdp_error, OutputTail,
};

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
use zeroize::Zeroize;

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
const OUTPUT_BUFFER_CAP: usize = 8192; // kept tail of each xfreerdp stream, both launch paths
#[cfg(unix)]
const PREFLIGHT_TIMEOUT: Duration = Duration::from_secs(3); // TCP reachability probe

/// The .rdp launch file lingers this long after spawn so mstsc can read it, then
/// is deleted — long enough for a slow mstsc start, short enough not to leak.
#[cfg(target_os = "windows")]
const RDP_FILE_CLEANUP_DELAY: std::time::Duration = std::time::Duration::from_secs(30);

#[allow(clippy::too_many_arguments)]
pub fn open_rdp(
    connection: &Connection,
    password: Option<&str>,
    client: Option<&ClientInfo>,
    rdp: RdpOptions,
    ui_language: Option<&str>,
    correlation_id: &str,
    app: &tauri::AppHandle,
    deadline: &super::Deadline,
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

    #[cfg(not(any(unix, target_os = "windows")))]
    let _ = password;
    #[cfg(not(any(unix, target_os = "windows")))]
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
            app, connection, host, port, username, domain, rdp, password, deadline,
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
                deadline.remaining(),
            )?;
            args.push("/from-stdin:force".to_string());
            args.push("/log-level:INFO".to_string());
            deadline.start()?;
            spawn_rdp_with_password(rdp_binary, args, secret, correlation_id, app)?;
        } else {
            args.push("/log-level:INFO".to_string());
            deadline.start()?;
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

/// Starts mstsc with a `.rdp` file for `host:port`; a stored `password` holds a `TERMSRV/…`
/// entry for that address only for the start (`password::start_mstsc`, R-0431). The app data dir
/// of `app` keeps the holds of all workspaces on such entries.
#[cfg(target_os = "windows")]
#[allow(clippy::too_many_arguments)]
fn open_rdp_windows(
    app: &tauri::AppHandle,
    connection: &Connection,
    host: &str,
    port: u16,
    username: &str,
    domain: &str,
    rdp: RdpOptions,
    password: Option<&str>,
    deadline: &super::Deadline,
) -> Result<(), AppError> {
    use std::process::Command;

    // The `TERMSRV/…` names of the start are those of the address in the file, so both take
    // the same host, without spaces around it.
    let host = host.trim();
    let base = crate::storage::app_data_dir(app)?;
    let rdp_path = write_rdp_file(
        host,
        port,
        username,
        domain,
        connection.trust_cert,
        rdp.window_mode,
        rdp.custom_size,
        rdp.performance_profile,
    )?;
    crate::password::start_mstsc(&base, host, port, connection, password, || {
        // A start past the deadline does not run, and run_termsrv_plan takes back the
        // entry and hold it made for it.
        deadline.start()?;
        Command::new("mstsc").arg(&rdp_path).spawn()?;
        Ok(())
    })
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
    let title = window_title(&connection.name);
    if !title.is_empty() {
        args.push(format!("/title:{title}"));
    }

    args.extend(performance_args(rdp.performance_profile));

    Ok(args)
}

/// The connection's name, in a workspace process after `[<workspace name>] `, so the windows of
/// one host in two workspaces tell apart. Each name is sanitized on its own and the brackets come
/// after: the sanitizer drops `[` and `]`, so neither name can forge another workspace's prefix.
/// A workspace name of which the sanitizer leaves nothing (only emoji or symbols) gives way to
/// the workspace id, which is safe as it is. Without a workspace (the launcher, or before the
/// start sets one) the name stands alone.
#[cfg(unix)]
fn window_title(connection_name: &str) -> String {
    let name = crate::validation::sanitize_window_title(connection_name);
    let workspace = crate::workspace::current()
        .map(|workspace| {
            let name = crate::validation::sanitize_window_title(&workspace.name);
            if name.is_empty() {
                workspace.id.to_string()
            } else {
                name
            }
        })
        .unwrap_or_default();
    if workspace.is_empty() {
        name
    } else {
        format!("[{workspace}] {name}").trim_end().to_string()
    }
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

/// Feed a password to a spawned child's stdin, then zero the copy this function made
/// for it. Shared by the RDP launch and the auth probe, so both handle the secret and
/// a failed write the same way. Only that one copy is zeroed: the string from the IPC,
/// the `password` argument, the strings from the keyring and the session's tokens stay
/// in memory as they are.
#[cfg(unix)]
fn feed_password_stdin(child: &mut std::process::Child, password: &str) -> Result<(), AppError> {
    if let Some(mut stdin) = child.stdin.take() {
        // Sized up front: a `format!` that grows its buffer frees the old one with the
        // password still in it, out of reach of the zeroize below.
        let mut payload = String::with_capacity(password.len() + 1);
        payload.push_str(password);
        payload.push('\n');
        let write_result = stdin.write_all(payload.as_bytes());
        // Zero the copy regardless of the write outcome, as the Windows credential path
        // in password.rs does with its own.
        payload.zeroize();
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
        if let Some(message) = wait_interactive(child) {
            emit_rdp_error(&app_handle, &cid, message);
        }
    });
    Ok(())
}

/// Waits for an interactive xfreerdp and returns the message for its end, if
/// any. A session can run for hours at `/log-level:INFO`, so each pipe is
/// drained on a thread of its own into a bounded tail (R-0646); xfreerdp
/// would block on whichever pipe nobody reads.
#[cfg(unix)]
fn wait_interactive(mut child: std::process::Child) -> Option<String> {
    let stderr = drain_on_thread(child.stderr.take());
    let stdout = drain_on_thread(child.stdout.take());
    let exited = child.wait();
    let collect = |reader: Option<std::thread::JoinHandle<OutputTail>>| {
        reader
            .and_then(|handle| handle.join().ok())
            .unwrap_or_else(|| OutputTail::new(OUTPUT_BUFFER_CAP))
    };
    let (stderr, stdout) = (collect(stderr), collect(stdout));
    exited.ok()?;
    interactive_exit_message(&stderr, &stdout)
}

#[cfg(unix)]
fn drain_on_thread(
    pipe: Option<impl Read + Send + 'static>,
) -> Option<std::thread::JoinHandle<OutputTail>> {
    pipe.map(|pipe| std::thread::spawn(move || drain_into_tail(pipe, OUTPUT_BUFFER_CAP)))
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

/// Runs xfreerdp's `+auth-only` check. It ends within `timeout`: an xfreerdp that hangs
/// (a host that never answers the handshake) is killed and reaped, so nothing waits on it
/// once the command gave up. With no time left it starts no xfreerdp at all: the command has
/// given up already, and the password must not reach a process nobody waits for.
#[cfg(unix)]
#[allow(clippy::too_many_arguments)]
pub fn check_rdp_auth(
    rdp_binary: &str,
    host: &str,
    port: u16,
    username: &str,
    domain: &str,
    trust_cert: bool,
    password: &str,
    timeout: std::time::Duration,
) -> Result<(), AppError> {
    if timeout.is_zero() {
        return Err(AppError::Connection(super::TIMEOUT_MESSAGE.to_string()));
    }
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

    // Read both pipes on threads of their own, so a full pipe cannot stall the child, and
    // poll for its end up to the deadline instead of waiting without one.
    let reader = |pipe: Option<Box<dyn std::io::Read + Send>>| {
        std::thread::spawn(move || {
            let mut buf = Vec::new();
            if let Some(mut pipe) = pipe {
                let _ = pipe.read_to_end(&mut buf);
            }
            buf
        })
    };
    let stdout = reader(
        child
            .stdout
            .take()
            .map(|p| Box::new(p) as Box<dyn std::io::Read + Send>),
    );
    let stderr = reader(
        child
            .stderr
            .take()
            .map(|p| Box::new(p) as Box<dyn std::io::Read + Send>),
    );
    let deadline = std::time::Instant::now() + timeout;
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if std::time::Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            // The reader threads end with the pipes; nothing waits for them here.
            return Err(AppError::Connection(
                "The RDP credential check did not finish in time.".to_string(),
            ));
        }
        std::thread::sleep(std::time::Duration::from_millis(50));
    };
    let mut combined = stderr.join().unwrap_or_default();
    combined.extend_from_slice(&stdout.join().unwrap_or_default());
    let output_text = String::from_utf8_lossy(&combined);
    let output_lower = output_text.to_lowercase();

    // An xfreerdp too old for +auth-only rejects the probe flag; skip the check and
    // let the real launch surface any auth failure.
    if auth_only_unsupported(&output_lower) {
        return Ok(());
    }

    if status.success() {
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

/// Reap `.rdp` files a previously killed session leaked. The per-launch cleanup
/// thread below is best-effort: it dies with the app, so a `.rdp` file (which
/// carries the host + username) survives on disk if the app is closed within
/// RDP_FILE_CLEANUP_DELAY. Sweeping leftovers on the next launch bounds the
/// exposure to a single session instead of leaving the file forever (4.93). Only
/// files older than the cleanup delay are removed, so a sibling `.rdp` that a
/// concurrent launch may still be opening is never deleted out from under it.
#[cfg(target_os = "windows")]
fn sweep_stale_rdp_files(dir: &std::path::Path) {
    use std::time::SystemTime;
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    let now = SystemTime::now();
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if !(name.starts_with("adminhelper-") && name.ends_with(".rdp")) {
            continue;
        }
        let stale = entry
            .metadata()
            .and_then(|meta| meta.modified())
            .ok()
            .and_then(|mtime| now.duration_since(mtime).ok())
            .map(|age| age >= RDP_FILE_CLEANUP_DELAY)
            .unwrap_or(true); // unreadable/future mtime → treat as stale (best-effort)
        if stale {
            let _ = std::fs::remove_file(entry.path());
        }
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
    // Reap any .rdp a previously killed session leaked before its cleanup ran (4.93).
    sweep_stale_rdp_files(&path);
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
        // `cat` echoes the piped stdin: the password and a newline arrive, and the helper
        // returns Ok. Whether it zeroes its own copy is not observable from here.
        let mut child = Command::new("cat")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .expect("cat available");
        assert!(feed_password_stdin(&mut child, "s3cret-passphrase").is_ok());
        // stdin was consumed by the helper, so cat sees EOF and exits.
        let output = child.wait_with_output().expect("cat exits");
        assert_eq!(output.stdout, b"s3cret-passphrase\n");
    }

    /// Runs `script` as a stand-in for xfreerdp through `wait_interactive`; a
    /// hang fails the test after `limit` instead of blocking the suite.
    fn wait_interactive_on(script: &str, limit: Duration) -> Option<String> {
        let child = Command::new("sh")
            .arg("-c")
            .arg(script)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("sh available");
        let (done, result) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            let _ = done.send(wait_interactive(child));
        });
        result
            .recv_timeout(limit)
            .expect("wait_interactive returns in time")
    }

    // Both pipes fill at once and the marker comes last: a reader that took one pipe after
    // the other would leave the stub blocked on the second and never return.
    #[test]
    fn wait_interactive_drains_both_pipes_of_a_loud_session() {
        let script = "line='[INFO][com.freerdp.gdi] - frame update'; \
                      yes \"$line\" | head -c 2097152 & \
                      yes \"$line\" | head -c 2097152 >&2 & \
                      wait; \
                      echo '[INFO][com.freerdp.client.x11] - Connected to 192.0.2.10:3389'";
        assert_eq!(wait_interactive_on(script, Duration::from_secs(10)), None);
    }

    #[test]
    fn wait_interactive_reports_the_error_line_of_a_failed_run() {
        let script = "echo '[ERROR][com.freerdp.core] - freerdp_set_last_error_ex \
                      ERRCONNECT_LOGON_FAILURE [0x00020014]' >&2; exit 1";
        assert_eq!(
            wait_interactive_on(script, Duration::from_secs(10)).as_deref(),
            Some("RDP Anmeldung fehlgeschlagen. Bitte Benutzer, Passwort und Domaene pruefen.")
        );
    }

    /// A stub `rdp_binary` in a directory of its own: `body` is its shell script.
    fn stub_rdp_binary(case: &str, body: &str) -> std::path::PathBuf {
        use std::os::unix::fs::PermissionsExt;
        let dir = std::env::temp_dir().join(format!(
            "adminhelper-rdp-stub-{}-{case}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("xfreerdp");
        std::fs::write(&path, format!("#!/bin/sh\n{body}\n")).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o755)).unwrap();
        path
    }

    #[test]
    fn check_rdp_auth_gives_up_at_its_deadline_and_reaps_the_child() {
        let stub = stub_rdp_binary(
            "hangs",
            "echo $$ > \"$(dirname \"$0\")/pid\"; exec sleep 30",
        );
        let start = std::time::Instant::now();
        let result = check_rdp_auth(
            stub.to_str().unwrap(),
            "192.0.2.10",
            3389,
            "u",
            "",
            false,
            "pw",
            std::time::Duration::from_millis(300),
        );
        assert!(result.is_err(), "{result:?}");
        assert!(start.elapsed() < std::time::Duration::from_secs(5));
        let dir = stub.parent().unwrap();
        let pid = std::fs::read_to_string(dir.join("pid")).unwrap();
        let alive = std::process::Command::new("kill")
            .args(["-0", pid.trim()])
            .status()
            .unwrap()
            .success();
        assert!(!alive, "xfreerdp {pid} still runs after the deadline");
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn check_rdp_auth_starts_no_xfreerdp_once_the_deadline_is_past() {
        let stub = stub_rdp_binary("past", "touch \"$(dirname \"$0\")/ran\"; exit 0");
        let result = check_rdp_auth(
            stub.to_str().unwrap(),
            "192.0.2.10",
            3389,
            "u",
            "",
            false,
            "pw",
            std::time::Duration::ZERO,
        );
        assert!(
            matches!(&result, Err(AppError::Connection(m)) if m == super::super::TIMEOUT_MESSAGE),
            "{result:?}"
        );
        let dir = stub.parent().unwrap();
        assert!(!dir.join("ran").exists(), "xfreerdp ran after the deadline");
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn check_rdp_auth_passes_an_xfreerdp_that_ends_in_time() {
        let stub = stub_rdp_binary("ends", "cat > /dev/null; exit 0");
        let result = check_rdp_auth(
            stub.to_str().unwrap(),
            "192.0.2.10",
            3389,
            "u",
            "",
            false,
            "pw",
            std::time::Duration::from_secs(10),
        );
        assert!(result.is_ok(), "{result:?}");
        let _ = std::fs::remove_dir_all(stub.parent().unwrap());
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

    fn title_of(name: &str) -> Option<String> {
        build_rdp_args(&conn(name, false), "h", 3389, None, opts(), None)
            .unwrap()
            .into_iter()
            .find_map(|a| a.strip_prefix("/title:").map(str::to_string))
    }

    fn enter_workspace(name: &str) -> crate::workspace::EnteredWorkspace {
        crate::workspace::enter(crate::workspace::Workspace {
            id: crate::workspace::WorkspaceId::parse("kunde-a").unwrap(),
            name: name.to_string(),
            legacy_keys: false,
        })
    }

    #[test]
    fn per_process_rdp_title_without_a_workspace_is_the_connection_name() {
        assert_eq!(title_of("Web 01").as_deref(), Some("Web 01"));
        assert_eq!(title_of(";$").as_deref(), None, "nothing left, no title");
    }

    #[test]
    fn per_process_rdp_title_starts_with_the_workspace_name() {
        let _workspace = enter_workspace("Kunde A");
        assert_eq!(title_of("Web 01").as_deref(), Some("[Kunde A] Web 01"));
        assert_eq!(
            title_of(";$").as_deref(),
            Some("[Kunde A]"),
            "the workspace alone still names the window"
        );
    }

    #[test]
    fn per_process_rdp_title_sanitizes_the_workspace_name_before_the_brackets() {
        // A bracket in either name would let it forge the prefix of another workspace.
        let _workspace = enter_workspace("Kunde] [B; $x");
        assert_eq!(
            title_of("[Kunde C] Web").as_deref(),
            Some("[Kunde B x] Kunde C Web")
        );
    }

    // A name of only emoji or symbols leaves nothing after sanitizing; the windows of two such
    // workspaces still tell apart by the id.
    #[test]
    fn per_process_rdp_title_without_a_sanitized_workspace_name_takes_the_workspace_id() {
        let _workspace = enter_workspace("🚀 ;$");
        assert_eq!(title_of("Web 01").as_deref(), Some("[kunde-a] Web 01"));
        assert_eq!(title_of(";$").as_deref(), Some("[kunde-a]"));
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

// The .rdp file (host + username) and its stale-leftover sweep are Windows-only.
#[cfg(all(test, windows))]
mod rdp_file_tests {
    use super::*;
    use std::time::{Duration, SystemTime, UNIX_EPOCH};

    // A fresh, isolated temp subdir so the sweep never touches real .rdp files.
    fn scratch_dir() -> std::path::PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!("ah-rdp-sweep-{nanos}"));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn sweep_reaps_only_stale_adminhelper_rdp_files() {
        let dir = scratch_dir();
        let stale = dir.join("adminhelper-111.rdp"); // leaked by a killed session
        let fresh = dir.join("adminhelper-222.rdp"); // maybe still being read by mstsc
        let other = dir.join("keep-me.rdp"); // wrong prefix — not ours
        for p in [&stale, &fresh, &other] {
            std::fs::write(p, "full address:s:h:3389").unwrap();
        }
        // Backdate the stale file's mtime past the cleanup delay so the sweep reaps it,
        // while the freshly written one stays inside the window and must be kept.
        let old = SystemTime::now() - (RDP_FILE_CLEANUP_DELAY + Duration::from_secs(5));
        std::fs::File::options()
            .write(true)
            .open(&stale)
            .unwrap()
            .set_modified(old)
            .unwrap();

        sweep_stale_rdp_files(&dir);

        assert!(!stale.exists(), "a stale adminhelper .rdp must be reaped");
        assert!(
            fresh.exists(),
            "a fresh adminhelper .rdp (maybe in use) must be kept"
        );
        assert!(other.exists(), "a non-adminhelper file must be left alone");

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn write_rdp_file_reaps_prior_leftovers() {
        // A leaked, backdated file in the real temp dir must be gone after the next
        // write_rdp_file call (which sweeps first). Use a distinctive backdated file.
        let leftover = std::env::temp_dir().join("adminhelper-000-stale-test.rdp");
        std::fs::write(&leftover, "full address:s:h:3389").unwrap();
        let old = SystemTime::now() - (RDP_FILE_CLEANUP_DELAY + Duration::from_secs(5));
        std::fs::File::options()
            .write(true)
            .open(&leftover)
            .unwrap()
            .set_modified(old)
            .unwrap();

        let written = write_rdp_file(
            "host",
            3389,
            "user",
            "",
            false,
            RdpWindowMode::Fit,
            None,
            RdpPerformanceProfile::Auto,
        )
        .unwrap();

        assert!(
            !leftover.exists(),
            "write_rdp_file must reap prior stale leftovers"
        );
        assert!(written.exists(), "the freshly written .rdp must exist");
        let _ = std::fs::remove_file(&written);
    }
}
