// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::path::{Path, PathBuf};

use crate::error::AppError;
use crate::models::{Connection, SshAuthMethod, SshForwardKind, SshOptions};
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
// tested without touching the terminal I/O (6.32). The embedded terminal starts ssh with the
// same argv (R-1069).
pub(crate) fn build_ssh_args(connection: &Connection) -> Result<Vec<String>, AppError> {
    let (mut args, target) = base_args(connection, true)?;
    args.push("--".to_string());
    args.push(target);
    Ok(args)
}

/// The argv of the `ssh` that carries the SFTP channel of a terminal session (R-1072): the
/// switches of the connection without its forwards and agent forwarding (a second ssh would
/// bind the forwards again), never a prompt (`BatchMode`), over the ControlMaster socket of the
/// session when it has one, then the `sftp` subsystem. The `-o` switches below clear what
/// `~/.ssh/config` sets for the host as well, as sftp(1) does: the first value ssh reads wins.
pub(crate) fn build_sftp_args(
    connection: &Connection,
    control_path: Option<&Path>,
) -> Result<Vec<String>, AppError> {
    let (mut args, target) = base_args(connection, false)?;
    for option in [
        "BatchMode=yes",
        "ClearAllForwardings=yes",
        "ForwardAgent=no",
        "ForwardX11=no",
        "PermitLocalCommand=no",
    ] {
        args.push("-o".to_string());
        args.push(option.to_string());
    }
    if let Some(path) = control_path {
        args.extend(control_args(path, false));
    }
    args.extend(["-s", "--"].map(String::from));
    args.push(target);
    args.push("sftp".to_string());
    Ok(args)
}

/// The socket in a ControlMaster directory ([`control_dir_base`]).
pub(crate) const CONTROL_SOCKET: &str = "c";

/// The name of every ControlMaster directory starts with this.
pub(crate) const CONTROL_DIR_PREFIX: &str = "ah-ssh-";

/// The longest socket path handed to ssh: it binds `<path>.<16 characters>` first and renames
/// it then (OpenSSH mux.c), and `sun_path` holds 104 bytes on macOS, 108 on Linux.
const CONTROL_PATH_MAX: usize = 80;

/// Where the ControlMaster directory of a session goes: `temp` while the socket path in it stays
/// short and plain, else `/tmp`. ssh splits an `-o` value at blanks and expands `%` in it.
pub(crate) fn control_dir_base(temp: &Path) -> PathBuf {
    // The longest name `create_private_dir` gives: pid, counter, nanoseconds.
    let longest = temp
        .join(format!(
            "{CONTROL_DIR_PREFIX}{}_{}_{}",
            u32::MAX,
            u64::MAX,
            u64::MAX
        ))
        .join(CONTROL_SOCKET);
    let plain = temp.to_str().is_some_and(|text| {
        text.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"/._-".contains(&b))
    });
    if plain && longest.as_os_str().len() <= CONTROL_PATH_MAX {
        temp.to_path_buf()
    } else {
        PathBuf::from("/tmp")
    }
}

/// The switches of an ssh that holds its connection for others at `path` (`master`), ending
/// with it, or of one that goes over that connection.
pub(crate) fn control_args(path: &Path, master: bool) -> Vec<String> {
    let mut args = vec![
        "-o".to_string(),
        format!("ControlMaster={}", yes_no(master)),
        "-o".to_string(),
        format!("ControlPath={}", path.display()),
    ];
    if master {
        args.extend(["-o", "ControlPersist=no"].map(String::from));
    }
    args
}

/// The switches of `connection` and its target; forwards and agent forwarding only for the
/// `terminal`.
fn base_args(connection: &Connection, terminal: bool) -> Result<(Vec<String>, String), AppError> {
    // Host, user and key_path are validated at the boundary — open_connection and
    // terminal_open_ssh run validate_connection_input before this, and they are the only
    // callers. Only the empty-host guard stays: the boundary allows an empty host, we don't
    // (2.80).
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
    if let Some(ssh) = connection.options.as_ref().and_then(|o| o.ssh.as_ref()) {
        push_option_args(&mut args, ssh, terminal);
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
    Ok((args, target))
}

fn yes_no(value: bool) -> &'static str {
    if value {
        "yes"
    } else {
        "no"
    }
}

