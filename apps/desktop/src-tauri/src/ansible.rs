// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::io::Write;

use crate::error::AppError;
use crate::terminal::{open_linux_terminal, open_windows_terminal, shell_escape, which};

#[derive(Debug, serde::Deserialize)]
pub struct AnsibleTarget {
    pub hostname: String,
    pub groups: Vec<String>,
}

/// Creates a fresh temp file for our ansible scratch data. On Unix it is created
/// 0600 (the shared /tmp is world-readable), and everywhere `create_new` (O_EXCL)
/// refuses to follow a pre-planted symlink at the predictable path. A stale file from
/// our own prior run is cleared first; a racing local attacker can then only cause the
/// O_EXCL open to fail, not overwrite a victim path or read the contents (3.55).
fn create_temp_file(path: &std::path::Path) -> std::io::Result<std::fs::File> {
    let _ = std::fs::remove_file(path);
    let mut opts = std::fs::OpenOptions::new();
    opts.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        opts.mode(0o600);
    }
    opts.open(path)
}

/// Generates an Ansible inventory file in INI format and returns the path.
pub fn generate_inventory(servers: &[AnsibleTarget]) -> Result<String, AppError> {
    // Host + group names arrive as attacker-controllable Tauri-command params and go straight into
    // the INI. Validate them like the ssh/rdp spawn paths do: a newline or [/] would otherwise
    // inject extra inventory lines or group headers — at best a broken, hard-to-diagnose
    // inventory, at worst the playbook running against unintended targets (4.91).
    for server in servers {
        crate::validation::validate_host(&server.hostname)?;
        for tag in &server.groups {
            crate::validation::validate_no_control_chars(tag, "Gruppe")?;
            if tag.contains(['[', ']']) {
                return Err(AppError::Validation("Ungueltiger Gruppenname".to_string()));
            }
        }
    }
    let mut content = String::from("[all]\n");
    for server in servers {
        content.push_str(&server.hostname);
        content.push('\n');
    }
    content.push('\n');

    // Build groups from tags
    let mut groups: std::collections::HashMap<&str, Vec<&str>> = std::collections::HashMap::new();
    for server in servers {
        for tag in &server.groups {
            groups
                .entry(tag.as_str())
                .or_default()
                .push(&server.hostname);
        }
    }
    let mut sorted_groups: Vec<_> = groups.into_iter().collect();
    sorted_groups.sort_by_key(|(k, _)| *k);
    for (group, hosts) in sorted_groups {
        content.push_str(&format!("[{}]\n", group));
        for host in hosts {
            content.push_str(host);
            content.push('\n');
        }
        content.push('\n');
    }

    let path = std::env::temp_dir().join(format!(
        "adminhelper_ansible_inventory_{}.ini",
        std::process::id()
    ));
    let mut file = create_temp_file(&path)?;
    file.write_all(content.as_bytes())?;

    Ok(path.to_string_lossy().to_string())
}

/// Writes the playbook content to a temporary file and returns the path.
pub fn write_playbook_temp(filename: &str, content: &str) -> Result<String, AppError> {
    let safe_name = filename
        .replace(['/', '\\'], "_")
        .replace("..", "_")
        .trim()
        .to_string();
    let path = std::env::temp_dir().join(format!("adminhelper_ansible_{}", safe_name));
    let mut file = create_temp_file(&path)?;
    file.write_all(content.as_bytes())?;

    Ok(path.to_string_lossy().to_string())
}

/// True only for one of our own ansible temp files: after resolving symlinks and
/// `..`, the path must sit directly inside the system temp dir and carry our
/// `adminhelper_ansible` prefix. Guards `launch_ansible` against a (compromised)
/// frontend pointing `ansible-playbook` at an arbitrary attacker-controlled YAML
/// — an ansible playbook runs arbitrary commands, so an unconfined path is RCE.
fn is_confined_ansible_path(path: &str) -> bool {
    let canon = match std::fs::canonicalize(path) {
        Ok(p) => p,
        Err(_) => return false,
    };
    let temp = match std::fs::canonicalize(std::env::temp_dir()) {
        Ok(p) => p,
        Err(_) => return false,
    };
    if canon.parent() != Some(temp.as_path()) {
        return false;
    }
    canon
        .file_name()
        .and_then(|name| name.to_str())
        .map(|name| name.starts_with("adminhelper_ansible"))
        .unwrap_or(false)
}

/// Starts ansible-playbook in a native terminal.
pub fn launch_ansible(inventory_path: &str, playbook_path: &str) -> Result<(), AppError> {
    if !is_confined_ansible_path(inventory_path) || !is_confined_ansible_path(playbook_path) {
        return Err(AppError::Validation(
            "Ansible-Pfad ausserhalb des erlaubten Temp-Verzeichnisses".to_string(),
        ));
    }
    if which("ansible-playbook").is_none() {
        return Err(AppError::Connection(
            "ansible-playbook wurde nicht gefunden. Bitte Ansible installieren.".to_string(),
        ));
    }

    if cfg!(target_os = "windows") {
        open_windows_terminal(
            "ansible-playbook",
            &[
                "-i".to_string(),
                inventory_path.to_string(),
                playbook_path.to_string(),
            ],
        )
    } else {
        let ansible_cmd = format!(
            "ansible-playbook -i {} {}",
            shell_escape(inventory_path),
            shell_escape(playbook_path)
        );
        let bash_args = vec![
            "-c".to_string(),
            format!(
                "{}; echo ''; echo 'Ansible beendet. Druecke Enter zum Schliessen.'; read",
                ansible_cmd
            ),
        ];
        open_linux_terminal("bash", &bash_args)
    }
}

