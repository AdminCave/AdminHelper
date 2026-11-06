// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::sync::LazyLock;

use regex::Regex;

use crate::error::AppError;
use crate::models::{
    Connection, ConnectionKind, RdpConnectionOptions, Snippet, SshForwardKind, SshOptions,
};
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

pub const MAX_SNIPPETS: usize = 200;
pub const MAX_SNIPPET_NAME: usize = 64;
pub const MAX_SNIPPET_COMMAND: usize = 4096;

/// The snippets a workspace saves (R-1071): a name to show on one line, a command the panel types
/// into a session, where a line break and a tab are text and every other control character
/// would be a key the user never sees.
pub fn validate_snippets(snippets: &[Snippet]) -> Result<(), AppError> {
    if snippets.len() > MAX_SNIPPETS {
        return Err(AppError::Validation(format!(
            "At most {MAX_SNIPPETS} snippets"
        )));
    }
    for snippet in snippets {
        let name = snippet.name.chars().count();
        if snippet.name.trim().is_empty() || name > MAX_SNIPPET_NAME {
            return Err(AppError::Validation(format!(
                "A snippet name has 1 to {MAX_SNIPPET_NAME} characters"
            )));
        }
        if snippet.name.contains(|c: char| c.is_control()) {
            return Err(AppError::Validation(
                "A snippet name has no control characters".to_string(),
            ));
        }
        let command = snippet.command.chars().count();
        if snippet.command.trim().is_empty() || command > MAX_SNIPPET_COMMAND {
            return Err(AppError::Validation(format!(
                "A snippet command has 1 to {MAX_SNIPPET_COMMAND} characters"
            )));
        }
        if snippet
            .command
            .contains(|c: char| c.is_control() && c != '\n' && c != '\t')
        {
            return Err(AppError::Validation(
                "A snippet command has no control characters but line breaks and tabs".to_string(),
            ));
        }
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
    if let Some(ssh) = connection.options.as_ref().and_then(|o| o.ssh.as_ref()) {
        validate_ssh_options(ssh)?;
    }
    if let Some(rdp) = connection.options.as_ref().and_then(|o| o.rdp.as_ref()) {
        validate_rdp_options(rdp)?;
    }
    Ok(())
}

// The same formats as the server schema (apps/server/app/modules/connections/schemas.py). Checked
// here again because these values become ssh arguments, and not every source of a connection
// went through the server (local files, the sync URL).
const HOST: &str = r"(?:\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9_][A-Za-z0-9._-]{0,252})";
// HOST without the IPv6 literal.
const NAMED_HOST: &str = r"[A-Za-z0-9_][A-Za-z0-9._-]{0,252}";
const PORT: &str =
    r"(?:6553[0-5]|655[0-2][0-9]|65[0-4][0-9]{2}|6[0-4][0-9]{3}|[1-5][0-9]{4}|[1-9][0-9]{0,3})";
const USER: &str = r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}";

static JUMP_RE: LazyLock<Regex> = LazyLock::new(|| {
    // An IPv6 literal only in the last hop (R-1158): ssh unwraps the last hop itself, but copies
    // the hops before it unchanged into a ProxyCommand that does not keep the brackets as written.
    let earlier = format!("(?:{USER}@)?{NAMED_HOST}(?::{PORT})?");
    let last = format!("(?:{USER}@)?{HOST}(?::{PORT})?");
    Regex::new(&format!("^(?:{earlier},){{0,7}}{last}$")).expect("jump host pattern")
});
static LISTEN_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(&format!(r"^(?:(?:\*|{HOST}):)?{PORT}$")).expect("listen pattern"));
static TARGET_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(&format!("^{HOST}:{PORT}$")).expect("target pattern"));
static GATEWAY_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(&format!("^{HOST}(?::{PORT})?$")).expect("gateway pattern"));

const MAX_FORWARDS: usize = 32;

fn matches_within(re: &Regex, value: &str, max_len: usize) -> bool {
    value.len() <= max_len && re.is_match(value)
}

