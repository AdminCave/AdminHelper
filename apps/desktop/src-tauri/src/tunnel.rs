// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use serde::{Deserialize, Serialize};

use crate::auth;
use crate::error::AppError;
use crate::models::Connection;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TunnelMapping {
    pub id: String,
    pub server_id: String,
    pub tunnel_type: String,
    pub protocol: String,
    pub local_port: u16,
    pub visitor_port: Option<u16>,
    pub custom_domains: Option<String>,
    pub connection_id: Option<String>,
    pub enabled: bool,
    pub name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ResolvedConnection {
    pub connection: Connection,
    pub via_tunnel: bool,
    pub tunnel_name: Option<String>,
    pub tunnel_type: Option<String>,
}

/// Fetch all tunnels from the server.
pub async fn fetch_tunnels(
    server_url: &str,
    token: &str,
    allow_self_signed: bool,
) -> Result<Vec<TunnelMapping>, AppError> {
    let response =
        auth::authenticated_get(server_url, token, "/api/frp/tunnels", allow_self_signed).await?;

    if !response.status().is_success() {
        return Err(AppError::Validation(
            "Tunnel-Liste konnte nicht geladen werden".to_string(),
        ));
    }

    let tunnels: Vec<TunnelMapping> = response.json().await?;
    Ok(tunnels)
}

/// Resolve a connection through a tunnel if one exists.
pub fn resolve_connection(
    connection: &Connection,
    tunnels: &[TunnelMapping],
) -> ResolvedConnection {
    // Find matching tunnel by connectionId
    let tunnel = tunnels
        .iter()
        .find(|t| t.enabled && t.connection_id.as_deref() == Some(&connection.id));

    match tunnel {
        Some(t) => {
            let mut resolved = connection.clone();
            match t.tunnel_type.as_str() {
                "stcp" => {
                    if let Some(vport) = t.visitor_port {
                        resolved.host = Some("127.0.0.1".to_string());
                        resolved.port = Some(vport);
                        if t.protocol == "web" {
                            resolved.url = Some(format!("http://127.0.0.1:{vport}"));
                        }
                    }
                }
                "https" => {
                    if let Some(ref domains) = t.custom_domains {
                        let domain = domains.split(',').next().unwrap_or("").trim();
                        if !domain.is_empty() {
                            resolved.url = Some(format!("https://{domain}"));
                        }
                    }
                }
                _ => {}
            }
            ResolvedConnection {
                connection: resolved,
                via_tunnel: true,
                tunnel_name: Some(t.name.clone()),
                tunnel_type: Some(t.tunnel_type.clone()),
            }
        }
        None => ResolvedConnection {
            connection: connection.clone(),
            via_tunnel: false,
            tunnel_name: None,
            tunnel_type: None,
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::ConnectionKind;

    fn connection(id: &str) -> Connection {
        Connection {
            id: id.to_string(),
            name: "Test".to_string(),
            kind: ConnectionKind::Rdp,
            host: Some("server.internal".to_string()),
            port: Some(3389),
            username: None,
            domain: None,
            key_path: None,
            url: None,
            notes: None,
            tags: Vec::new(),
            trust_cert: false,
            last_used: None,
        }
    }

    fn tunnel(connection_id: &str, tunnel_type: &str, protocol: &str) -> TunnelMapping {
        TunnelMapping {
            id: "t1".to_string(),
            server_id: "s1".to_string(),
            tunnel_type: tunnel_type.to_string(),
            protocol: protocol.to_string(),
            local_port: 3389,
            visitor_port: Some(13389),
            custom_domains: None,
            connection_id: Some(connection_id.to_string()),
            enabled: true,
            name: "tunnel-1".to_string(),
        }
    }

    #[test]
    fn no_tunnels_returns_connection_unchanged() {
        let conn = connection("c1");
        let resolved = resolve_connection(&conn, &[]);
        assert!(!resolved.via_tunnel);
        assert_eq!(resolved.tunnel_name, None);
        assert_eq!(resolved.tunnel_type, None);
        assert_eq!(resolved.connection.host.as_deref(), Some("server.internal"));
        assert_eq!(resolved.connection.port, Some(3389));
    }

    #[test]
    fn tunnel_for_other_connection_is_ignored() {
        let conn = connection("c1");
        let resolved = resolve_connection(&conn, &[tunnel("other", "stcp", "rdp")]);
        assert!(!resolved.via_tunnel);
    }

    #[test]
    fn disabled_tunnel_is_ignored() {
        let conn = connection("c1");
        let mut mapping = tunnel("c1", "stcp", "rdp");
        mapping.enabled = false;
        let resolved = resolve_connection(&conn, &[mapping]);
        assert!(!resolved.via_tunnel);
    }

    #[test]
    fn stcp_rewrites_host_and_port_to_local_visitor() {
        let conn = connection("c1");
        let resolved = resolve_connection(&conn, &[tunnel("c1", "stcp", "rdp")]);
        assert!(resolved.via_tunnel);
        assert_eq!(resolved.tunnel_name.as_deref(), Some("tunnel-1"));
        assert_eq!(resolved.tunnel_type.as_deref(), Some("stcp"));
        assert_eq!(resolved.connection.host.as_deref(), Some("127.0.0.1"));
        assert_eq!(resolved.connection.port, Some(13389));
        assert_eq!(resolved.connection.url, None);
    }

    #[test]
    fn stcp_web_protocol_sets_local_url() {
        let conn = connection("c1");
        let resolved = resolve_connection(&conn, &[tunnel("c1", "stcp", "web")]);
        assert_eq!(
            resolved.connection.url.as_deref(),
            Some("http://127.0.0.1:13389")
        );
    }

    #[test]
    fn stcp_without_visitor_port_keeps_original_target() {
        let conn = connection("c1");
        let mut mapping = tunnel("c1", "stcp", "rdp");
        mapping.visitor_port = None;
        let resolved = resolve_connection(&conn, &[mapping]);
        assert!(resolved.via_tunnel);
        assert_eq!(resolved.connection.host.as_deref(), Some("server.internal"));
        assert_eq!(resolved.connection.port, Some(3389));
    }

    #[test]
    fn https_uses_first_custom_domain() {
        let conn = connection("c1");
        let mut mapping = tunnel("c1", "https", "web");
        mapping.custom_domains = Some("a.example.com, b.example.com".to_string());
        let resolved = resolve_connection(&conn, &[mapping]);
        assert!(resolved.via_tunnel);
        assert_eq!(
            resolved.connection.url.as_deref(),
            Some("https://a.example.com")
        );
        // Host/port are not rewritten on the https path.
        assert_eq!(resolved.connection.host.as_deref(), Some("server.internal"));
        assert_eq!(resolved.connection.port, Some(3389));
    }

    #[test]
    fn https_with_empty_or_missing_domains_keeps_url_unset() {
        let conn = connection("c1");

        let mut mapping = tunnel("c1", "https", "web");
        mapping.custom_domains = Some("".to_string());
        let resolved = resolve_connection(&conn, &[mapping]);
        assert!(resolved.via_tunnel);
        assert_eq!(resolved.connection.url, None);

        let mut mapping = tunnel("c1", "https", "web");
        mapping.custom_domains = None;
        let resolved = resolve_connection(&conn, &[mapping]);
        assert!(resolved.via_tunnel);
        assert_eq!(resolved.connection.url, None);
    }

    #[test]
    fn unknown_tunnel_type_keeps_connection_unchanged_but_marks_tunnel() {
        let conn = connection("c1");
        let resolved = resolve_connection(&conn, &[tunnel("c1", "tcp", "rdp")]);
        assert!(resolved.via_tunnel);
        assert_eq!(resolved.tunnel_type.as_deref(), Some("tcp"));
        assert_eq!(resolved.connection.host.as_deref(), Some("server.internal"));
        assert_eq!(resolved.connection.port, Some(3389));
        assert_eq!(resolved.connection.url, None);
    }
}
