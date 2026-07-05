// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use crate::error::AppError;
use crate::models::{Connection, ConnectionKind};
use url::{Host, Url};

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

/// True only for hosts whose traffic never leaves the machine: the loopback
/// IPs (127.0.0.0/8, ::1) and the literal `localhost`. Subdomains of
/// `.localhost` are deliberately *not* accepted — not every resolver maps them
/// to loopback (RFC 6761 is advisory), so trusting them could leak to a real host.
fn is_loopback_host(host: Option<Host<&str>>) -> bool {
    match host {
        Some(Host::Ipv4(ip)) => ip.is_loopback(),
        Some(Host::Ipv6(ip)) => ip.is_loopback(),
        Some(Host::Domain(d)) => d.eq_ignore_ascii_case("localhost"),
        None => false,
    }
}

/// Enforces TLS on an AdminHelper server URL before any credential (password,
/// JWT, refresh token) is sent to it. `https://` is always allowed; `http://`
/// is allowed *only* for loopback hosts, so local development keeps working
/// while no secret ever crosses a network in cleartext.
///
/// The public read-only sync URL has its own stricter `validate_https_url`
/// (no loopback exception) below; this guards the authenticated JWT path
/// funnelled through `http_client::build_client`.
pub fn validate_server_url_secure(raw: &str) -> Result<(), AppError> {
    let url = Url::parse(raw)?;
    match url.scheme() {
        "https" => Ok(()),
        "http" if is_loopback_host(url.host()) => Ok(()),
        _ => Err(AppError::Validation(
            "Server-URL muss https:// verwenden (http:// nur fuer localhost)".to_string(),
        )),
    }
}

/// Stricter than `validate_server_url_secure`: NO loopback exception. The public
/// read-only sync URL is always a network target, so cleartext `http://` is never
/// acceptable there — not even for localhost.
pub fn validate_https_url(raw: &str) -> Result<(), AppError> {
    let url = Url::parse(raw)?;
    if url.scheme() != "https" {
        return Err(AppError::Validation(
            "Nur https:// URLs sind erlaubt".to_string(),
        ));
    }
    Ok(())
}

/// True if two URLs point at the same server origin (scheme + host + port),
/// ignoring path, trailing slash and host case. Used to pin `api_proxy`'s token
/// destination to the logged-in server: a request URL that differs from the
/// session's server origin must not receive the JWT. Falls back to a
/// trailing-slash-insensitive exact match if either URL fails to parse.
pub fn same_server_destination(requested: &str, stored: &str) -> bool {
    fn origin(raw: &str) -> Option<(String, String, u16)> {
        let url = Url::parse(raw).ok()?;
        let host = url.host_str()?.to_ascii_lowercase();
        let port = url.port_or_known_default()?;
        Some((url.scheme().to_string(), host, port))
    }
    match (origin(requested), origin(stored)) {
        (Some(a), Some(b)) => a == b,
        _ => requested.trim_end_matches('/') == stored.trim_end_matches('/'),
    }
}

/// Validates a request `path` coming from the frontend and confirms that the URL
/// composed as `server_url + path` still targets `stored` (the logged-in server).
///
/// `api_proxy`/`authenticated_get` build the request URL by naive string
/// concatenation (`format!("{server_url}{path}")`). A frontend-supplied `path`
/// could break out of that: a leading `@` shoves the host into the userinfo
/// (RFC 3986: `https://server@evil.com/`), a `\` or `://` injects a new
/// authority, so the Bearer token would travel to a foreign host even though
/// `server_url` alone passed `same_server_destination`. Guard both: reject path
/// shapes that can rewrite the authority, then re-parse the FINAL URL and pin its
/// origin to the logged-in server.
pub fn validate_proxy_path(server_url: &str, path: &str, stored: &str) -> Result<(), AppError> {
    if !path.starts_with('/') {
        return Err(AppError::Validation(
            "Ungueltiger Anfrage-Pfad (muss mit / beginnen)".to_string(),
        ));
    }
    if path.contains('@') || path.contains('\\') || path.contains("://") {
        return Err(AppError::Validation("Ungueltiger Anfrage-Pfad".to_string()));
    }
    let composed = format!("{}{}", server_url.trim_end_matches('/'), path);
    let parsed = Url::parse(&composed)
        .map_err(|_| AppError::Validation("Ungueltige Ziel-URL".to_string()))?;
    if !same_server_destination(parsed.as_str(), stored) {
        return Err(AppError::Validation(
            "Anfrage-Ziel weicht von der angemeldeten Server-URL ab".to_string(),
        ));
    }
    Ok(())
}

