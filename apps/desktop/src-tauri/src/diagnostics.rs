// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! Redacted desktop diagnostics report for bug reports: version, OS and the tail
//! of the rotating log file, with secret-looking tokens masked. Written next to
//! the log file; the path is returned to the UI for the user to attach to an issue.

use chrono::Utc;
use regex::Regex;
use std::sync::LazyLock;
use tauri::{AppHandle, Manager};

use crate::error::AppError;

const LOG_TAIL_LINES: usize = 400;

/// Build a redacted report, write it into the app log dir and return its path.
pub fn generate(app: &AppHandle) -> Result<String, AppError> {
    let log_dir = app
        .path()
        .app_log_dir()
        .map_err(|e| AppError::Connection(format!("Log-Verzeichnis: {e}")))?;
    let log_path = log_dir.join("adminhelper.log");

    let mut report = String::new();
    report.push_str("AdminHelper desktop diagnostics\n");
    report.push_str("======================================================================\n\n");
    report.push_str(&format!("version : {}\n", app.package_info().version));
    report.push_str(&format!(
        "os/arch : {}/{}\n",
        std::env::consts::OS,
        std::env::consts::ARCH
    ));
    report.push_str(&format!("log file: {}\n\n", log_path.display()));

    report.push_str(&format!("## Log (last {LOG_TAIL_LINES} lines)\n"));
    match std::fs::read_to_string(&log_path) {
        Ok(content) => report.push_str(&tail(&content, LOG_TAIL_LINES)),
        Err(e) => report.push_str(&format!("(log not available: {e})\n")),
    }

    let redacted = redact(&report);
    let out = log_dir.join(format!(
        "adminhelper-diagnostics-{}.txt",
        Utc::now().format("%Y%m%dT%H%M%SZ")
    ));
    std::fs::write(&out, redacted)?;
    Ok(out.display().to_string())
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
