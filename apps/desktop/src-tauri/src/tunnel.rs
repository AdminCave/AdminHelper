// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use serde::{Deserialize, Serialize};

use crate::auth;
use crate::error::AppError;
use crate::models::{Connection, ConnectionKind, VisitorBinding};
use crate::session::SessionState;

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
pub async fn fetch_tunnels(session: &SessionState) -> Result<Vec<TunnelMapping>, AppError> {
    let (response, _) = auth::authenticated_get(session, "/api/frp/tunnels").await?;

    if !response.status().is_success() {
        return Err(AppError::Validation(
            "Tunnel-Liste konnte nicht geladen werden".to_string(),
        ));
    }

    let tunnels: Vec<TunnelMapping> = response.json().await?;
    Ok(tunnels)
}

/// Resolve a connection through a tunnel if one exists. `bindings` are where the visitors of the
/// running frpc listen, empty while none runs; an STCP target resolves only to the local port of
/// one of them and otherwise stays as it is.
///
/// A mapping of the connection decides first (only admins read mappings); its visitor port is the
/// server port of a visitor. Without one, a target of `127.0.0.1` or `localhost` at the server port
/// of a visitor resolves to that visitor: the server's automatic connections name it so. The
/// allow-list admits every server port once, so the visitor is never ambiguous.
pub fn resolve_connection(
    connection: &Connection,
    tunnels: &[TunnelMapping],
    bindings: &[VisitorBinding],
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
                    let visitor = t.visitor_port.and_then(|vport| visitor_at(bindings, vport));
                    if let Some(visitor) = visitor {
                        to_visitor(&mut resolved, visitor.local_port, t.protocol == "web");
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
        None => match literal_visitor(connection, bindings) {
            Some(visitor) => {
                let mut resolved = connection.clone();
                let web = connection.kind == ConnectionKind::Web;
                to_visitor(&mut resolved, visitor.local_port, web);
                ResolvedConnection {
                    connection: resolved,
                    via_tunnel: true,
                    tunnel_name: Some(visitor.name.clone()),
                    // The allow-list admits STCP visitors only.
                    tunnel_type: Some("stcp".to_string()),
                }
            }
            None => ResolvedConnection {
                connection: connection.clone(),
                via_tunnel: false,
                tunnel_name: None,
                tunnel_type: None,
            },
        },
    }
}

/// The visitor of the running frpc at `server_port`.
fn visitor_at(bindings: &[VisitorBinding], server_port: u16) -> Option<&VisitorBinding> {
    bindings
        .iter()
        .find(|binding| binding.server_port == server_port)
}

/// The visitor a target of `127.0.0.1` or `localhost` at its server port names. frpc listens on
/// `127.0.0.1` only, so no other loopback address reaches it.
fn literal_visitor<'a>(
    connection: &Connection,
    bindings: &'a [VisitorBinding],
) -> Option<&'a VisitorBinding> {
    let host = connection.host.as_deref()?;
    if host != "127.0.0.1" && !host.eq_ignore_ascii_case("localhost") {
        return None;
    }
    visitor_at(bindings, connection.port?)
}

