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
/// wt) would otherwise linger as a <defunct> zombie in the process table until the app exits — an
/// admin opening dozens of sessions a day accumulates that many (4.96).
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

    let line = cmd_console_line(command, args)?;
    open_cmd_console(&line)
}

/// Opens `cmd <line>` in a console of its own.
#[cfg(windows)]
fn open_cmd_console(line: &str) -> Result<(), AppError> {
    // cmd is the console itself and runs until its window closes. Windows keeps nothing of a
    // process once its handles are closed, so nothing waits for it (unlike `reap_async`).
    drop(spawn_in_new_console(line)?);
    Ok(())
}

#[cfg(not(windows))]
fn open_cmd_console(_line: &str) -> Result<(), AppError> {
    Err(AppError::Connection(
        "A Windows console can only be opened on Windows".to_string(),
    ))
}

/// Starts `<system directory>\cmd.exe <line>` in a new console and returns its process handle.
///
/// Not through `std::process::Command`: that hands the child the standard handles of this process
/// (`STARTF_USESTDHANDLES`) whenever it has any, and Windows keeps them even for a new console
/// (learn.microsoft.com/en-us/windows/console/getstdhandle, Remarks). The desktop is a console
/// program (no `windows_subsystem`), so cmd and ssh would read and write its console instead of
/// the new window. Without that flag and without handle inheritance the new console fills the
/// standard handles itself.
/// cmd comes by its full path from the system directory: with only a command line,
/// `CreateProcessW` would search the current directory as well.
#[cfg(windows)]
fn spawn_in_new_console(line: &str) -> std::io::Result<std::os::windows::io::OwnedHandle> {
    use std::os::windows::ffi::OsStrExt;
    use std::os::windows::io::{FromRawHandle, OwnedHandle};
    use windows::core::{PCWSTR, PWSTR};
    use windows::Win32::System::Threading::{
        CreateProcessW, CREATE_NEW_CONSOLE, PROCESS_INFORMATION, STARTUPINFOW,
    };

    let cmd_exe = system_directory()?.join("cmd.exe");
    let application: Vec<u16> = cmd_exe.as_os_str().encode_wide().chain([0]).collect();
    let mut command_line = std::ffi::OsString::from("\"");
    command_line.push(&cmd_exe);
    command_line.push("\" ");
    command_line.push(line);
    // A buffer of its own: CreateProcessW may write into the command line.
    let mut command_line: Vec<u16> = command_line.encode_wide().chain([0]).collect();
    let startup = STARTUPINFOW {
        cb: std::mem::size_of::<STARTUPINFOW>() as u32,
        ..Default::default()
    };
    let mut info = PROCESS_INFORMATION::default();
    // SAFETY: both strings are NUL-terminated and outlive the call, the command line is writable,
    // `startup` and `info` are valid for the call. `false` inherits no handle, and `startup`
    // (zeroed but `cb`) passes no standard handle.
    unsafe {
        CreateProcessW(
            PCWSTR(application.as_ptr()),
            Some(PWSTR(command_line.as_mut_ptr())),
            None,
            None,
            false,
            CREATE_NEW_CONSOLE,
            None,
            PCWSTR::null(),
            &startup,
            &mut info,
        )
    }?;
    // SAFETY: CreateProcessW succeeded, so both handles are open, and nothing else owns them.
    let (process, thread) = unsafe {
        (
            OwnedHandle::from_raw_handle(info.hProcess.0),
            OwnedHandle::from_raw_handle(info.hThread.0),
        )
    };
    drop(thread);
    Ok(process)
}

/// The Windows system directory, as `GetSystemDirectoryW` reports it.
#[cfg(windows)]
fn system_directory() -> std::io::Result<PathBuf> {
    use std::os::windows::ffi::OsStringExt;
    use windows::Win32::System::SystemInformation::GetSystemDirectoryW;

    // SAFETY: without a buffer the call writes nothing and returns the size it needs, NUL included.
    let needed = unsafe { GetSystemDirectoryW(None) } as usize;
    if needed == 0 {
        return Err(std::io::Error::last_os_error());
    }
    let mut buffer = vec![0u16; needed];
    // SAFETY: the call gets the buffer with its length and writes at most that many units.
    let len = unsafe { GetSystemDirectoryW(Some(&mut buffer)) } as usize;
    if len == 0 {
        return Err(std::io::Error::last_os_error());
    }
    if len >= buffer.len() {
        return Err(std::io::Error::other(
            "the system directory changed its length between two calls",
        ));
    }
    buffer.truncate(len);
    Ok(PathBuf::from(std::ffi::OsString::from_wide(&buffer)))
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
    if let Some(problem) = quote_percent_or_control(value) {
        return Some(problem);
    }
    if value.contains(' ') && value.ends_with('\\') {
        return Some("an argument with a space and a trailing '\\'".to_string());
    }
    None
}

/// What neither wt nor cmd passes unchanged: `"`, `%` or a control character.
fn quote_percent_or_control(value: &str) -> Option<String> {
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
    None
}

