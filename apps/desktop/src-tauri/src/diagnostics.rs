// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! Redacted desktop diagnostics report for bug reports: version, OS, workspace id and
//! the tail of this process's rotating log file, with secret-looking tokens masked.
//! Written next to the log file; the path is returned to the UI for the user to
//! attach to an issue.

use chrono::Utc;
use regex::Regex;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;
use tauri::{AppHandle, Manager};

use crate::error::AppError;
use crate::workspace::{self, Mode, Workspace};

const LOG_TAIL_LINES: usize = 400;

/// Build a redacted report, write it into the app log dir and return its path.
pub fn generate(app: &AppHandle) -> Result<String, AppError> {
    let log_dir = app
        .path()
        .app_log_dir()
        .map_err(|e| AppError::Connection(format!("Log-Verzeichnis: {e}")))?;
    // No workspace is no error here: the launcher has none, and a report must come out anyway.
    let workspace = workspace::current().ok();
    let redacted = report(
        &log_dir,
        &app.package_info().version.to_string(),
        workspace.as_ref(),
    );
    let out = log_dir.join(format!(
        "adminhelper-diagnostics-{}.txt",
        Utc::now().format("%Y%m%dT%H%M%SZ")
    ));
    std::fs::write(&out, redacted)?;
    Ok(out.display().to_string())
}

/// The redacted report of the process serving `workspace` (none: the launcher), with the tail of
/// that process's own log in `log_dir`.
fn report(log_dir: &Path, version: &str, workspace: Option<&Workspace>) -> String {
    let log_path = log_path(log_dir, workspace);

    let mut report = String::new();
    report.push_str("AdminHelper desktop diagnostics\n");
    report.push_str("======================================================================\n\n");
    report.push_str(&format!("version : {version}\n"));
    report.push_str(&format!(
        "os/arch : {}/{}\n",
        std::env::consts::OS,
        std::env::consts::ARCH
    ));
    // The id, never the name: the report goes into public issues, and a name may be a customer's.
    report.push_str(&format!(
        "workspace: {}\n",
        workspace.map_or_else(|| "none (launcher)".to_string(), |ws| ws.id.to_string())
    ));
    report.push_str(&format!("log file: {}\n\n", log_path.display()));

    report.push_str(&format!("## Log (last {LOG_TAIL_LINES} lines)\n"));
    match std::fs::read_to_string(&log_path) {
        Ok(content) => report.push_str(&tail(&content, LOG_TAIL_LINES)),
        Err(e) => report.push_str(&format!("(log not available: {e})\n")),
    }

    redact(&report)
}

/// The log file of the process serving `workspace`: every process writes a log of its own, under
/// the name its start gives the log plugin ([`Mode::log_name`]); the launcher's without one.
fn log_path(log_dir: &Path, workspace: Option<&Workspace>) -> PathBuf {
    let name = workspace.map_or_else(|| Mode::Launcher.log_name(), Workspace::log_name);
    log_dir.join(format!("{name}.log"))
}

fn tail(content: &str, n: usize) -> String {
    let lines: Vec<&str> = content.lines().collect();
    let start = lines.len().saturating_sub(n);
    let mut s = lines[start..].join("\n");
    s.push('\n');
    s
}

/// Max length of a raw server error body surfaced in a user-facing error/log.
/// A misbehaving (or hostile) server must not be able to flood the UI or the log
/// with an arbitrarily long body.
const MAX_BODY_CHARS: usize = 500;

/// Sanitize a raw server error body before it lands in a user-facing error or the
/// log: truncate to `MAX_BODY_CHARS` and mask secret-looking tokens with the same
/// `redact()` the diagnostics report uses. Token-bearing endpoints can echo the
/// Bearer/JWT back in their error body, so an unfiltered body is a leak vector.
pub fn redact_body(s: &str) -> String {
    let truncated: String = if s.chars().count() > MAX_BODY_CHARS {
        let head: String = s.chars().take(MAX_BODY_CHARS).collect();
        format!("{head}… (gekürzt)")
    } else {
        s.to_string()
    };
    redact(&truncated)
}

/// Mask generic secret token shapes (JWT, Bearer, ah_ API keys) plus opaque
/// token/secret/refresh key-values. The last one catches the frp auth token and
/// refresh tokens that match none of the three fixed shapes but appear in the frpc
/// stdout/stderr tail appended to a diagnostics report (3.57).
// Compile the redaction patterns once (LazyLock) instead of on every redact_body call — that runs
// on every HTTP error path (api_proxy, login, enrollment, renew), and Regex::new (parser + NFA
// build) is the regex crate's standard don't-do-this-in-a-loop cost (5.9).
static JWT_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]*").unwrap()
});
static BEARER_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)bearer [A-Za-z0-9._-]{8,}").unwrap());
static APIKEY_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"ah_[A-Za-z0-9_-]{8,}").unwrap());
// key = <high-entropy value>: token/secret/refresh (any quote/=/:/space separator) followed by a
// >=12-char opaque value.
static TOKENKV_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"(?i)(token|secret|refresh)["'=: ]+[A-Za-z0-9._-]{12,}"#).unwrap()
});

