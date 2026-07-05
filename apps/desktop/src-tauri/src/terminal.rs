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

/// Spawn a detached reaper for a launcher process. Rust does not reap children on Child drop, so
/// a terminal launcher that delegates to a server process and exits immediately (gnome-terminal,
/// wt, `cmd /C start`) would otherwise linger as a <defunct> zombie in the process table until the
/// app exits — an admin opening dozens of sessions a day accumulates that many (4.96).
fn reap_async(mut child: std::process::Child) {
    std::thread::spawn(move || {
        let _ = child.wait();
    });
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

    let mut last_err: Option<std::io::Error> = None;
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

        match result {
            Ok(child) => {
                reap_async(child);
                return Ok(());
            }
            // Spawn failed (e.g. a broken x-terminal-emulator alternative) — the
            // list is a real fallback chain, so try the next terminal (2.88).
            Err(e) => last_err = Some(e),
        }
    }

    Err(last_err
        .map(AppError::from)
        .unwrap_or_else(|| AppError::Connection("Kein Terminal gefunden".to_string())))
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
        reap_async(Command::new("wt").args(wt_args).spawn()?);
        return Ok(());
    }

    let cmdline = build_windows_cmdline(command, args);
    reap_async(
        Command::new("cmd")
            .args(["/C", "start", "", "cmd", "/K", &cmdline])
            .spawn()?,
    );
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

/// POSIX-shell single-quote escaping for a value interpolated into a `bash -c`
/// command line: wrap in single quotes and escape any embedded single quote.
/// Security-relevant — the single shared copy so a hardening can't miss a caller.
pub fn shell_escape(s: &str) -> String {
    format!("'{}'", s.replace('\'', "'\\''"))
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn windows_quote_passes_safe_values_through() {
        assert_eq!(windows_quote("ssh"), "ssh");
        assert_eq!(windows_quote("C:\\Tools\\ssh.exe"), "C:\\Tools\\ssh.exe");
        assert_eq!(windows_quote("user@host"), "user@host");
        assert_eq!(windows_quote("-p"), "-p");
    }

    #[test]
    fn windows_quote_quotes_and_escapes_metacharacters() {
        assert_eq!(windows_quote("two words"), "\"two words\"");
        assert_eq!(windows_quote("a\"b"), "\"a^\"b\"");
        assert_eq!(windows_quote("100%"), "\"100^%\"");
        assert_eq!(windows_quote("a&b|c"), "\"a^&b^|c\"");
        assert_eq!(windows_quote("x>y<z"), "\"x^>y^<z\"");
        assert_eq!(windows_quote("(test)"), "\"^(test^)\"");
        assert_eq!(windows_quote("bang!"), "\"bang^!\"");
        assert_eq!(windows_quote("car^et"), "\"car^^et\"");
    }

    #[test]
    fn shell_escape_wraps_and_escapes_single_quotes() {
        // Plain values are single-quoted (safe against every POSIX metacharacter).
        assert_eq!(shell_escape("host"), "'host'");
        assert_eq!(shell_escape("a b; rm -rf /"), "'a b; rm -rf /'");
        assert_eq!(shell_escape("$(evil)"), "'$(evil)'");
        // An embedded single quote is broken out and re-escaped so it can't end
        // the quoting early (the injection this guards against).
        assert_eq!(shell_escape("O'Brien"), "'O'\\''Brien'");
        assert_eq!(shell_escape("'; id; '"), "''\\''; id; '\\'''");
    }

    #[test]
    fn build_windows_cmdline_joins_quoted_parts() {
        let args = vec![
            "-p".to_string(),
            "2222".to_string(),
            "user@host name".to_string(),
        ];
        assert_eq!(
            build_windows_cmdline("ssh", &args),
            "ssh -p 2222 \"user@host name\""
        );
        assert_eq!(build_windows_cmdline("ssh", &[]), "ssh");
    }
}
