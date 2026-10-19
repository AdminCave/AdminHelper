// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

mod ansible;
mod auth;
mod commands;
mod connection;
mod diagnostics;
mod enrollment;
mod error;
mod frpc;
mod http_client;
mod keyring_store;
mod launcher;
mod migration;
mod models;
mod notifications;
mod password;
mod port_registry;
mod proxy;
mod session;
mod storage;
mod sync;
mod terminal;
#[cfg(test)]
mod test_tls;
mod tofu;
mod tunnel;
mod validation;
mod workspace;

use commands::{
    ansible_generate_inventory, ansible_launch, ansible_write_playbook, api_proxy,
    check_server_cert, delete_password, device_identity, enroll_with_token, export_browser_p12,
    fetch_connections_jwt, fetch_tunnels, generate_diagnostics, is_device_enrolled,
    load_connections, load_settings, login, logout, open_connection, open_connection_stored,
    password_state, pinned_ca_fingerprint, refresh_tunnel, reset_device_identity,
    reset_server_cert_pin, resolve_connection, save_connections, save_password, save_settings,
    start_notification_stream, start_tunnel, stop_notification_stream, stop_tunnel,
    sync_connections, tunnel_status,
};
use tauri::{Emitter, Manager};

fn main() {
    // Route panics through the log sink (file + stdout) so a crash leaves a
    // trace in the diagnostics log, while keeping the default stderr/backtrace.
    let default_panic = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        log::error!("panic: {info}");
        default_panic(info);
    }));

    let frpc_state = frpc::new_frpc_state();
    let frpc_state_exit = frpc_state.clone();
    let stream_state = notifications::new_stream_state();
    let stream_state_exit = stream_state.clone();

    let builder = tauri::Builder::default();
    // Registered first so a second launch hands over and exits before any other
    // plugin or the setup runs. On Linux this needs `enableGTKAppId: false`:
    // with a GTK app id, GApplication forwards the launch itself and makes this
    // instance re-run its setup, which aborts on the existing `main` window.
    #[cfg(desktop)]
    let builder = builder.plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
        if let Some(window) = app.get_webview_window("main") {
            let _ = window.unminimize();
            let _ = window.show();
            let _ = window.set_focus();
        }
    }));

    builder
        .plugin(
            // stdout + a size-rotated file (adminhelper.log) in the OS app-log
            // dir — the diagnostics report reads it back.
            tauri_plugin_log::Builder::new()
                .target(tauri_plugin_log::Target::new(
                    tauri_plugin_log::TargetKind::Stdout,
                ))
                .target(tauri_plugin_log::Target::new(
                    tauri_plugin_log::TargetKind::LogDir {
                        file_name: Some("adminhelper".into()),
                    },
                ))
                .level(log::LevelFilter::Info)
                .max_file_size(10_000_000)
                .build(),
        )
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .manage(frpc_state)
        .manage(frpc::RefreshLock::default())
        .manage(stream_state)
        .manage(session::SessionState::default())
        .setup(|app| {
            // Ensure a concrete runtime window icon in dev and production.
            let icon_bytes = include_bytes!("../icons/icon.png");
            if let Ok(icon) = tauri::image::Image::from_bytes(icon_bytes) {
                for (_, window) in app.webview_windows() {
                    let _ = window.set_icon(icon.clone());
                }
            }
            // Migrate the pre-split local connection store (connections.json ->
            // connections.local.json) once, before any server fetch can
            // overwrite the legacy file. Best-effort: must not block startup.
            let _ = storage::migrate_legacy_local_store(app.handle());
            // The session lives in the process now; drop what earlier versions left in the
            // keyring. Off the main thread: a keyring that hangs must not hold the window.
            tauri::async_runtime::spawn_blocking(auth::forget_keyring_session);
            // A renewal that fails ends the session; the webview hears of it through this event.
            let handle = app.handle().clone();
            app.state::<session::SessionState>().on_expiry(move || {
                let _ = handle.emit("session-expired", ());
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            load_connections,
            load_settings,
            save_settings,
            password_state,
            save_password,
            delete_password,
            sync_connections,
            save_connections,
            open_connection,
            open_connection_stored,
            login,
            logout,
            fetch_connections_jwt,
            start_tunnel,
            refresh_tunnel,
            stop_tunnel,
            tunnel_status,
            fetch_tunnels,
            generate_diagnostics,
            resolve_connection,
            api_proxy,
            check_server_cert,
            reset_server_cert_pin,
            is_device_enrolled,
            device_identity,
            pinned_ca_fingerprint,
            reset_device_identity,
            enroll_with_token,
            export_browser_p12,
            ansible_generate_inventory,
            ansible_write_playbook,
            ansible_launch,
            start_notification_stream,
            stop_notification_stream
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(move |_app, event| {
            if let tauri::RunEvent::Exit = event {
                let _ = frpc::stop_frpc(&frpc_state_exit);
                notifications::stop(&stream_state_exit);
            }
        });
}