/// Point `connection` at a visitor on `127.0.0.1`:`local_port`; a web one gets the URL too.
fn to_visitor(connection: &mut Connection, local_port: u16, web: bool) {
    // `localhost` may resolve to `::1` first, where frpc does not listen.
    connection.host = Some("127.0.0.1".to_string());
    connection.port = Some(local_port);
    if web {
        connection.url = Some(format!("http://127.0.0.1:{local_port}"));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
            server_id: None,
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

    fn binding(name: &str, server_port: u16, local_port: u16) -> VisitorBinding {
        VisitorBinding {
            name: name.to_string(),
            server_port,
            local_port,
        }
    }

    /// A running frpc whose visitor for `tunnel`'s visitor port listens on that port itself.
    fn same_ports() -> Vec<VisitorBinding> {
        vec![binding("tunnel-1-visitor", 13389, 13389)]
    }

    /// A running frpc whose visitors listen elsewhere than their server ports.
    fn moved_ports() -> Vec<VisitorBinding> {
        vec![
            binding("db-visitor", 6000, 23005),
            binding("tunnel-1-visitor", 13389, 23000),
            binding("web-visitor", 6001, 6001),
        ]
    }

    /// A connection to `host`:`port` with no tunnel of its own, as a non-admin sees an automatic
    /// one.
    fn literal(kind: ConnectionKind, host: &str, port: u16) -> Connection {
        Connection {
            kind,
            host: Some(host.to_string()),
            port: Some(port),
            ..connection("auto")
        }
    }

    #[test]
    fn no_tunnels_returns_connection_unchanged() {
        let conn = connection("c1");
        let resolved = resolve_connection(&conn, &[], &[]);
        assert!(!resolved.via_tunnel);
        assert_eq!(resolved.tunnel_name, None);
        assert_eq!(resolved.tunnel_type, None);
        assert_eq!(resolved.connection.host.as_deref(), Some("server.internal"));
        assert_eq!(resolved.connection.port, Some(3389));
    }

    #[test]
    fn tunnel_for_other_connection_is_ignored() {
        let conn = connection("c1");
        let resolved = resolve_connection(&conn, &[tunnel("other", "stcp", "rdp")], &same_ports());
        assert!(!resolved.via_tunnel);
    }

    #[test]
    fn disabled_tunnel_is_ignored() {
        let conn = connection("c1");
        let mut mapping = tunnel("c1", "stcp", "rdp");
        mapping.enabled = false;
        let resolved = resolve_connection(&conn, &[mapping], &same_ports());
        assert!(!resolved.via_tunnel);
    }

    #[test]
    fn stcp_rewrites_host_and_port_to_local_visitor() {
        let conn = connection("c1");
        let resolved = resolve_connection(&conn, &[tunnel("c1", "stcp", "rdp")], &same_ports());
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
        let resolved = resolve_connection(&conn, &[tunnel("c1", "stcp", "web")], &same_ports());
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
        let resolved = resolve_connection(&conn, &[mapping], &same_ports());
        assert!(resolved.via_tunnel);
        assert_eq!(resolved.connection.host.as_deref(), Some("server.internal"));
        assert_eq!(resolved.connection.port, Some(3389));
    }

    #[test]
    fn https_uses_first_custom_domain() {
        let conn = connection("c1");
        let mut mapping = tunnel("c1", "https", "web");
        mapping.custom_domains = Some("a.example.com, b.example.com".to_string());
        let resolved = resolve_connection(&conn, &[mapping], &same_ports());
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
        let resolved = resolve_connection(&conn, &[mapping], &same_ports());
        assert!(resolved.via_tunnel);
        assert_eq!(resolved.connection.url, None);

        let mut mapping = tunnel("c1", "https", "web");
        mapping.custom_domains = None;
        let resolved = resolve_connection(&conn, &[mapping], &same_ports());
        assert!(resolved.via_tunnel);
        assert_eq!(resolved.connection.url, None);
    }

    #[test]
    fn unknown_tunnel_type_keeps_connection_unchanged_but_marks_tunnel() {
        let conn = connection("c1");
        let resolved = resolve_connection(&conn, &[tunnel("c1", "tcp", "rdp")], &same_ports());
        assert!(resolved.via_tunnel);
        assert_eq!(resolved.tunnel_type.as_deref(), Some("tcp"));
        assert_eq!(resolved.connection.host.as_deref(), Some("server.internal"));
        assert_eq!(resolved.connection.port, Some(3389));
        assert_eq!(resolved.connection.url, None);
    }

    /// The whole connection, to compare one with another.
    fn json(connection: &Connection) -> serde_json::Value {
        serde_json::to_value(connection).unwrap()
    }

    /// `connection` with its target moved to `127.0.0.1`:`port`, nothing else changed.
    fn at_loopback(connection: &Connection, port: u16, url: Option<&str>) -> serde_json::Value {
        json(&Connection {
            host: Some("127.0.0.1".to_string()),
            port: Some(port),
            url: url.map(str::to_string),
            ..connection.clone()
        })
    }

    #[test]
    fn stcp_mapping_resolves_to_the_local_port_of_its_visitor() {
        let conn = connection("c1");

        let resolved = resolve_connection(&conn, &[tunnel("c1", "stcp", "rdp")], &moved_ports());
        assert!(resolved.via_tunnel);
        assert_eq!(resolved.tunnel_name.as_deref(), Some("tunnel-1"));
        assert_eq!(resolved.tunnel_type.as_deref(), Some("stcp"));
        assert_eq!(json(&resolved.connection), at_loopback(&conn, 23000, None));

        let resolved = resolve_connection(&conn, &[tunnel("c1", "stcp", "web")], &moved_ports());
        assert_eq!(
            json(&resolved.connection),
            at_loopback(&conn, 23000, Some("http://127.0.0.1:23000"))
        );
    }

    #[test]
    fn literal_loopback_target_resolves_without_a_mapping() {
        // A non-admin reads no mappings; the server's automatic connection names the visitor's
        // server port on loopback. A mapping of another connection changes nothing.
        let other = [tunnel("other", "stcp", "rdp")];
        for tunnels in [&[][..], &other[..]] {
            for (host, port, visitor, local) in [
                ("127.0.0.1", 6000, "db-visitor", 23005),
                ("localhost", 6000, "db-visitor", 23005),
                ("LOCALHOST", 6000, "db-visitor", 23005),
                ("127.0.0.1", 13389, "tunnel-1-visitor", 23000),
                ("127.0.0.1", 6001, "web-visitor", 6001),
            ] {
                let case = format!("{host}:{port} with {} mappings", tunnels.len());
                let conn = literal(ConnectionKind::Ssh, host, port);
                let resolved = resolve_connection(&conn, tunnels, &moved_ports());
                assert!(resolved.via_tunnel, "{case}");
                assert_eq!(resolved.tunnel_name.as_deref(), Some(visitor), "{case}");
                assert_eq!(resolved.tunnel_type.as_deref(), Some("stcp"), "{case}");
                assert_eq!(
                    json(&resolved.connection),
                    at_loopback(&conn, local, None),
                    "{case}"
                );
            }
        }

        let web = literal(ConnectionKind::Web, "localhost", 6000);
        let resolved = resolve_connection(&web, &[], &moved_ports());
        assert_eq!(
            json(&resolved.connection),
            at_loopback(&web, 23005, Some("http://127.0.0.1:23005"))
        );
    }

    #[test]
    fn literal_target_outside_the_port_map_stays_unchanged() {
        let ssh = |host: &str, port: u16| literal(ConnectionKind::Ssh, host, port);
        for (case, conn) in [
            ("a port no visitor asked for", ssh("127.0.0.1", 6002)),
            ("a visitor's local port", ssh("127.0.0.1", 23005)),
            ("another host", ssh("server.internal", 6000)),
            ("loopback frpc does not listen on", ssh("::1", 6000)),
            (
                "no host",
                Connection {
                    host: None,
                    ..ssh("127.0.0.1", 6000)
                },
            ),
            (
                "no port",
                Connection {
                    port: None,
                    ..ssh("127.0.0.1", 6000)
                },
            ),
        ] {
            let resolved = resolve_connection(&conn, &[], &moved_ports());
            assert!(!resolved.via_tunnel, "{case}");
            assert_eq!(resolved.tunnel_name, None, "{case}");
            assert_eq!(json(&resolved.connection), json(&conn), "{case}");
        }
    }

    #[test]
    fn stcp_target_without_a_listening_visitor_stays_unchanged() {
        let mapped = connection("c1");
        let auto = literal(ConnectionKind::Web, "127.0.0.1", 13389);
        let only_db = [binding("db-visitor", 6000, 23005)];
        for (case, conn, tunnels, bindings) in [
            (
                "mapped, no frpc runs",
                &mapped,
                vec![tunnel("c1", "stcp", "rdp")],
                &[][..],
            ),
            (
                "mapped web, no frpc runs",
                &mapped,
                vec![tunnel("c1", "stcp", "web")],
                &[][..],
            ),
            ("literal, no frpc runs", &auto, vec![], &[][..]),
            (
                "mapped, frpc runs other visitors",
                &mapped,
                vec![tunnel("c1", "stcp", "rdp")],
                &only_db[..],
            ),
            (
                "literal, frpc runs other visitors",
                &auto,
                vec![],
                &only_db[..],
            ),
        ] {
            let resolved = resolve_connection(conn, &tunnels, bindings);
            assert_eq!(json(&resolved.connection), json(conn), "{case}");
        }
    }
}
