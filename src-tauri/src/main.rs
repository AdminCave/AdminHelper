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

fn main() {
    tauri::Builder::default()
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
