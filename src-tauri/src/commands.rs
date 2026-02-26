use crate::connection;
use crate::error::AppError;
use crate::models::{ClientInfo, Connection, PasswordState, Settings};
use crate::password;
use crate::storage;
use crate::sync;

#[tauri::command]
pub fn load_connections(app: tauri::AppHandle) -> Result<Vec<Connection>, AppError> {
    storage::load_connections(&app)
}

#[tauri::command]
pub fn load_settings(app: tauri::AppHandle) -> Result<Settings, AppError> {
    storage::load_settings(&app)
}

#[tauri::command]
pub fn save_settings(app: tauri::AppHandle, settings: Settings) -> Result<(), AppError> {
    storage::save_settings(&app, &settings)
}

#[tauri::command]
pub async fn sync_connections(
    app: tauri::AppHandle,
    url: String,
) -> Result<Vec<Connection>, AppError> {
    sync::sync_connections(app, url).await
}

#[tauri::command]
pub fn save_connections(
    app: tauri::AppHandle,
    connections: Vec<Connection>,
) -> Result<(), AppError> {
    storage::save_connections(&app, &connections)
}

#[tauri::command]
pub fn open_connection(
    app: tauri::AppHandle,
    connection: Connection,
    password: Option<String>,
    client: Option<ClientInfo>,
) -> Result<(), AppError> {
    let settings = storage::load_settings(&app)?;
    connection::open_connection(
        &connection,
        password.as_deref(),
        client.as_ref(),
        settings.rdp_scaling_mode,
        settings.language.as_deref(),
        &app,
    )
}

#[tauri::command]
pub fn open_connection_stored(
    app: tauri::AppHandle,
    connection: Connection,
    client: Option<ClientInfo>,
) -> Result<(), AppError> {
    let settings = storage::load_settings(&app)?;
    connection::open_connection_stored(
        &app,
        &connection,
        client.as_ref(),
        settings.rdp_scaling_mode,
        settings.language.as_deref(),
    )
}

#[tauri::command]
pub fn password_state(connection: Connection) -> Result<PasswordState, AppError> {
    password::password_state(&connection)
}

#[tauri::command]
pub fn save_password(connection: Connection, password: String) -> Result<(), AppError> {
    password::save_password(&connection, &password)
}

#[tauri::command]
pub fn delete_password(connection: Connection) -> Result<(), AppError> {
    password::delete_password(&connection)
}
