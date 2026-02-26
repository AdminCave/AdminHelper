pub mod rdp;
pub mod ssh;
pub mod web;

use crate::error::AppError;
use crate::models::{ClientInfo, Connection, ConnectionKind, RdpScalingMode};
use crate::validation::validate_connection_input;

pub fn open_connection(
    connection: &Connection,
    password: Option<&str>,
    client: Option<&ClientInfo>,
    rdp_scaling_mode: RdpScalingMode,
    app: &tauri::AppHandle,
) -> Result<(), AppError> {
    validate_connection_input(connection)?;
    match connection.kind {
        ConnectionKind::Ssh => ssh::open_ssh(connection),
        ConnectionKind::Rdp => rdp::open_rdp(connection, password, client, rdp_scaling_mode, app),
        ConnectionKind::Web => web::open_web(connection),
    }
}

pub fn open_connection_stored(
    app: &tauri::AppHandle,
    connection: &Connection,
    client: Option<&ClientInfo>,
    rdp_scaling_mode: RdpScalingMode,
) -> Result<(), AppError> {
    validate_connection_input(connection)?;
    match connection.kind {
        ConnectionKind::Rdp => {
            open_rdp_with_stored_password(app, connection, client, rdp_scaling_mode)
        }
        _ => open_connection(connection, None, client, rdp_scaling_mode, app),
    }
}

#[cfg(target_os = "windows")]
fn open_rdp_with_stored_password(
    app: &tauri::AppHandle,
    connection: &Connection,
    client: Option<&ClientInfo>,
    rdp_scaling_mode: RdpScalingMode,
) -> Result<(), AppError> {
    rdp::open_rdp(connection, None, client, rdp_scaling_mode, app)
}

#[cfg(unix)]
fn open_rdp_with_stored_password(
    app: &tauri::AppHandle,
    connection: &Connection,
    client: Option<&ClientInfo>,
    rdp_scaling_mode: RdpScalingMode,
) -> Result<(), AppError> {
    let password = crate::password::load_password_keyring(connection)?;
    rdp::open_rdp(
        connection,
        password.as_deref(),
        client,
        rdp_scaling_mode,
        app,
    )
}

#[cfg(not(any(target_os = "windows", unix)))]
fn open_rdp_with_stored_password(
    app: &tauri::AppHandle,
    connection: &Connection,
    client: Option<&ClientInfo>,
    rdp_scaling_mode: RdpScalingMode,
) -> Result<(), AppError> {
    open_connection(connection, None, client, rdp_scaling_mode, app)
}
