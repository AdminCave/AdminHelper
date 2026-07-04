// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use crate::error::AppError;
use crate::models::Connection;
use crate::terminal::{open_linux_terminal, open_windows_terminal, shell_escape};
use crate::validation::required;

fn build_ssh_command(args: &[String]) -> String {
    let mut parts = vec!["ssh".to_string()];
    for arg in args {
        parts.push(shell_escape(arg));
    }
    parts.join(" ")
}

pub fn open_ssh(connection: &Connection) -> Result<(), AppError> {
    // Host, user and key_path are validated at the boundary — open_connection runs
    // validate_connection_input before this, and it's the sole caller. Only the
    // empty-host guard stays: the boundary allows an empty host, we don't (2.80).
    let host = required(&connection.host, "Host")?;
    let port = connection.port.unwrap_or(22);
    let mut args: Vec<String> = Vec::new();
    if port != 22 {
        args.push("-p".to_string());
        args.push(port.to_string());
    }
    if let Some(key_path) = connection.key_path.as_ref() {
        let trimmed = key_path.trim();
        if !trimmed.is_empty() {
            args.push("-i".to_string());
            args.push(trimmed.to_string());
        }
    }
    let target = if let Some(username) = connection.username.as_ref() {
        let u = username.trim();
        if !u.is_empty() {
            format!("{u}@{host}")
        } else {
            host.to_string()
        }
    } else {
        host.to_string()
    };
    args.push("--".to_string());
    args.push(target);

    if cfg!(target_os = "windows") {
        open_windows_terminal("ssh", &args)
    } else {
        // Wrap SSH in bash so the terminal stays open on connection failure
        let ssh_cmd = build_ssh_command(&args);
        let bash_args = vec![
            "-c".to_string(),
            format!("{ssh_cmd}; echo ''; echo 'Verbindung beendet. Druecke Enter zum Schliessen.'; read"),
        ];
        open_linux_terminal("bash", &bash_args)
    }
}