pub fn validate_ssh_options(ssh: &SshOptions) -> Result<(), AppError> {
    if let Some(ref jump) = ssh.jump_host {
        if !matches_within(&JUMP_RE, jump, 1000) {
            return Err(AppError::Validation("Invalid jump host".to_string()));
        }
    }
    if ssh.forwards.len() > MAX_FORWARDS {
        return Err(AppError::Validation(format!(
            "At most {MAX_FORWARDS} port forwards"
        )));
    }
    for forward in &ssh.forwards {
        if !matches_within(&LISTEN_RE, &forward.listen, 300) {
            return Err(AppError::Validation(
                "Invalid port forward listen address".to_string(),
            ));
        }
        match (forward.kind, forward.target.as_deref()) {
            (SshForwardKind::D, None) => {}
            (SshForwardKind::D, Some(_)) => {
                return Err(AppError::Validation(
                    "A dynamic forward takes no target".to_string(),
                ))
            }
            (_, Some(target)) if matches_within(&TARGET_RE, target, 300) => {}
            _ => {
                return Err(AppError::Validation(
                    "Invalid port forward target".to_string(),
                ))
            }
        }
    }
    if let Some(keepalive) = ssh.keepalive {
        if !(1..=3600).contains(&keepalive) {
            return Err(AppError::Validation(
                "Keepalive must be 1-3600 seconds".to_string(),
            ));
        }
    }
    Ok(())
}

