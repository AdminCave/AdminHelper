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

/// Generates an Ansible inventory file in INI format and returns the path.
pub fn generate_inventory(servers: &[AnsibleTarget]) -> Result<String, AppError> {
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
    let mut file = std::fs::File::create(&path)?;
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
    let mut file = std::fs::File::create(&path)?;
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
    use super::is_confined_ansible_path;
    use std::fs;

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
}
