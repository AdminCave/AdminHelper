// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

mod ansible;
mod auth;
mod commands;
mod connection;
mod error;
mod frpc;
mod models;
mod password;
mod storage;
mod sync;
mod terminal;
mod tunnel;
mod validation;

use commands::{
    ansible_generate_inventory, ansible_launch, ansible_write_playbook, api_proxy,
    check_server_cert, check_session, delete_password, fetch_connections_jwt, fetch_tunnels,
    load_connections, load_settings, login, logout, open_connection, open_connection_stored,
    password_state, resolve_connection, save_connections, save_password, save_settings,
    start_tunnel, stop_tunnel, sync_connections, tunnel_status,
};
use tauri::Manager;

fn main() {
    let frpc_state = frpc::new_frpc_state();
    let frpc_state_exit = frpc_state.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(frpc_state)
        .setup(|app| {
            // Ensure a concrete runtime window icon in dev and production.
            let icon_bytes = include_bytes!("../icons/icon.png");
            if let Ok(icon) = tauri::image::Image::from_bytes(icon_bytes) {
                for (_, window) in app.webview_windows() {
                    let _ = window.set_icon(icon.clone());
                }
            }
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
            check_session,
            fetch_connections_jwt,
            start_tunnel,
            stop_tunnel,
            tunnel_status,
            fetch_tunnels,
            resolve_connection,
            api_proxy,
            check_server_cert,
            ansible_generate_inventory,
            ansible_write_playbook,
            ansible_launch
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(move |_app, event| {
            if let tauri::RunEvent::Exit = event {
                let _ = frpc::stop_frpc(&frpc_state_exit);
            }
        });
}
