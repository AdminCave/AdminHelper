// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::path::PathBuf;
use std::process::Command;

use crate::error::AppError;

pub struct TerminalProfile {
    pub bin: &'static str,
    pub mode: TerminalMode,
}

impl TerminalProfile {
    pub const fn new(bin: &'static str, mode: TerminalMode) -> Self {
        Self { bin, mode }
    }
}

pub enum TerminalMode {
    DashE,
    DoubleDash,
    Wezterm,
}

pub fn which(binary: &str) -> Option<PathBuf> {
    let path_var = std::env::var_os("PATH")?;
    let paths = std::env::split_paths(&path_var);
    for path in paths {
        let candidate = path.join(binary);
        if candidate.is_file() {
            return Some(candidate);
        }
        if cfg!(target_os = "windows") {
            let candidate_exe = path.join(format!("{binary}.exe"));
            if candidate_exe.is_file() {
                return Some(candidate_exe);
            }
        }
    }
    None
}

pub fn open_linux_terminal(command: &str, args: &[String]) -> Result<(), AppError> {
    let profiles = [
        TerminalProfile::new("x-terminal-emulator", TerminalMode::DashE),
        TerminalProfile::new("gnome-terminal", TerminalMode::DoubleDash),
        TerminalProfile::new("konsole", TerminalMode::DashE),
        TerminalProfile::new("xfce4-terminal", TerminalMode::DashE),
        TerminalProfile::new("xterm", TerminalMode::DashE),
        TerminalProfile::new("alacritty", TerminalMode::DashE),
        TerminalProfile::new("kitty", TerminalMode::DashE),
        TerminalProfile::new("wezterm", TerminalMode::Wezterm),
    ];

    for profile in profiles.iter() {
        if which(profile.bin).is_none() {
            continue;
        }
        let result = match profile.mode {
            TerminalMode::DashE => {
                let mut terminal_args = vec!["-e".to_string(), command.to_string()];
                terminal_args.extend(args.iter().cloned());
                Command::new(profile.bin).args(terminal_args).spawn()
            }
            TerminalMode::DoubleDash => {
                let mut terminal_args = vec!["--".to_string(), command.to_string()];
                terminal_args.extend(args.iter().cloned());
                Command::new(profile.bin).args(terminal_args).spawn()
            }
            TerminalMode::Wezterm => {
                let mut terminal_args =
                    vec!["start".to_string(), "--".to_string(), command.to_string()];
                terminal_args.extend(args.iter().cloned());
                Command::new(profile.bin).args(terminal_args).spawn()
            }
        };

        return result.map(|_| ()).map_err(AppError::from);
    }

    Err(AppError::Connection("Kein Terminal gefunden".to_string()))
}

pub fn open_windows_terminal(command: &str, args: &[String]) -> Result<(), AppError> {
    if which("wt").is_some() {
        let mut wt_args = vec![
            "-w".to_string(),
            "0".to_string(),
            "new-tab".to_string(),
            "--".to_string(),
        ];
        wt_args.push(command.to_string());
        wt_args.extend(args.iter().cloned());
        Command::new("wt").args(wt_args).spawn()?;
        return Ok(());
    }

    let cmdline = build_windows_cmdline(command, args);
    Command::new("cmd")
        .args(["/C", "start", "", "cmd", "/K", &cmdline])
        .spawn()?;
    Ok(())
}

pub fn build_windows_cmdline(command: &str, args: &[String]) -> String {
    let mut parts = Vec::new();
    parts.push(windows_quote(command));
    for arg in args {
        parts.push(windows_quote(arg));
    }
    parts.join(" ")
}

pub fn windows_quote(value: &str) -> String {
    if value
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || "-._/:@\\".contains(ch))
    {
        return value.to_string();
    }
    let escaped: String = value
        .chars()
        .flat_map(|c| match c {
            '"' => vec!['^', '"'],
            '%' | '!' | '^' | '&' | '|' | '<' | '>' | '(' | ')' => vec!['^', c],
            _ => vec![c],
        })
        .collect();
    format!("\"{escaped}\"")
}
