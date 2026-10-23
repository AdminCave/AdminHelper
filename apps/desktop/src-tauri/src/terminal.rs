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
        let wt_args = wt_new_tab_args(command, args)?;
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

/// Arguments for `wt -w 0 new-tab -- <command> <args…>` that reach `command` unchanged.
///
/// wt splits its own command line at every `;` without a `\` before it, behind `--` too, and
/// reads `\;` as a literal `;` (learn.microsoft.com/en-us/windows/terminal/command-line-arguments;
/// microsoft/terminal `AppCommandlineArgs::_addCommandsForArg`, `Commandline::AddArg`), so every
/// `;` goes out as `\;`. wt then joins the arguments into one command line and wraps only an
/// argument with a space in `"…"`, escaping nothing (`_getNewTerminalArgs`): an empty argument,
/// a `"`, a control character (a tab splits) or a space with a trailing `\` (the program reads the
/// closing `\"` as a literal quote) would reach the program as other arguments. Before it starts
/// the program, wt expands `%NAME%` in that command line (microsoft/terminal
/// `ConptyConnection.cpp`, `ExpandEnvironmentStringsW`), so a `%` could change the value too.
/// All of those are refused before anything starts.
pub fn wt_new_tab_args(command: &str, args: &[String]) -> Result<Vec<String>, AppError> {
    let mut wt_args = vec![
        "-w".to_string(),
        "0".to_string(),
        "new-tab".to_string(),
        "--".to_string(),
    ];
    for value in std::iter::once(command).chain(args.iter().map(String::as_str)) {
        if let Some(problem) = wt_unpassable(value) {
            return Err(AppError::Validation(format!(
                "Windows Terminal cannot pass {problem} unchanged; nothing was opened"
            )));
        }
        wt_args.push(value.replace(';', "\\;"));
    }
    Ok(wt_args)
}

fn wt_unpassable(value: &str) -> Option<String> {
    if value.is_empty() {
        return Some("an empty argument".to_string());
    }
    if value.contains('"') {
        return Some("an argument with '\"'".to_string());
    }
    if value.contains('%') {
        return Some("an argument with '%'".to_string());
    }
    if let Some(ch) = value.chars().find(|c| c.is_control()) {
        let code = u32::from(ch);
        return Some(format!(
            "an argument with the control character U+{code:04X}"
        ));
    }
    if value.contains(' ') && value.ends_with('\\') {
        return Some("an argument with a space and a trailing '\\'".to_string());
    }
    None
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

    fn strings(values: &[&str]) -> Vec<String> {
        values.iter().map(|v| v.to_string()).collect()
    }

    fn wt_tail(command: &str, args: &[&str]) -> Vec<String> {
        let wt_args = wt_new_tab_args(command, &strings(args)).expect("wt args");
        assert_eq!(wt_args[..4], strings(&["-w", "0", "new-tab", "--"]));
        wt_args[4..].to_vec()
    }

    #[test]
    fn wt_new_tab_args_escape_every_semicolon() {
        assert_eq!(
            wt_tail("ssh", &["semi;colon", ";lead", "a\\;b", "a;;b"]),
            strings(&["ssh", "semi\\;colon", "\\;lead", "a\\\\;b", "a\\;\\;b"])
        );
        assert_eq!(wt_tail("my;tool", &["x"]), strings(&["my\\;tool", "x"]));
    }

    #[test]
    fn wt_new_tab_args_keep_values_without_semicolon() {
        assert_eq!(
            wt_new_tab_args("ssh", &strings(&["-p", "2222", "--", "u@h"])).expect("wt args"),
            strings(&["-w", "0", "new-tab", "--", "ssh", "-p", "2222", "--", "u@h"])
        );
    }

    #[test]
    fn wt_new_tab_args_reject_values_wt_cannot_pass_unchanged() {
        for (bad, named) in [
            ("a\"b", "'\"'"),
            ("a\tb", "U+0009"),
            ("", "empty"),
            ("C:\\dir with space\\", "trailing '\\'"),
            ("%USERNAME%", "'%'"),
            ("50%", "'%'"),
        ] {
            match wt_new_tab_args("ssh", &strings(&["-i", bad, "--", "u@h"])) {
                Err(AppError::Validation(msg)) => {
                    assert!(msg.contains(named), "{bad:?}: {msg}")
                }
                other => panic!("{bad:?} must be rejected, got {other:?}"),
            }
        }
        for bad_command in ["ss\"h", "%SystemRoot%\\ssh"] {
            assert!(
                matches!(
                    wt_new_tab_args(bad_command, &[]),
                    Err(AppError::Validation(_))
                ),
                "{bad_command:?} must be rejected"
            );
        }
    }

    #[test]
    fn wt_new_tab_args_pass_trailing_backslash_or_space_alone() {
        assert_eq!(
            wt_tail("ssh", &["C:\\dir\\", "C:\\Program Files\\key"]),
            strings(&["ssh", "C:\\dir\\", "C:\\Program Files\\key"])
        );
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