fn redact(s: &str) -> String {
    let s = JWT_RE.replace_all(s, "<redacted-jwt>");
    let s = BEARER_RE.replace_all(&s, "Bearer <redacted>");
    let s = APIKEY_RE.replace_all(&s, "ah_<redacted>");
    let s = TOKENKV_RE.replace_all(&s, "$1=<redacted>");
    s.into_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redacts_tokens_but_keeps_plain_text() {
        let input =
            "hi Authorization: Bearer abcdef123456 key ah_aBcDeFgH1234 jwt eyJhbGciOiJI.eyJzdWIiOiJ.sig";
        let out = redact(input);
        assert!(!out.contains("abcdef123456"), "bearer token leaked: {out}");
        assert!(!out.contains("ah_aBcDeFgH1234"), "api key leaked: {out}");
        assert!(out.contains("hi"));
        assert!(out.contains("Bearer <redacted>"));
        assert!(out.contains("ah_<redacted>"));
        assert!(out.contains("<redacted-jwt>"));
    }

    #[test]
    fn redacts_opaque_token_key_values() {
        // 3.57: an frp auth token / refresh token matches none of the fixed shapes,
        // but appears as token/secret/refresh=<value> in the frpc log tail.
        let out = redact("auth.token = \"9f3ab12cd45ef678\"\nrefresh: abcdef1234567890");
        assert!(!out.contains("9f3ab12cd45ef678"), "frp token leaked: {out}");
        assert!(
            !out.contains("abcdef1234567890"),
            "refresh token leaked: {out}"
        );
        assert!(out.contains("token=<redacted>"));
        assert!(out.contains("refresh=<redacted>"));
    }

    /// A directory of its own for one test case under the system temp dir, gone with the guard.
    struct Scratch(PathBuf);

    impl Scratch {
        fn new(case: &str) -> Self {
            let dir =
                std::env::temp_dir().join(format!("ah-diagnostics-{case}-{}", std::process::id()));
            let _ = std::fs::remove_dir_all(&dir);
            std::fs::create_dir_all(&dir).unwrap();
            Self(dir)
        }
    }

    impl Drop for Scratch {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn kunde_a() -> Workspace {
        Workspace {
            id: crate::workspace::WorkspaceId::parse("kunde-a").unwrap(),
            name: "Kunde A".to_string(),
            legacy_keys: false,
        }
    }

    #[test]
    fn per_process_log_path_follows_the_log_name_of_the_process() {
        let dir = Path::new("logs");
        let ws = kunde_a();
        // The names the start gives the log plugin (`Mode::log_name`), plus its `.log`.
        let workspace_log = format!("{}.log", Mode::Workspace(ws.id.clone()).log_name());
        let launcher_log = format!("{}.log", Mode::Launcher.log_name());
        assert_eq!(log_path(dir, Some(&ws)), dir.join(&workspace_log));
        assert_eq!(workspace_log, "adminhelper-kunde-a.log");
        assert_eq!(log_path(dir, None), dir.join(&launcher_log));
        assert_eq!(launcher_log, "adminhelper.log", "the log before workspaces");
    }

    #[test]
    fn per_process_report_reads_its_own_log_and_names_the_workspace_id() {
        let scratch = Scratch::new("own-log");
        std::fs::write(scratch.0.join("adminhelper.log"), "launcher line\n").unwrap();
        std::fs::write(
            scratch.0.join("adminhelper-kunde-a.log"),
            "workspace line\n",
        )
        .unwrap();

        let ws = kunde_a();
        let ours = report(&scratch.0, "1.2.3", Some(&ws));
        assert!(ours.contains("workspace line"), "{ours}");
        assert!(!ours.contains("launcher line"), "{ours}");
        assert!(ours.contains("workspace: kunde-a\n"), "{ours}");
        assert!(!ours.contains("Kunde A"), "the name stays out: {ours}");

        let launcher = report(&scratch.0, "1.2.3", None);
        assert!(launcher.contains("launcher line"), "{launcher}");
        assert!(!launcher.contains("workspace line"), "{launcher}");
        assert!(
            launcher.contains("workspace: none (launcher)\n"),
            "{launcher}"
        );
    }

    #[test]
    fn tail_keeps_last_lines() {
        assert_eq!(tail("a\nb\nc\nd\n", 2), "c\nd\n");
        assert_eq!(tail("x\n", 5), "x\n");
    }

    #[test]
    fn redact_body_truncates_over_the_char_cap() {
        // 6.106: a body over MAX_BODY_CHARS is cut to the cap plus a marker; under it, unchanged.
        // This is the anti-flooding defence against a malicious/broken server flooding the UI/log.
        let long = "a".repeat(MAX_BODY_CHARS + 100);
        let out = redact_body(&long);
        assert!(
            out.contains("… (gekürzt)"),
            "over-cap body must be truncated: {out}"
        );
        assert!(out.starts_with(&"a".repeat(MAX_BODY_CHARS)));
        assert_eq!(redact_body("short body"), "short body");
    }

    #[test]
    fn redact_body_truncation_is_char_safe_on_multibyte() {
        // 6.106: the cut counts chars(), not bytes — a multibyte char at the boundary must not panic.
        let multibyte = "🔒".repeat(MAX_BODY_CHARS + 10);
        let out = redact_body(&multibyte);
        assert!(out.contains("… (gekürzt)"));
    }
}