/// The arguments of `cmd` for `cmd /S /V:OFF /K ""<command>" "<arg>"…"` in a new console, with
/// which `command` gets every argument unchanged.
///
/// After `/K`, cmd with `/S` takes off exactly the first and the last `"` and runs the rest
/// (learn.microsoft.com/en-us/windows-server/administration/windows-commands/cmd). Every value
/// stands in its own `"…"`, inside which cmd takes `&|<>()^` and `;` literally, and `/V:OFF`
/// turns off the `!` expansion. The C runtime of the program reads a `\` as itself unless it comes
/// before a `"`, so trailing `\` are doubled before the closing quote. cmd expands `%NAME%` inside
/// quotes too, a `"` would end the quoting and a control character (a line break) the command:
/// those are refused before anything starts. The line goes to cmd as it is (`spawn_in_new_console`),
/// not quoted once more by the rules of the C runtime, which cmd does not follow.
pub fn cmd_console_line(command: &str, args: &[String]) -> Result<String, AppError> {
    let mut quoted = Vec::with_capacity(args.len() + 1);
    for value in std::iter::once(command).chain(args.iter().map(String::as_str)) {
        if let Some(problem) = quote_percent_or_control(value) {
            return Err(AppError::Validation(format!(
                "The Windows console (cmd) cannot pass {problem} unchanged; nothing was opened"
            )));
        }
        let trailing = value.len() - value.trim_end_matches('\\').len();
        quoted.push(format!("\"{value}{}\"", "\\".repeat(trailing)));
    }
    Ok(format!("/S /V:OFF /K \"{}\"", quoted.join(" ")))
}

/// POSIX-shell single-quote escaping for a value interpolated into a `bash -c`
/// command line: wrap in single quotes and escape any embedded single quote.
/// Security-relevant — the single shared copy so a hardening can't miss a caller.
pub fn shell_escape(s: &str) -> String {
    format!("'{}'", s.replace('\'', "'\\''"))
}

#[cfg(test)]
mod tests {
    use super::*;

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

    fn cmd_line(command: &str, args: &[&str]) -> String {
        cmd_console_line(command, &strings(args)).expect("cmd line")
    }

    #[test]
    fn cmd_console_line_quotes_each_value_inside_one_outer_pair() {
        assert_eq!(
            cmd_line("ssh", &["-p", "2222", "--", "u@h"]),
            r#"/S /V:OFF /K ""ssh" "-p" "2222" "--" "u@h"""#
        );
    }