// The per-connection options (R-1066), already checked by validate_ssh_options. Switches as in
// ssh(1) and ssh_config(5); booleans go through -o so that an explicit "off" overrides a
// ~/.ssh/config that turns them on.
fn push_option_args(args: &mut Vec<String>, ssh: &SshOptions, terminal: bool) {
    if let Some(ref jump) = ssh.jump_host {
        args.push("-J".to_string());
        args.push(jump.clone());
    }
    let forwards = if terminal {
        ssh.forwards.as_slice()
    } else {
        &[]
    };
    for forward in forwards {
        let (flag, spec) = match (forward.kind, forward.target.as_deref()) {
            (SshForwardKind::L, Some(target)) => ("-L", format!("{}:{target}", forward.listen)),
            (SshForwardKind::R, Some(target)) => ("-R", format!("{}:{target}", forward.listen)),
            (SshForwardKind::D, _) => ("-D", forward.listen.clone()),
            // L/R without a target never pass validation; skip rather than build half a switch.
            _ => continue,
        };
        args.push(flag.to_string());
        args.push(spec);
    }
    let mut option = |key: &str, value: &str| {
        args.push("-o".to_string());
        args.push(format!("{key}={value}"));
    };
    if let Some(agent) = ssh.agent_forwarding.filter(|_| terminal) {
        option("ForwardAgent", yes_no(agent));
    }
    if let Some(compression) = ssh.compression {
        option("Compression", yes_no(compression));
    }
    if let Some(keepalive) = ssh.keepalive {
        option("ServerAliveInterval", &keepalive.to_string());
    }
    match ssh.auth_method {
        Some(SshAuthMethod::Key) => {
            option("PreferredAuthentications", "publickey");
            option("IdentitiesOnly", "yes");
        }
        Some(SshAuthMethod::Agent) => option("PreferredAuthentications", "publickey"),
        Some(SshAuthMethod::Password) => {
            option("PreferredAuthentications", "password,keyboard-interactive")
        }
        None => {}
    }
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
            options: None,
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

    fn with_ssh_options(json: serde_json::Value) -> Connection {
        let mut c = conn(Some("h"), None, Some("u"), None);
        c.options = Some(serde_json::from_value(serde_json::json!({ "ssh": json })).unwrap());
        c
    }

    #[test]
    fn args_carry_every_ssh_option_before_the_separator() {
        let c = with_ssh_options(serde_json::json!({
            "jumpHost": "ops@bastion:2222,[2001:db8::1]",
            "forwards": [
                {"type": "L", "listen": "8080", "target": "intranet:80"},
                {"type": "R", "listen": "127.0.0.1:9000", "target": "[::1]:9000"},
                {"type": "D", "listen": "*:1080"}
            ],
            "agentForwarding": true,
            "compression": false,
            "keepalive": 30,
            "authMethod": "key"
        }));

        let args = build_ssh_args(&c).unwrap();

        assert_eq!(
            args,
            vec![
                "-J",
                "ops@bastion:2222,[2001:db8::1]",
                "-L",
                "8080:intranet:80",
                "-R",
                "127.0.0.1:9000:[::1]:9000",
                "-D",
                "*:1080",
                "-o",
                "ForwardAgent=yes",
                "-o",
                "Compression=no",
                "-o",
                "ServerAliveInterval=30",
                "-o",
                "PreferredAuthentications=publickey",
                "-o",
                "IdentitiesOnly=yes",
                "--",
                "u@h",
            ]
        );
    }

    #[test]
    fn args_map_each_auth_method() {
        let cases = [
            ("agent", vec!["-o", "PreferredAuthentications=publickey"]),
            (
                "password",
                vec![
                    "-o",
                    "PreferredAuthentications=password,keyboard-interactive",
                ],
            ),
        ];
        for (method, expected) in cases {
            let args = build_ssh_args(&with_ssh_options(
                serde_json::json!({ "authMethod": method }),
            ))
            .unwrap();
            assert_eq!(args[..args.len() - 2], expected[..], "{method}");
        }
    }

    #[test]
    fn args_leave_unset_options_to_the_global_default() {
        let args = build_ssh_args(&with_ssh_options(serde_json::json!({}))).unwrap();
        assert_eq!(args, vec!["--", "u@h"]);
        // An explicit "off" is passed on, so it beats a ~/.ssh/config that turns it on.
        let args = build_ssh_args(&with_ssh_options(
            serde_json::json!({"agentForwarding": false, "compression": true}),
        ))
        .unwrap();
        assert_eq!(
            args,
            vec![
                "-o",
                "ForwardAgent=no",
                "-o",
                "Compression=yes",
                "--",
                "u@h"
            ]
        );
    }

    #[test]
    fn command_prefixes_ssh_and_shell_escapes_each_arg() {
        // build_ssh_command single-quotes every arg (shell_escape); the injection-safety of that
        // escaping is covered in terminal.rs. The `--` separator + quoting keep the target inert.
        let cmd = build_ssh_command(&["-p".into(), "2222".into(), "--".into(), "u@h".into()]);
        assert_eq!(cmd, "ssh '-p' '2222' '--' 'u@h'");
    }

    #[test]
    fn sftp_args_leave_forwards_and_the_agent_out_and_never_prompt() {
        let c = with_ssh_options(serde_json::json!({
            "jumpHost": "ops@bastion:2222",
            "forwards": [
                {"type": "L", "listen": "8080", "target": "intranet:80"},
                {"type": "D", "listen": "*:1080"}
            ],
            "agentForwarding": true,
            "compression": false,
            "authMethod": "key"
        }));

        assert_eq!(
            build_sftp_args(&c, None).unwrap(),
            vec![
                "-J",
                "ops@bastion:2222",
                "-o",
                "Compression=no",
                "-o",
                "PreferredAuthentications=publickey",
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "BatchMode=yes",
                "-o",
                "ClearAllForwardings=yes",
                "-o",
                "ForwardAgent=no",
                "-o",
                "ForwardX11=no",
                "-o",
                "PermitLocalCommand=no",
                "-s",
                "--",
                "u@h",
                "sftp",
            ]
        );
        let terminal = build_ssh_args(&c).unwrap();
        assert!(
            terminal.contains(&"-L".to_string())
                && terminal.contains(&"ForwardAgent=yes".to_string())
        );
    }

    #[test]
    fn sftp_args_go_over_the_control_master_of_the_session() {
        let c = conn(Some("h"), Some(2222), Some("u"), Some("/k/id"));
        let path = Path::new("/tmp/ah-ssh-1_2_3").join(CONTROL_SOCKET);
        let control = format!("ControlPath={}", path.display());
        assert_eq!(
            build_sftp_args(&c, Some(&path)).unwrap(),
            [
                "-p",
                "2222",
                "-i",
                "/k/id",
                "-o",
                "BatchMode=yes",
                "-o",
                "ClearAllForwardings=yes",
                "-o",
                "ForwardAgent=no",
                "-o",
                "ForwardX11=no",
                "-o",
                "PermitLocalCommand=no",
                "-o",
                "ControlMaster=no",
                "-o",
                control.as_str(),
                "-s",
                "--",
                "u@h",
                "sftp",
            ]
        );
        assert_eq!(
            build_ssh_args(&c).unwrap(),
            ["-p", "2222", "-i", "/k/id", "--", "u@h"],
            "the terminal keeps its argv"
        );
    }

    #[test]
    fn the_control_master_holds_the_connection_and_ends_with_its_session() {
        let path = Path::new("/tmp/d").join(CONTROL_SOCKET);
        let control = format!("ControlPath={}", path.display());
        assert_eq!(
            control_args(&path, true),
            [
                "-o",
                "ControlMaster=yes",
                "-o",
                control.as_str(),
                "-o",
                "ControlPersist=no"
            ]
        );
        assert_eq!(
            control_args(&path, false),
            ["-o", "ControlMaster=no", "-o", control.as_str()]
        );
    }

    #[test]
    fn the_control_directory_stays_in_a_short_plain_temp_dir() {
        for temp in ["/tmp", "/run/user/1000"] {
            assert_eq!(control_dir_base(Path::new(temp)), Path::new(temp));
        }
        let long = format!("/var/folders/{}/T", "x".repeat(40));
        for temp in [long.as_str(), "/home/a b/tmp", "/tmp/100%", "/tmp/\u{e4}"] {
            assert_eq!(
                control_dir_base(Path::new(temp)),
                Path::new("/tmp"),
                "{temp}"
            );
        }
    }
}