/// Enforce the token-destination pin fail-closed: a token may only travel to the
/// server stored at login. If there is no stored session — e.g. the user logged out
/// (which clears the stored URL) but the frontend still holds a JWT in memory — refuse
/// the request rather than send the token to an unpinned, caller-supplied URL. The
/// previous best-effort guard silently skipped the pin when the URL was absent (3.56).
pub fn require_pinned_destination(
    server_url: &str,
    path: &str,
    stored: Option<&str>,
) -> Result<(), AppError> {
    match stored {
        Some(stored) => validate_proxy_path(server_url, path, stored),
        None => Err(AppError::Validation(
            "Keine aktive Sitzung — Anfrage abgelehnt".to_string(),
        )),
    }
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

/// Trim a value and error if it is empty — the shared "field X is required" check
/// used across connection/SSH/RDP input validation.
pub fn required(value: &Option<String>, label: &str) -> Result<String, AppError> {
    let trimmed = value.as_deref().unwrap_or("").trim().to_string();
    if trimmed.is_empty() {
        return Err(AppError::Validation(format!("{label} fehlt")));
    }
    Ok(trimmed)
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
            server_id: None,
        }
    }

    #[test]
    fn validate_host_accepts_plain_hostname() {
        assert!(validate_host("host.example.com").is_ok());
        assert!(validate_host("192.168.0.1").is_ok());
    }

    #[test]
    fn validate_https_url_requires_https_without_loopback_exception() {
        assert!(validate_https_url("https://sync.example.com/connections").is_ok());
        // Stricter than validate_server_url_secure: even loopback http is rejected.
        assert!(validate_https_url("http://localhost/connections").is_err());
        assert!(validate_https_url("http://sync.example.com").is_err());
        assert!(validate_https_url("ftp://sync.example.com").is_err());
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

    #[test]
    fn validate_server_url_secure_accepts_https_and_loopback_http() {
        for url in [
            "https://example.com",
            "https://example.com:8443/api",
            "http://localhost",
            "http://localhost:8000/api",
            "http://LOCALHOST:8000",
            "http://127.0.0.1",
            "http://127.0.0.5:9000", // whole 127.0.0.0/8 is loopback
            "http://[::1]:8000",
        ] {
            assert!(
                validate_server_url_secure(url).is_ok(),
                "{url} must be accepted"
            );
        }
    }

    #[test]
    fn validate_server_url_secure_rejects_cleartext_network_and_other_schemes() {
        for url in [
            "http://example.com",        // cleartext over the network
            "http://192.168.1.10:8000",  // private LAN IP, still a network
            "http://10.0.0.1",           // private LAN IP
            "http://attacker.localhost", // subdomain is not guaranteed loopback
            "http://localhost.evil.com", // looks loopback, is not
            "ftp://example.com",         // wrong scheme
        ] {
            assert!(
                validate_server_url_secure(url).is_err(),
                "{url} must be rejected"
            );
        }
    }

    #[test]
    fn same_server_destination_matches_same_origin_ignoring_path_and_slash() {
        let stored = "https://adminhelper.example:8443";
        for requested in [
            "https://adminhelper.example:8443",
            "https://adminhelper.example:8443/",
            "https://adminhelper.example:8443/api/connections",
            "https://ADMINHELPER.example:8443/api", // host case-insensitive
        ] {
            assert!(
                same_server_destination(requested, stored),
                "{requested} must match {stored}"
            );
        }
        // Implicit vs explicit default port are the same origin.
        assert!(same_server_destination(
            "https://adminhelper.example/api",
            "https://adminhelper.example:443"
        ));
    }

    #[test]
    fn same_server_destination_rejects_foreign_origin() {
        let stored = "https://adminhelper.example:8443";
        for requested in [
            "https://attacker.example:8443/api",         // different host
            "https://adminhelper.example:9443/api",      // different port
            "http://adminhelper.example:8443/api",       // different scheme
            "https://adminhelper.example.evil.com:8443", // suffix trick
        ] {
            assert!(
                !same_server_destination(requested, stored),
                "{requested} must NOT match {stored}"
            );
        }
    }

    #[test]
    fn validate_proxy_path_accepts_plain_path() {
        let stored = "https://adminhelper.example:8443";
        assert!(validate_proxy_path(stored, "/api/auth/me", stored).is_ok());
        // trailing slash on server_url must not matter
        assert!(validate_proxy_path("https://adminhelper.example:8443/", "/api/x", stored).is_ok());
    }

    #[test]
    fn validate_proxy_path_rejects_authority_rewrite() {
        let stored = "https://adminhelper.example:8443";
        // A leading '@' pushes the real host into userinfo (RFC 3986), so the
        // composed URL would target evil.com; '\' and '://' inject an authority.
        for path in [
            "@evil.com/api/auth/me",
            "/\\evil.com/api",
            "/x://evil.com",
            "api/no-leading-slash",
        ] {
            assert!(
                validate_proxy_path(stored, path, stored).is_err(),
                "path {path:?} must be rejected"
            );
        }
    }

    #[test]
    fn same_server_destination_handles_ipv6_and_unparseable_fallback() {
        // IPv6 literal hosts compare by origin like any other host.
        assert!(same_server_destination(
            "https://[::1]:8443/api",
            "https://[::1]:8443"
        ));
        assert!(!same_server_destination(
            "https://[::2]:8443",
            "https://[::1]:8443"
        ));
        // If a side doesn't parse as a URL, fall back to a trailing-slash-
        // insensitive exact match rather than silently treating them as equal.
        assert!(same_server_destination("not a url/", "not a url"));
        assert!(!same_server_destination("not a url", "other"));
    }

    #[test]
    fn validate_proxy_path_rejects_a_foreign_server_url() {
        // Even with a clean path, a frontend-supplied server_url that differs
        // from the logged-in origin must not receive the token.
        let stored = "https://adminhelper.example:8443";
        assert!(
            validate_proxy_path("https://attacker.example:8443", "/api/auth/me", stored).is_err()
        );
        // scheme downgrade is also a different origin
        assert!(validate_proxy_path("http://adminhelper.example:8443", "/api/x", stored).is_err());
    }

    #[test]
    fn require_pinned_destination_fails_closed_without_session() {
        // 3.56: no stored session -> refuse rather than send the token unpinned.
        assert!(
            require_pinned_destination("https://adminhelper.example:8443", "/api/x", None).is_err()
        );
    }

    #[test]
    fn require_pinned_destination_pins_when_session_present() {
        let stored = "https://adminhelper.example:8443";
        assert!(require_pinned_destination(stored, "/api/auth/me", Some(stored)).is_ok());
        // a foreign server_url is still rejected when a session exists
        assert!(require_pinned_destination(
            "https://attacker.example:8443",
            "/api/x",
            Some(stored)
        )
        .is_err());
    }
}
