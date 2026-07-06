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

// Build the ssh argument vector. Extracted from open_ssh so the arg logic (port only when != 22,
// the `--` separator right before the target, the -i key path, the user@host assembly) is unit-
// tested without touching the terminal I/O (6.32).
fn build_ssh_args(connection: &Connection) -> Result<Vec<String>, AppError> {
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
    Ok(args)
}

pub fn open_ssh(connection: &Connection) -> Result<(), AppError> {
    let args = build_ssh_args(connection)?;

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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::ConnectionKind;

    fn conn(
        host: Option<&str>,
        port: Option<u16>,
        username: Option<&str>,
        key_path: Option<&str>,
    ) -> Connection {
        Connection {
            id: "id".into(),
            name: "n".into(),
            kind: ConnectionKind::Ssh,
            host: host.map(String::from),
            port,
            username: username.map(String::from),
            domain: None,
            key_path: key_path.map(String::from),
            url: None,
            notes: None,
            tags: vec![],
            trust_cert: false,
            last_used: None,
            server_id: None,
        }
    }

    #[test]
    fn args_omit_port_for_default_22_and_place_separator_before_target() {
        let args = build_ssh_args(&conn(Some("h"), Some(22), Some("u"), None)).unwrap();
        assert_eq!(args, vec!["--", "u@h"]); // no -p, target after the -- separator
    }

    #[test]
    fn args_include_port_when_non_default() {
        let args = build_ssh_args(&conn(Some("h"), Some(2222), Some("u"), None)).unwrap();
        assert_eq!(args, vec!["-p", "2222", "--", "u@h"]);
    }

    #[test]
    fn args_include_key_path_with_i_flag() {
        let args =
            build_ssh_args(&conn(Some("h"), None, Some("u"), Some("/k/id_ed25519"))).unwrap();
        assert_eq!(args, vec!["-i", "/k/id_ed25519", "--", "u@h"]);
    }

    #[test]
    fn args_drop_empty_username_and_key_path() {
        let args = build_ssh_args(&conn(Some("h"), None, Some("  "), Some("  "))).unwrap();
        assert_eq!(args, vec!["--", "h"]); // no user@, no -i
    }

    #[test]
    fn args_reject_missing_or_empty_host() {
        assert!(build_ssh_args(&conn(None, None, Some("u"), None)).is_err());
        assert!(build_ssh_args(&conn(Some(""), None, Some("u"), None)).is_err());
    }

    #[test]
    fn command_prefixes_ssh_and_shell_escapes_each_arg() {
        // build_ssh_command single-quotes every arg (shell_escape); the injection-safety of that
        // escaping is covered in terminal.rs. The `--` separator + quoting keep the target inert.
        let cmd = build_ssh_command(&["-p".into(), "2222".into(), "--".into(), "u@h".into()]);
        assert_eq!(cmd, "ssh '-p' '2222' '--' 'u@h'");
    }
}
