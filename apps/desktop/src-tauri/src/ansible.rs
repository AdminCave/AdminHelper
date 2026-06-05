// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::io::Write;

use crate::error::AppError;
use crate::terminal::{open_linux_terminal, open_windows_terminal, which};

#[derive(Debug, serde::Deserialize)]
pub struct AnsibleTarget {
    pub hostname: String,
    pub groups: Vec<String>,
}

fn shell_escape(s: &str) -> String {
    format!("'{}'", s.replace('\'', "'\\''"))
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

/// Starts ansible-playbook in a native terminal.
pub fn launch_ansible(inventory_path: &str, playbook_path: &str) -> Result<(), AppError> {
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
