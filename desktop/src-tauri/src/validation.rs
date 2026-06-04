// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use crate::error::AppError;
use crate::models::{Connection, ConnectionKind};
use url::Url;

pub fn validate_host(host: &str) -> Result<(), AppError> {
    let trimmed = host.trim();
    if trimmed.is_empty() {
        return Err(AppError::Validation("Host fehlt".to_string()));
    }
    if trimmed.starts_with('-') {
        return Err(AppError::Validation("Ungueltiger Hostname".to_string()));
    }
    if trimmed
        .contains(|c: char| c.is_control() || c.is_whitespace() || ";|&$`'\"\\{}()!#".contains(c))
    {
        return Err(AppError::Validation("Ungueltiger Hostname".to_string()));
    }
    Ok(())
}

pub fn validate_no_control_chars(value: &str, label: &str) -> Result<(), AppError> {
    if value.contains(|c: char| c.is_control()) {
        return Err(AppError::Validation(format!(
            "{label} enthaelt ungueltige Zeichen"
        )));
    }
    Ok(())
}

pub fn validate_web_url(raw: &str) -> Result<String, AppError> {
    let trimmed = raw.trim();
    let with_scheme = if !trimmed.contains("://") {
        format!("https://{trimmed}")
    } else {
        trimmed.to_string()
    };
    let parsed = Url::parse(&with_scheme)?;
    match parsed.scheme() {
        "https" | "http" => Ok(parsed.to_string()),
        other => Err(AppError::Validation(format!(
            "Unerlaubtes URL-Schema: {other}"
        ))),
    }
}

pub fn validate_connection_input(connection: &Connection) -> Result<(), AppError> {
    if let Some(ref host) = connection.host {
        let trimmed = host.trim();
        if !trimmed.is_empty() {
            validate_host(trimmed)?;
        }
    }
    if let Some(ref username) = connection.username {
        validate_no_control_chars(username, "Benutzer")?;
    }
    if let Some(ref domain) = connection.domain {
        validate_no_control_chars(domain, "Domaene")?;
    }
    if let Some(ref key_path) = connection.key_path {
        let trimmed = key_path.trim();
        if !trimmed.is_empty() && trimmed.contains("..") {
            return Err(AppError::Validation("Ungueltiger SSH Key Pfad".to_string()));
        }
    }
    if let Some(ref url) = connection.url {
        if connection.kind == ConnectionKind::Web && !url.trim().is_empty() {
            validate_web_url(url)?;
        }
    }
    Ok(())
}

/// Sanitizes a connection name for safe use as an RDP window title
/// (xfreerdp `/title:`). Defense-in-depth: passing via argv already prevents
/// argument splitting, but sanitization guards against control characters,
/// X11 escapes, and future code paths that might shell-format the value.
pub fn sanitize_window_title(name: &str) -> String {
    let filtered: String = name
        .chars()
        .filter(|c| c.is_alphanumeric() || matches!(c, ' ' | '-' | '_' | '.' | ':' | '(' | ')'))
        .take(64)
        .collect();
    filtered.trim().to_string()
}

pub fn sanitize_synced_connections(connections: Vec<Connection>) -> Vec<Connection> {
    connections
        .into_iter()
        .filter(|c| validate_connection_input(c).is_ok())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::ConnectionKind;

    fn ssh_connection_with_key_path(key_path: &str) -> Connection {
        Connection {
            id: "id".to_string(),
            name: "name".to_string(),
            kind: ConnectionKind::Ssh,
            host: Some("example.com".to_string()),
            port: None,
            username: None,
            domain: None,
            key_path: Some(key_path.to_string()),
            url: None,
            notes: None,
            tags: Vec::new(),
            trust_cert: false,
            last_used: None,
        }
    }

    #[test]
    fn validate_host_accepts_plain_hostname() {
        assert!(validate_host("host.example.com").is_ok());
        assert!(validate_host("192.168.0.1").is_ok());
    }

    #[test]
    fn validate_host_rejects_shell_metacharacters() {
        for c in [';', '|', '&', '$', '`'] {
            let host = format!("host{c}evil");
            assert!(
                validate_host(&host).is_err(),
                "Host mit '{c}' muss abgelehnt werden"
            );
        }
    }

    #[test]
    fn validate_host_rejects_whitespace() {
        assert!(validate_host("host name").is_err());
    }

    #[test]
    fn validate_host_rejects_control_chars() {
        assert!(validate_host("host\x00name").is_err());
        assert!(validate_host("host\x1fname").is_err());
        assert!(validate_host("host\nname").is_err());
    }

    #[test]
    fn validate_host_rejects_empty_and_leading_dash() {
        assert!(validate_host("").is_err());
        assert!(validate_host("   ").is_err());
        assert!(validate_host("-oProxyCommand=evil").is_err());
    }

    #[test]
    fn validate_web_url_allows_http_and_https() {
        assert!(validate_web_url("http://example.com").is_ok());
        assert!(validate_web_url("https://example.com").is_ok());
        // Without a scheme, https:// is prepended.
        assert!(validate_web_url("example.com").is_ok());
    }

    #[test]
    fn validate_web_url_rejects_ftp_and_other_schemes() {
        assert!(validate_web_url("ftp://example.com").is_err());
        assert!(validate_web_url("file:///etc/passwd").is_err());
        assert!(validate_web_url("javascript:alert(1)").is_err());
    }

    #[test]
    fn validate_connection_input_rejects_path_traversal_in_key_path() {
        let connection = ssh_connection_with_key_path("../../etc/passwd");
        assert!(validate_connection_input(&connection).is_err());
    }

    #[test]
    fn validate_connection_input_accepts_plain_key_path() {
        let connection = ssh_connection_with_key_path("/home/user/.ssh/id_ed25519");
        assert!(validate_connection_input(&connection).is_ok());
    }

    #[test]
    fn validate_no_control_chars_rejects_null_and_unit_separator() {
        assert!(validate_no_control_chars("user\x00name", "Benutzer").is_err());
        assert!(validate_no_control_chars("user\x1fname", "Benutzer").is_err());
    }

    #[test]
    fn validate_no_control_chars_accepts_plain_text() {
        assert!(validate_no_control_chars("administrator", "Benutzer").is_ok());
    }
}
