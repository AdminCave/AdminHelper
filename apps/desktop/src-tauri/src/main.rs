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
mod models;
mod notifications;
mod password;
mod storage;
mod sync;
mod terminal;
mod tofu;
mod tunnel;
mod validation;

use commands::{
    ansible_generate_inventory, ansible_launch, ansible_write_playbook, api_proxy,
    check_server_cert, delete_password, enroll_device, enroll_with_token, export_browser_p12,
    fetch_connections_jwt, fetch_tunnels, generate_diagnostics, is_device_enrolled,
    load_connections, load_settings, login, logout, open_connection, open_connection_stored,
    password_state, reset_device_identity, reset_server_cert_pin, resolve_connection,
    save_connections, save_password, save_settings, start_notification_stream, start_tunnel,
    stop_notification_stream, stop_tunnel, sync_connections, tunnel_status,
};
use tauri::Manager;

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

    tauri::Builder::default()
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
        .manage(stream_state)
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
            stop_tunnel,
            tunnel_status,
            fetch_tunnels,
            generate_diagnostics,
            resolve_connection,
            api_proxy,
            check_server_cert,
            reset_server_cert_pin,
            is_device_enrolled,
            reset_device_identity,
            enroll_device,
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
