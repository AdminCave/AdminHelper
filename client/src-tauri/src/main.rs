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
use tauri::{Manager, PhysicalPosition, PhysicalSize, Size, Position, WindowEvent};

fn save_window_state(window: &tauri::WebviewWindow, path: &std::path::Path) {
    let Ok(size) = window.outer_size() else { return };
    let Ok(pos) = window.outer_position() else { return };
    let Ok(is_maximized) = window.is_maximized() else { return };
    let state = serde_json::json!({
        "width": size.width,
        "height": size.height,
        "x": pos.x,
        "y": pos.y,
        "maximized": is_maximized,
    });
    let _ = std::fs::write(path, state.to_string());
}

fn restore_window_state(window: &tauri::WebviewWindow, path: &std::path::Path) {
    let Ok(data) = std::fs::read_to_string(path) else { return };
    let Ok(state) = serde_json::from_str::<serde_json::Value>(&data) else { return };
    if state["maximized"].as_bool().unwrap_or(false) {
        let _ = window.maximize();
        return;
    }
    let width = state["width"].as_u64().unwrap_or(1440) as u32;
    let height = state["height"].as_u64().unwrap_or(900) as u32;
    let x = state["x"].as_i64().unwrap_or(0) as i32;
    let y = state["y"].as_i64().unwrap_or(0) as i32;
    let _ = window.set_size(Size::Physical(PhysicalSize { width, height }));
    let _ = window.set_position(Position::Physical(PhysicalPosition { x, y }));
}

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

            let state_path = app.path().app_data_dir()?.join("window-state.json");
            if let Some(window) = app.get_webview_window("main") {
                restore_window_state(&window, &state_path);
                window.on_window_event(move |event| {
                    if matches!(event, WindowEvent::CloseRequested { .. } | WindowEvent::Resized(_) | WindowEvent::Moved(_)) {
                        save_window_state(&window, &state_path);
                    }
                });
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
