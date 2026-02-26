pub mod rdp;
pub mod ssh;
pub mod web;

use crate::error::AppError;
use crate::models::{ClientInfo, Connection, ConnectionKind};
use crate::validation::validate_connection_input;

pub fn open_connection(
    connection: &Connection,
    password: Option<&str>,
    client: Option<&ClientInfo>,
    app: &tauri::AppHandle,
) -> Result<(), AppError> {
    validate_connection_input(connection)?;
    match connection.kind {
        ConnectionKind::Ssh => ssh::open_ssh(connection),
        ConnectionKind::Rdp => rdp::open_rdp(connection, password, client, app),
        ConnectionKind::Web => web::open_web(connection),
    }
}

pub fn open_connection_stored(
    app: &tauri::AppHandle,
    connection: &Connection,
    client: Option<&ClientInfo>,
) -> Result<(), AppError> {
    validate_connection_input(connection)?;
    if connection.kind != ConnectionKind::Rdp {
        return open_connection(connection, None, client, app);
    }

    #[cfg(target_os = "windows")]
    {
        return rdp::open_rdp(connection, None, client, app);
    }

    #[cfg(unix)]
    {
        let password = crate::password::load_password_keyring(connection)?;
        rdp::open_rdp(connection, password.as_deref(), client, app)
    }

    #[cfg(not(any(target_os = "windows", unix)))]
    {
        return open_connection(connection, None, client, app);
    }
}
