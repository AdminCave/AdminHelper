mod connection;
mod error;
mod models;
mod password;
mod storage;
mod sync;
mod terminal;
mod validation;

use error::AppError;
use models::{ClientInfo, Connection, PasswordState, Settings};

#[tauri::command]
fn load_connections(app: tauri::AppHandle) -> Result<Vec<Connection>, AppError> {
    storage::load_connections(&app)
}

#[tauri::command]
fn load_settings(app: tauri::AppHandle) -> Result<Settings, AppError> {
    storage::load_settings(&app)
}

#[tauri::command]
fn save_settings(app: tauri::AppHandle, settings: Settings) -> Result<(), AppError> {
    storage::save_settings(&app, &settings)
}

#[tauri::command]
async fn sync_connections(app: tauri::AppHandle, url: String) -> Result<Vec<Connection>, AppError> {
    sync::sync_connections(app, url).await
}

#[tauri::command]
fn save_connections(app: tauri::AppHandle, connections: Vec<Connection>) -> Result<(), AppError> {
    storage::save_connections(&app, &connections)
}

#[tauri::command]
fn open_connection(
    app: tauri::AppHandle,
    connection: Connection,
    password: Option<String>,
    client: Option<ClientInfo>,
) -> Result<(), AppError> {
    connection::open_connection(&connection, password.as_deref(), client.as_ref(), &app)
}

#[tauri::command]
fn open_connection_stored(
    app: tauri::AppHandle,
    connection: Connection,
    client: Option<ClientInfo>,
) -> Result<(), AppError> {
    connection::open_connection_stored(&app, &connection, client.as_ref())
}

#[tauri::command]
fn password_state(connection: Connection) -> Result<PasswordState, AppError> {
    password::password_state(&connection)
}

#[tauri::command]
fn save_password(connection: Connection, password: String) -> Result<(), AppError> {
    password::save_password(&connection, &password)
}

#[tauri::command]
fn delete_password(connection: Connection) -> Result<(), AppError> {
    password::delete_password(&connection)
}

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