#[cfg(test)]
mod tests {
    use super::{
        create_temp_file, generate_inventory, is_confined_ansible_path, write_playbook_temp,
        AnsibleTarget,
    };
    use std::fs;

    #[test]
    fn generate_inventory_rejects_host_and_group_injection() {
        // 4.91: a hostname with a newline or a group name with [/] must be rejected — otherwise it
        // injects extra inventory lines or group headers into the INI.
        let bad_host = vec![AnsibleTarget {
            hostname: "host\nevil ansible_connection=local".to_string(),
            groups: vec![],
        }];
        assert!(generate_inventory(&bad_host).is_err());

        let bad_group = vec![AnsibleTarget {
            hostname: "host".to_string(),
            groups: vec!["[evil]".to_string()],
        }];
        assert!(generate_inventory(&bad_group).is_err());

        // A clean target still passes.
        let ok = vec![AnsibleTarget {
            hostname: "web01.example.com".to_string(),
            groups: vec!["web".to_string()],
        }];
        assert!(generate_inventory(&ok).is_ok());
    }

    #[test]
    fn generate_inventory_builds_group_sections() {
        let targets = vec![
            AnsibleTarget {
                hostname: "web01".to_string(),
                groups: vec!["web".to_string()],
            },
            AnsibleTarget {
                hostname: "db01".to_string(),
                groups: vec!["db".to_string()],
            },
        ];
        let path = generate_inventory(&targets).unwrap();
        let content = fs::read_to_string(&path).unwrap();
        let _ = fs::remove_file(&path);
        assert!(
            content.contains("[all]\nweb01\ndb01\n"),
            "all section: {content}"
        );
        assert!(
            content.contains("[db]\ndb01\n"),
            "db group (sorted first): {content}"
        );
        assert!(content.contains("[web]\nweb01\n"), "web group: {content}");
    }

    #[test]
    fn write_playbook_temp_sanitizes_traversal() {
        // Path separators and .. in the filename must be neutralized so the written playbook stays a
        // confined adminhelper_ansible temp file (an unconfined path is RCE via ansible-playbook).
        let path = write_playbook_temp("../../etc/passwd", "- hosts: all\n").unwrap();
        assert!(
            is_confined_ansible_path(&path),
            "traversal filename escaped temp: {path}"
        );
        assert!(!path.contains(".."), "'..' not sanitized: {path}");
        let _ = fs::remove_file(&path);
    }

    #[test]
    fn confines_ansible_paths_to_own_temp_files() {
        let dir = std::env::temp_dir();
        let pid = std::process::id();

        // One of our own temp files: accepted.
        let ours = dir.join(format!("adminhelper_ansible_confine_test_{pid}.yml"));
        fs::write(&ours, b"- hosts: all\n").unwrap();
        assert!(is_confined_ansible_path(ours.to_str().unwrap()));

        // A real temp file without our prefix: rejected.
        let foreign = dir.join(format!("evil_playbook_{pid}.yml"));
        fs::write(&foreign, b"- hosts: all\n").unwrap();
        assert!(!is_confined_ansible_path(foreign.to_str().unwrap()));

        // A traversal escape out of temp resolving to an existing file: rejected.
        let escape = dir.join(format!("adminhelper_ansible_{pid}/../../etc/hostname"));
        assert!(!is_confined_ansible_path(escape.to_str().unwrap()));

        // A non-existent path: rejected (cannot be canonicalized).
        assert!(!is_confined_ansible_path(
            dir.join("adminhelper_ansible_does_not_exist.yml")
                .to_str()
                .unwrap()
        ));

        let _ = fs::remove_file(&ours);
        let _ = fs::remove_file(&foreign);
    }

    #[test]
    fn create_temp_file_is_exclusive_and_hardened() {
        let dir = std::env::temp_dir();
        let path = dir.join(format!(
            "adminhelper_ansible_create_test_{}",
            std::process::id()
        ));
        let _ = fs::remove_file(&path);

        let f = create_temp_file(&path).unwrap();
        drop(f);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = fs::metadata(&path).unwrap().permissions().mode();
            assert_eq!(mode & 0o777, 0o600, "ansible temp file must be 0600");
        }
        // A second call over our own stale file still succeeds (remove-first).
        assert!(create_temp_file(&path).is_ok());
        let _ = fs::remove_file(&path);
    }

    #[cfg(unix)]
    #[test]
    fn create_temp_file_does_not_write_through_a_pre_planted_symlink() {
        let dir = std::env::temp_dir();
        let pid = std::process::id();
        let victim = dir.join(format!("adminhelper_ansible_victim_{pid}"));
        let link = dir.join(format!("adminhelper_ansible_symlink_{pid}"));
        let _ = fs::remove_file(&victim);
        let _ = fs::remove_file(&link);
        fs::write(&victim, b"important").unwrap();
        std::os::unix::fs::symlink(&victim, &link).unwrap();

        let f = create_temp_file(&link).unwrap();
        drop(f);
        // The symlink was unlinked (remove-first) and a fresh regular file created —
        // the victim it pointed at is untouched, not truncated through the link.
        assert_eq!(
            fs::read(&victim).unwrap(),
            b"important",
            "victim must be untouched"
        );
        assert!(
            !fs::symlink_metadata(&link)
                .unwrap()
                .file_type()
                .is_symlink(),
            "link must now be a fresh regular file, not a symlink"
        );
        let _ = fs::remove_file(&victim);
        let _ = fs::remove_file(&link);
    }
}