pub fn validate_rdp_options(rdp: &RdpConnectionOptions) -> Result<(), AppError> {
    if let Some(ref gateway) = rdp.gateway {
        if !matches_within(&GATEWAY_RE, gateway, 300) {
            return Err(AppError::Validation("Invalid RD gateway".to_string()));
        }
    }
    if rdp.custom_size.is_some() {
        crate::connection::rdp_logic::parse_custom_size(rdp.custom_size.as_deref())?;
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
/// `api_proxy` and the callers of `session::authed_send` build the request URL by naive
/// string concatenation (`format!("{server_url}{path}")`). A frontend-supplied `path`
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
    fn snippet(name: &str, command: &str) -> Snippet {
        Snippet {
            name: name.to_string(),
            command: command.to_string(),
        }
    }

    #[test]
    fn snippets_within_bounds_pass() {
        let name = "n".repeat(MAX_SNIPPET_NAME);
        let command = "c".repeat(MAX_SNIPPET_COMMAND);
        assert!(validate_snippets(&[]).is_ok());
        assert!(validate_snippets(&[snippet(&name, &command)]).is_ok());
        assert!(validate_snippets(&[snippet("Größe", "cd /tmp\nls\t-la")]).is_ok());
        let many = vec![snippet("a", "b"); MAX_SNIPPETS];
        assert!(validate_snippets(&many).is_ok());
    }

    #[test]
    fn snippets_out_of_bounds_fail() {
        let too_long_name = "n".repeat(MAX_SNIPPET_NAME + 1);
        let too_long_command = "c".repeat(MAX_SNIPPET_COMMAND + 1);
        let too_many = vec![snippet("a", "b"); MAX_SNIPPETS + 1];
        for (case, snippets) in [
            ("too many", too_many),
            ("empty name", vec![snippet("", "ls")]),
            ("blank name", vec![snippet("  ", "ls")]),
            ("long name", vec![snippet(&too_long_name, "ls")]),
            ("line break in name", vec![snippet("a\nb", "ls")]),
            ("tab in name", vec![snippet("a\tb", "ls")]),
            ("empty command", vec![snippet("a", "")]),
            ("blank command", vec![snippet("a", " \n")]),
            ("long command", vec![snippet("a", &too_long_command)]),
            ("escape in command", vec![snippet("a", "ls\u{1b}[2J")]),
            ("carriage return in command", vec![snippet("a", "ls\r")]),
            ("ctrl-c in command", vec![snippet("a", "ls\u{3}")]),
            (
                "one bad of two",
                vec![snippet("a", "ls"), snippet("b", "ls\u{7f}")],
            ),
        ] {
            assert!(
                matches!(validate_snippets(&snippets), Err(AppError::Validation(_))),
                "{case}"
            );
        }
    }

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
            options: None,
        }
    }

    fn with_ssh_options(json: serde_json::Value) -> Result<Connection, serde_json::Error> {
        let mut c = ssh_connection_with_key_path("");
        c.options = Some(serde_json::from_value(serde_json::json!({ "ssh": json }))?);
        Ok(c)
    }

    #[test]
    fn validate_connection_input_accepts_good_ssh_options() {
        let c = with_ssh_options(serde_json::json!({
            "jumpHost": "ops@bastion.example.org:2222,h3,[2001:db8::1]",
            "forwards": [
                {"type": "L", "listen": "8080", "target": "intranet.local:80"},
                {"type": "R", "listen": "127.0.0.1:65535", "target": "[::1]:1"},
                {"type": "D", "listen": "*:1080"}
            ],
            "keepalive": 3600
        }))
        .unwrap();
        assert!(validate_connection_input(&c).is_ok());
    }

    #[test]
    fn validate_connection_input_rejects_bad_ssh_options() {
        let nine_hops = ["h"; 9].join(",");
        let long_host = "a".repeat(254);
        let too_many: Vec<_> = (0..33)
            .map(|_| serde_json::json!({"type": "D", "listen": "1080"}))
            .collect();
        let bad = [
            serde_json::json!({"jumpHost": "-oProxyCommand=touch /tmp/x"}),
            serde_json::json!({"jumpHost": "user@-host"}),
            serde_json::json!({"jumpHost": "host;id"}),
            serde_json::json!({"jumpHost": "host name"}),
            serde_json::json!({"jumpHost": "host\n-oX"}),
            serde_json::json!({"jumpHost": "host\u{1}"}),
            serde_json::json!({"jumpHost": "host:0"}),
            serde_json::json!({"jumpHost": "host:65536"}),
            serde_json::json!({"jumpHost": ""}),
            serde_json::json!({"jumpHost": "h,"}),
            // an IPv6 literal only in the last hop (R-1158)
            serde_json::json!({"jumpHost": "[2001:db8::1],h2"}),
            serde_json::json!({"jumpHost": "ops@[2001:db8::1]:22,h2"}),
            serde_json::json!({"jumpHost": "h1,[2001:db8::1],h3"}),
            serde_json::json!({"jumpHost": "h\u{e4}"}),
            serde_json::json!({"jumpHost": nine_hops}),
            serde_json::json!({"jumpHost": long_host}),
            serde_json::json!({"forwards": [{"type": "L", "listen": "0", "target": "h:1"}]}),
            serde_json::json!({"forwards": [{"type": "L", "listen": "-1", "target": "h:1"}]}),
            serde_json::json!({"forwards": [{"type": "L", "listen": "80", "target": "-oX=y:1"}]}),
            serde_json::json!({"forwards": [{"type": "L", "listen": "80", "target": "h:1 -oX=y"}]}),
            serde_json::json!({"forwards": [{"type": "L", "listen": "80", "target": "h"}]}),
            serde_json::json!({"forwards": [{"type": "L", "listen": "80"}]}),
            serde_json::json!({"forwards": [{"type": "R", "listen": "80"}]}),
            serde_json::json!({"forwards": [{"type": "D", "listen": "1080", "target": "h:1"}]}),
            serde_json::json!({"forwards": too_many}),
            serde_json::json!({"keepalive": 0}),
            serde_json::json!({"keepalive": 3601}),
        ];
        for options in bad {
            let c = with_ssh_options(options.clone()).unwrap();
            assert!(validate_connection_input(&c).is_err(), "{options}");
        }
    }

    #[test]
    fn unknown_forward_types_and_auth_methods_do_not_parse() {
        // Closed enums: a value the desktop cannot map never becomes an argument.
        for options in [
            serde_json::json!({"forwards": [{"type": "X", "listen": "80"}]}),
            serde_json::json!({"authMethod": "keyboard-interactive"}),
        ] {
            assert!(with_ssh_options(options).is_err());
        }
    }

    #[test]
    fn a_connection_without_options_still_loads_and_omits_them() {
        let c: Connection = serde_json::from_value(serde_json::json!({
            "id": "1", "name": "n", "kind": "ssh", "host": "h", "port": null, "username": null,
            "domain": null, "keyPath": null, "url": null, "notes": null, "lastUsed": null
        }))
        .unwrap();
        assert!(c.options.is_none());
        assert!(serde_json::to_value(&c).unwrap().get("options").is_none());
    }

    #[test]
    fn sanitize_synced_connections_drops_entries_with_bad_ssh_options() {
        let good = ssh_connection_with_key_path("");
        let bad = with_ssh_options(serde_json::json!({"jumpHost": "-oX"})).unwrap();
        assert_eq!(sanitize_synced_connections(vec![good, bad]).len(), 1);
    }

    fn with_rdp_options(json: serde_json::Value) -> Result<Connection, serde_json::Error> {
        let mut c = ssh_connection_with_key_path("");
        c.kind = ConnectionKind::Rdp;
        c.options = Some(serde_json::from_value(serde_json::json!({ "rdp": json }))?);
        Ok(c)
    }

    #[test]
    fn validate_connection_input_accepts_good_rdp_options() {
        for gateway in [
            "rdgw.example.org",
            "rdgw.example.org:443",
            "[2001:db8::1]:8443",
        ] {
            let c = with_rdp_options(serde_json::json!({
                "scalingMode": "hdpi", "windowMode": "custom", "customSize": "1920x1080",
                "performanceProfile": "lan", "drives": true, "audio": "remote",
                "printers": false, "gateway": gateway, "nla": true
            }))
            .unwrap();
            assert!(validate_connection_input(&c).is_ok(), "{gateway}");
        }
    }

    #[test]
    fn validate_connection_input_rejects_bad_rdp_options() {
        let long_gateway = "a".repeat(301);
        for options in [
            serde_json::json!({"gateway": "-gw"}),
            serde_json::json!({"gateway": "gw /u:admin"}),
            serde_json::json!({"gateway": "gw,u:admin"}),
            serde_json::json!({"gateway": "gw\n/p:x"}),
            serde_json::json!({"gateway": "gw:0"}),
            serde_json::json!({"gateway": "gw:65536"}),
            serde_json::json!({"gateway": ""}),
            serde_json::json!({"gateway": long_gateway}),
            serde_json::json!({"customSize": "100x100"}),
            serde_json::json!({"customSize": "1920x1080x60"}),
            serde_json::json!({"customSize": "1920x1080 /p:x"}),
        ] {
            let c = with_rdp_options(options.clone()).unwrap();
            assert!(validate_connection_input(&c).is_err(), "{options}");
        }
    }

    #[test]
    fn unknown_rdp_enum_values_do_not_parse() {
        for options in [
            serde_json::json!({"scalingMode": "zoom"}),
            serde_json::json!({"audio": "loud"}),
            serde_json::json!({"windowMode": "kiosk"}),
        ] {
            assert!(with_rdp_options(options).is_err());
        }
    }

    #[test]
    fn rdp_options_round_trip_and_keep_only_the_fields_set() {
        let c = with_rdp_options(serde_json::json!({"nla": false, "gateway": "gw"})).unwrap();
        assert_eq!(
            serde_json::to_value(&c).unwrap()["options"],
            serde_json::json!({"rdp": {"gateway": "gw", "nla": false}})
        );
    }

    #[test]
    fn sanitize_synced_connections_drops_entries_with_bad_rdp_options() {
        let good = ssh_connection_with_key_path("");
        let bad = with_rdp_options(serde_json::json!({"gateway": "-gw"})).unwrap();
        assert_eq!(sanitize_synced_connections(vec![good, bad]).len(), 1);
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
    fn sanitize_window_title_keeps_safe_chars_drops_the_rest_and_caps_at_64() {
        // Defense-in-depth against X11/terminal escapes fed to xfreerdp /title: only the safe charset
        // survives, and the title is capped at 64 chars (6.112).
        assert_eq!(
            sanitize_window_title("srv-01 (ssh).lab:22"),
            "srv-01 (ssh).lab:22"
        );
        // Disallowed chars — ';', ESC, brackets — are stripped.
        assert_eq!(sanitize_window_title("a;b\u{1b}[0m"), "ab0m");
        // Capped at 64 chars.
        assert_eq!(sanitize_window_title(&"x".repeat(100)).chars().count(), 64);
        // Trimmed.
        assert_eq!(sanitize_window_title("  hi  "), "hi");
    }

    #[test]
    fn sanitize_synced_connections_drops_invalid_entries() {
        // The only filter between server data and the local store: an entry that fails
        // validate_connection_input (here a path-traversal key_path) is dropped, valid ones kept (6.112).
        let valid = ssh_connection_with_key_path("/home/u/.ssh/id_rsa");
        let invalid = ssh_connection_with_key_path("../../../etc/passwd");
        let out = sanitize_synced_connections(vec![valid.clone(), invalid]);
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].key_path, valid.key_path);
    }
}
