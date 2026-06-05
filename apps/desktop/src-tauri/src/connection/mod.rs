// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

pub mod rdp;
pub mod ssh;
pub mod web;

use crate::error::AppError;
use crate::models::{ClientInfo, Connection, ConnectionKind, RdpOptions};
use crate::validation::validate_connection_input;

pub fn open_connection(
    connection: &Connection,
    password: Option<&str>,
    client: Option<&ClientInfo>,
    rdp: RdpOptions,
    ui_language: Option<&str>,
    correlation_id: &str,
    app: &tauri::AppHandle,
) -> Result<(), AppError> {
    validate_connection_input(connection)?;
    match connection.kind {
        ConnectionKind::Ssh => ssh::open_ssh(connection),
        ConnectionKind::Rdp => rdp::open_rdp(
            connection,
            password,
            client,
            rdp,
            ui_language,
            correlation_id,
            app,
        ),
        ConnectionKind::Web => web::open_web(connection),
    }
}

pub fn open_connection_stored(
    app: &tauri::AppHandle,
    connection: &Connection,
    client: Option<&ClientInfo>,
    rdp: RdpOptions,
    ui_language: Option<&str>,
    correlation_id: &str,
) -> Result<(), AppError> {
    validate_connection_input(connection)?;
    match connection.kind {
        ConnectionKind::Rdp => {
            open_rdp_with_stored_password(app, connection, client, rdp, ui_language, correlation_id)
        }
        _ => open_connection(
            connection,
            None,
            client,
            rdp,
            ui_language,
            correlation_id,
            app,
        ),
    }
}

#[cfg(target_os = "windows")]
fn open_rdp_with_stored_password(
    app: &tauri::AppHandle,
    connection: &Connection,
    client: Option<&ClientInfo>,
    rdp: RdpOptions,
    ui_language: Option<&str>,
    correlation_id: &str,
) -> Result<(), AppError> {
    rdp::open_rdp(
        connection,
        None,
        client,
        rdp,
        ui_language,
        correlation_id,
        app,
    )
}

#[cfg(unix)]
fn open_rdp_with_stored_password(
    app: &tauri::AppHandle,
    connection: &Connection,
    client: Option<&ClientInfo>,
    rdp: RdpOptions,
    ui_language: Option<&str>,
    correlation_id: &str,
) -> Result<(), AppError> {
    let password = crate::password::load_password_keyring(connection)?;
    rdp::open_rdp(
        connection,
        password.as_deref(),
        client,
        rdp,
        ui_language,
        correlation_id,
        app,
    )
}

#[cfg(not(any(target_os = "windows", unix)))]
fn open_rdp_with_stored_password(
    app: &tauri::AppHandle,
    connection: &Connection,
    client: Option<&ClientInfo>,
    rdp: RdpOptions,
    ui_language: Option<&str>,
    correlation_id: &str,
) -> Result<(), AppError> {
    open_connection(
        connection,
        None,
        client,
        rdp,
        ui_language,
        correlation_id,
        app,
    )
}