    #[test]
    fn cmd_console_line_keeps_metacharacters_unchanged_inside_quotes() {
        for value in [
            "a&b",
            "x|y",
            "(p)",
            "c^d",
            "semi;colon",
            "with space",
            "a<b>c",
            "bang!",
        ] {
            assert_eq!(
                cmd_line("ssh", &[value]),
                format!(r#"/S /V:OFF /K ""ssh" "{value}"""#)
            );
        }
    }

    #[test]
    fn cmd_console_line_doubles_only_trailing_backslashes() {
        assert_eq!(
            cmd_line("ssh", &["C:\\dir with space\\", "C:\\a\\b", "x\\\\"]),
            r#"/S /V:OFF /K ""ssh" "C:\dir with space\\" "C:\a\b" "x\\\\"""#
        );
    }

    #[test]
    fn cmd_console_line_rejects_values_cmd_cannot_pass_unchanged() {
        for (bad, named) in [("a\"b", "'\"'"), ("50%", "'%'"), ("a\nb", "U+000A")] {
            match cmd_console_line("ssh", &strings(&["-i", bad, "--", "u@h"])) {
                Err(AppError::Validation(msg)) => {
                    assert!(msg.contains(named), "{bad:?}: {msg}")
                }
                other => panic!("{bad:?} must be rejected, got {other:?}"),
            }
        }
        for bad_command in ["ss\"h", "%SystemRoot%\\ssh"] {
            assert!(
                matches!(
                    cmd_console_line(bad_command, &[]),
                    Err(AppError::Validation(_))
                ),
                "{bad_command:?} must be rejected"
            );
        }
    }

    /// The arguments for a run of this test binary that runs only `helper`, with `values` after
    /// `--`: libtest reads those as more filters, and `--exact` matches none of them to a test.
    #[cfg(windows)]
    fn run_only(helper: &str, values: &[String]) -> Vec<String> {
        let mut args = strings(&["--exact", helper, "--nocapture", "--"]);
        args.extend(values.iter().cloned());
        args
    }

    /// The line from `cmd_console_line` for this test binary, with `/C` instead of `/K`: cmd ends
    /// with the program.
    #[cfg(windows)]
    fn run_once_line(args: &[String]) -> String {
        let exe = std::env::current_exe().expect("test binary");
        let line = cmd_console_line(exe.to_str().expect("UTF-8 path"), args).expect("cmd line");
        let rest = line
            .strip_prefix("/S /V:OFF /K ")
            .expect("the line starts with the switches");
        format!("/S /V:OFF /C {rest}")
    }

    #[cfg(windows)]
    const ARGV_ECHO_ENV: &str = "AH_TEST_TERMINAL_ARGV_ECHO";
    #[cfg(windows)]
    const ARGV_ECHO_MARK: &str = "argv-echo: ";

    /// Not a test of its own: with `ARGV_ECHO_ENV` set, it prints the arguments of this run after
    /// the first `--` as one JSON line.
    #[cfg(windows)]
    #[test]
    fn argv_echo_helper() {
        if std::env::var_os(ARGV_ECHO_ENV).is_none() {
            return;
        }
        let args: Vec<String> = std::env::args().skip_while(|a| a != "--").skip(1).collect();
        println!(
            "{ARGV_ECHO_MARK}{}",
            serde_json::to_string(&args).expect("arguments as JSON")
        );
    }

    #[cfg(windows)]
    #[test]
    fn cmd_console_line_reaches_the_program_unchanged() {
        use std::os::windows::process::CommandExt;

        let values = strings(&[
            "-p",
            "2222",
            "--",
            "u@h",
            "a&b",
            "x|y",
            "(p)",
            "c^d",
            "semi;colon",
            "with space",
            "a<b>c",
            "bang!",
            "C:\\dir with space\\",
        ]);
        let line = run_once_line(&run_only("terminal::tests::argv_echo_helper", &values));
        let output = Command::new("cmd")
            .raw_arg(&line)
            .env(ARGV_ECHO_ENV, "1")
            .output()
            .expect("cmd runs");
        let stdout = String::from_utf8_lossy(&output.stdout);
        assert!(
            output.status.success(),
            "{}: {stdout}{}",
            output.status,
            String::from_utf8_lossy(&output.stderr)
        );
        let echoed = stdout
            .split_once(ARGV_ECHO_MARK)
            .and_then(|(_, rest)| rest.lines().next())
            .unwrap_or_else(|| panic!("no echo of the arguments in: {stdout}"));
        let received: Vec<String> = serde_json::from_str(echoed).expect("echo as JSON");
        assert_eq!(received, values);
    }

    #[cfg(windows)]
    const HANDLE_PROBE_ARG: &str = "ah-terminal-handle-probe=";

    /// Not a test of its own: started with `HANDLE_PROBE_ARG<file>` after `--`, it writes to that
    /// file whether its stdout is a console.
    #[cfg(windows)]
    #[test]
    fn std_handle_probe_helper() {
        use std::io::IsTerminal;

        let Some(report) =
            std::env::args().find_map(|arg| arg.strip_prefix(HANDLE_PROBE_ARG).map(PathBuf::from))
        else {
            return;
        };
        let stdout = if std::io::stdout().is_terminal() {
            "console"
        } else {
            "no console"
        };
        std::fs::write(report, stdout).expect("probe report");
    }

    #[cfg(windows)]
    #[test]
    fn new_console_does_not_get_the_std_handles_of_this_process() {
        use std::io::IsTerminal;
        use std::os::windows::io::AsRawHandle;
        use std::os::windows::process::CommandExt;
        use windows::Win32::Foundation::{HANDLE, WAIT_OBJECT_0};
        use windows::Win32::System::Threading::{WaitForSingleObject, CREATE_NEW_CONSOLE};

        let dir = std::env::temp_dir().join(format!("ah-terminal-console-{}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("temp dir");
        let report = dir.join("stdout.txt");
        let probe = format!("{HANDLE_PROBE_ARG}{}", report.display());
        let line = run_once_line(&run_only(
            "terminal::tests::std_handle_probe_helper",
            &[probe],
        ));

        let process = spawn_in_new_console(&line).expect("console starts");
        // SAFETY: `process` stays open for the whole call.
        let waited = unsafe { WaitForSingleObject(HANDLE(process.as_raw_handle()), 60_000) };
        assert_eq!(waited, WAIT_OBJECT_0, "the console did not end within 60 s");
        assert_eq!(
            std::fs::read_to_string(&report).expect("probe report"),
            "console"
        );

        // Counter-check that the probe tells the two apart: std::process::Command with the same
        // flag hands this process's standard handles on, so the probe sees a pipe. That differs
        // from the console only where this process's own stdout is not a terminal (cargo test
        // with its output captured, as in CI); on a terminal the check is skipped.
        if !std::io::stdout().is_terminal() {
            std::fs::remove_file(&report).expect("first probe report");
            let status = Command::new(
                system_directory()
                    .expect("system directory")
                    .join("cmd.exe"),
            )
            .raw_arg(&line)
            .creation_flags(CREATE_NEW_CONSOLE.0)
            .status()
            .expect("cmd runs");
            assert!(status.success(), "{status}");
            assert_eq!(
                std::fs::read_to_string(&report).expect("probe report"),
                "no console"
            );
        }
        std::fs::remove_dir_all(&dir).expect("temp dir");
    }
}
