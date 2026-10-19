// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

pub mod rdp;
pub mod rdp_logic;
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
    credential_connection: Option<&Connection>,
    client: Option<&ClientInfo>,
    rdp: RdpOptions,
    ui_language: Option<&str>,
    correlation_id: &str,
) -> Result<(), AppError> {
    validate_connection_input(connection)?;
    if let Some(credential) = credential_connection {
        validate_connection_input(credential)?;
        check_credential_connection(connection, credential)?;
    }
    match connection.kind {
        ConnectionKind::Rdp => open_rdp_with_stored_password(
            app,
            connection,
            credential_connection,
            client,
            rdp,
            ui_language,
            correlation_id,
        ),
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

/// The connection whose keyring entry holds the stored RDP password. A tunnelled
/// target arrives resolved to `127.0.0.1:<visitor port>`, but the UI checks and
/// saves the password under the connection as listed, so the caller passes
/// that one separately; without it the opened connection is its own source.
#[cfg_attr(not(unix), allow(dead_code))]
fn stored_password_source<'a>(
    connection: &'a Connection,
    credential_connection: Option<&'a Connection>,
) -> &'a Connection {
    credential_connection.unwrap_or(connection)
}

/// The credential connection is accepted only as the same connection as the
/// opened one: same id, kind, username and domain. A different host or port is
/// the tunnel form, so the opened connection must then point at loopback.
fn check_credential_connection(
    connection: &Connection,
    credential: &Connection,
) -> Result<(), AppError> {
    let same_identity = connection.id == credential.id
        && connection.kind == credential.kind
        && connection.username == credential.username
        && connection.domain == credential.domain;
    let same_target = connection.host == credential.host && connection.port == credential.port;
    let tunnel_form = connection.host.as_deref().is_some_and(is_loopback_host);
    if same_identity && (same_target || tunnel_form) {
        Ok(())
    } else {
        Err(AppError::Validation(
            "credential connection does not match the opened connection".to_string(),
        ))
    }
}

/// Loopback IPs (127.0.0.0/8, ::1) and `localhost`, like the server URL check in
/// `validation.rs`; `tunnel::resolve_connection` sets `127.0.0.1`.
fn is_loopback_host(host: &str) -> bool {
    host.eq_ignore_ascii_case("localhost")
        || host
            .parse::<std::net::IpAddr>()
            .is_ok_and(|ip| ip.is_loopback())
}

fn open_rdp_with_stored_password(
    app: &tauri::AppHandle,
    connection: &Connection,
    credential_connection: Option<&Connection>,
    client: Option<&ClientInfo>,
    rdp: RdpOptions,
    ui_language: Option<&str>,
    correlation_id: &str,
) -> Result<(), AppError> {
    // Only the unix launcher passes a password through to xfreerdp's stdin; the
    // Windows (.rdp file) and unsupported-OS paths pass none. Both connections
    // are already validated and matched by the sole caller, open_connection_stored.
    #[cfg(unix)]
    let password = crate::password::load_password_keyring(stored_password_source(
        connection,
        credential_connection,
    ))?;
    #[cfg(not(unix))]
    let password: Option<String> = {
        let _ = credential_connection;
        None
    };
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::password::rdp_storage_key;

    fn rdp(host: &str, port: u16) -> Connection {
        Connection {
            id: "c1".into(),
            name: "T".into(),
            kind: ConnectionKind::Rdp,
            host: Some(host.into()),
            port: Some(port),
            username: Some("Admin".into()),
            domain: Some("CORP".into()),
            key_path: None,
            url: None,
            notes: None,
            tags: Vec::new(),
            trust_cert: false,
            last_used: None,
            server_id: None,
        }
    }

    // The tunnel resolves a listed RDP target to the local visitor port; the
    // password lookup must still use the key the UI saved it under.
    #[test]
    fn stored_password_key_uses_credential_connection() {
        let listed = rdp("rdp.example.com", 3389);
        let resolved = rdp("127.0.0.1", 6000);
        let key = rdp_storage_key(stored_password_source(&resolved, Some(&listed)));
        assert_eq!(key.as_deref(), Some("rdp|rdp.example.com|3389|admin|corp"));
        assert_ne!(key, rdp_storage_key(&resolved));
    }

    #[test]
    fn stored_password_key_without_credential_connection_uses_connection() {
        let direct = rdp("192.0.2.10", 3390);
        let key = rdp_storage_key(stored_password_source(&direct, None));
        assert_eq!(key.as_deref(), Some("rdp|192.0.2.10|3390|admin|corp"));
    }

    fn assert_rejected(connection: &Connection, credential: &Connection) {
        assert!(
            matches!(
                check_credential_connection(connection, credential),
                Err(AppError::Validation(_))
            ),
            "{:?}:{:?} must not take the password source {:?}:{:?}",
            connection.host,
            connection.port,
            credential.host,
            credential.port
        );
    }

    #[test]
    fn stored_password_key_accepts_the_tunnel_form_of_the_same_connection() {
        let listed = rdp("rdp.example.com", 3389);
        for loopback in ["127.0.0.1", "::1", "localhost"] {
            let resolved = rdp(loopback, 6000);
            assert!(check_credential_connection(&resolved, &listed).is_ok());
            let key = rdp_storage_key(stored_password_source(&resolved, Some(&listed)));
            assert_eq!(key.as_deref(), Some("rdp|rdp.example.com|3389|admin|corp"));
        }
    }

    #[test]
    fn stored_password_key_accepts_the_same_connection_without_resolution() {
        let direct = rdp("192.0.2.10", 3390);
        assert!(check_credential_connection(&direct, &direct.clone()).is_ok());
    }

    #[test]
    fn stored_password_key_rejects_another_host_off_loopback() {
        let listed = rdp("rdp.example.com", 3389);
        assert_rejected(&rdp("198.51.100.7", 3389), &listed);
        assert_rejected(&rdp("198.51.100.7", 6000), &listed);
        // Same host, another port: still not the tunnel form.
        assert_rejected(&rdp("rdp.example.com", 6000), &listed);
    }

    #[test]
    fn stored_password_key_rejects_another_id() {
        let listed = rdp("rdp.example.com", 3389);
        let mut resolved = rdp("127.0.0.1", 6000);
        resolved.id = "c2".into();
        assert_rejected(&resolved, &listed);
    }

    #[test]
    fn stored_password_key_rejects_another_username() {
        let listed = rdp("rdp.example.com", 3389);
        let mut resolved = rdp("127.0.0.1", 6000);
        resolved.username = Some("Other".into());
        assert_rejected(&resolved, &listed);
        resolved.username = None;
        assert_rejected(&resolved, &listed);
    }

    #[test]
    fn stored_password_key_rejects_another_kind_or_domain() {
        let listed = rdp("rdp.example.com", 3389);
        let mut resolved = rdp("127.0.0.1", 6000);
        resolved.kind = ConnectionKind::Ssh;
        assert_rejected(&resolved, &listed);
        let mut resolved = rdp("127.0.0.1", 6000);
        resolved.domain = Some("OTHER".into());
        assert_rejected(&resolved, &listed);
    }
}
