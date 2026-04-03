mod commands;
mod connection;
mod error;
mod models;
mod password;
mod storage;
mod sync;
mod terminal;
mod validation;

use commands::{
    delete_password, load_connections, load_settings, open_connection, open_connection_stored,
    password_state, save_connections, save_password, save_settings, sync_connections,
};
use tauri::Manager;

fn main() {
    tauri::Builder::default()
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
            open_connection_stored
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
