// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::net::{Ipv4Addr, Ipv6Addr};

use serde::{Deserialize, Serialize};
use url::{Host, Url};

use crate::auth;
use crate::error::AppError;
use crate::models::{Connection, ConnectionKind, VisitorBinding};
use crate::session::SessionState;
use crate::validation::validate_web_url;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TunnelMapping {
    pub id: String,
    pub server_id: String,
    pub tunnel_type: String,
    pub protocol: String,
    // Wider than a port: the server may still list a row stored before it checked the range,
    // and one such row must not fail the whole list. Only a value that is a port resolves.
    pub local_port: i64,
    pub visitor_port: Option<i64>,
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

/// Fetch all tunnels from the server. The session keeps them for the check of a stored
/// password ([`SessionState::keep_tunnels`]). A refusal (401, 403) drops the last ones; a fetch
/// that fails otherwise (network, server error) leaves them.
pub async fn fetch_tunnels(session: &SessionState) -> Result<Vec<TunnelMapping>, AppError> {
    let (response, who) = auth::authenticated_get(session, "/api/frp/tunnels").await?;

    if matches!(
        response.status(),
        reqwest::StatusCode::UNAUTHORIZED | reqwest::StatusCode::FORBIDDEN
    ) {
        // The user may not read the mappings (any more), so none of the last ones count. A
        // session gone meanwhile has none left to drop.
        let _ = session.keep_tunnels(&who, Vec::new()).await;
    }
    if !response.status().is_success() {
        return Err(AppError::Validation(
            "Tunnel-Liste konnte nicht geladen werden".to_string(),
        ));
    }

    let tunnels: Vec<TunnelMapping> = response.json().await?;
    session.keep_tunnels(&who, tunnels.clone()).await?;
    Ok(tunnels)
}

/// Resolve a connection through a tunnel if one exists. `bindings` are where the visitors of the
/// running frpc listen, empty while none runs; an STCP target resolves only to the local port of
/// one of them and otherwise stays as it is.
///
/// A mapping of the connection decides first (admins read all, other users those of the enabled
/// tunnels on the servers assigned to them); its visitor port is the server port of a visitor.
/// Without one, a target of `127.0.0.1` or `localhost` at the server port of a visitor resolves to
/// that visitor: the server's automatic connections name it so. The allow-list admits every server
/// port once, so the visitor is never ambiguous.
pub fn resolve_connection(
    connection: &Connection,
    tunnels: &[TunnelMapping],
    bindings: &[VisitorBinding],
) -> ResolvedConnection {
    match mapping_of(connection, tunnels) {
        Some(t) => {
            let mut resolved = connection.clone();
            match t.tunnel_type.as_str() {
                "stcp" => {
                    let visitor = t
                        .visitor_port
                        .and_then(|vport| u16::try_from(vport).ok())
                        .and_then(|vport| visitor_at(bindings, vport));
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

/// The enabled mapping of `connection`, found by its id.
pub fn mapping_of<'a>(
    connection: &Connection,
    tunnels: &'a [TunnelMapping],
) -> Option<&'a TunnelMapping> {
    tunnels
        .iter()
        .find(|t| t.enabled && t.connection_id.as_deref() == Some(&connection.id))
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

/// Rejects `connection` if it goes to this machine at a port of another workspace's tunnel:
/// `others` are the local ports the port map gives the visitors of the other workspaces
/// (`PortRegistry::local_ports_of_others`), `bindings` where the visitors of this workspace's
/// frpc listen. Without a frpc of its own, a target at `127.0.0.1:<server port>` would reach the
/// frpc of another workspace and through it a machine of another server. A port a visitor of
/// this workspace listens on is its own. The target is the host at its port as the starter takes
/// them (see [`host_targets`]), for a web connection also its URL. A host the check cannot read
/// may name this machine at any port, so it is refused while the map holds a port of another
/// workspace.
///
/// Every port of the map counts, so through the visitors it sends, a server can also keep the
/// connections of another workspace from a loopback port that is no tunnel of anyone. That fails
/// safe: a refusal, never a connection elsewhere.
pub fn reject_foreign_port(
    connection: &Connection,
    others: &[u16],
    bindings: &[VisitorBinding],
) -> Result<(), AppError> {
    let at_url = connection
        .url
        .as_deref()
        .filter(|_| connection.kind == ConnectionKind::Web)
        // Read as the browser gets it, a URL without a scheme included.
        .and_then(|raw| Url::parse(&validate_web_url(raw).ok()?).ok())
        .and_then(|url| {
            let loopback = url.host().is_some_and(|host| is_loopback(&host));
            loopback.then_some(Loopback::At(url.port_or_known_default()?))
        });
    let own = |port: u16| bindings.iter().any(|binding| binding.local_port == port);
    let foreign = |port: &u16| others.contains(port) && !own(*port);
    for target in host_targets(connection).into_iter().chain(at_url) {
        match target {
            Loopback::At(port) if foreign(&port) => {
                return Err(AppError::Connection(format!(
                    "port {port} on this machine belongs to the tunnel of another workspace; \
                     start the tunnel of this workspace to connect"
                )))
            }
            // Its own tunnel would not help: no port of it is in `others`.
            Loopback::Unread if others.iter().any(foreign) => {
                return Err(AppError::Connection(
                    "the host of this connection cannot be read and may lead to the tunnel of \
                     another workspace on this machine; write the host as a name or an address, \
                     and the user and the port in their own fields"
                        .to_string(),
                ))
            }
            _ => {}
        }
    }
    Ok(())
}

/// Where a target reaches this machine.
enum Loopback {
    At(u16),
    /// A host the check cannot read: it may name this machine, at a port it carries itself.
    Unread,
}

/// Where the host of `connection` reaches this machine, as the starter takes host and port:
/// without a port, the one `ssh` and `rdp` take. Empty without a host, for another machine, and
/// for a web connection's host without a port.
///
/// `ssh` reads a destination `ssh://…` itself, and the port in it counts unless `-p` names
/// another (`ssh.rs` passes `-p` only for a port other than 22); any other destination it splits
/// at the last `@`, the host being what follows. An RDP host may carry a port, `host:port` or
/// `[IPv6 address]:port`.
fn host_targets(connection: &Connection) -> Vec<Loopback> {
    let Some(host) = connection
        .host
        .as_deref()
        .map(str::trim)
        .filter(|host| !host.is_empty())
    else {
        return Vec::new();
    };
    let at = |host: &str, ports: &[u16]| match host_is_loopback(host) {
        Some(true) => ports.iter().map(|&port| Loopback::At(port)).collect(),
        Some(false) => Vec::new(),
        None => vec![Loopback::Unread],
    };
    match connection.kind {
        // Only a lower-case `ssh://` is a URI to OpenSSH; no other spelling reads as a host.
        ConnectionKind::Ssh if host.starts_with("ssh://") => match ssh_uri(host) {
            Some((host, uri_port)) => {
                let port = match connection.port {
                    Some(port) if port != 22 => port,
                    _ => uri_port.unwrap_or(22),
                };
                at(host, &[port])
            }
            None => vec![Loopback::Unread],
        },
        ConnectionKind::Ssh => {
            let host = host.rsplit_once('@').map_or(host, |(_user, host)| host);
            at(host, &[connection.port.unwrap_or(22)])
        }
        ConnectionKind::Rdp => {
            let port = connection.port.unwrap_or(3389);
            match (host_is_loopback(host), rdp_host_port(host)) {
                // Not verified which of the two ports FreeRDP (`/v:host:port:port`) or mstsc
                // (`full address:s:host:port:port`) takes, so both count.
                (None, Some((host, in_host))) => at(host, &[in_host, port]),
                _ => at(host, &[port]),
            }
        }
        ConnectionKind::Web => at(host, connection.port.as_slice()),
    }
}

/// Host and port of an RDP host `host:port` or `[IPv6 address]:port`; an IPv6 address carries a
/// port only in brackets.
pub(crate) fn rdp_host_port(host: &str) -> Option<(&str, u16)> {
    let (host, port) = match host.strip_prefix('[') {
        Some(bracketed) => {
            let (address, rest) = bracketed.split_once(']')?;
            (address, rest.strip_prefix(':')?)
        }
        None => host.split_once(':')?,
    };
    Some((host, port.parse().ok()?))
}

/// Host and port of an OpenSSH destination `ssh://[user[;params]@]host[:port][/]`, split as
/// OpenSSH's `parse_uri` splits it: the user up to the first `@`, then a host in brackets or up
/// to the first `:` or `/`. `None` for what it reads otherwise or refuses (a path, a port by
/// service name such as `x11`).
fn ssh_uri(destination: &str) -> Option<(&str, Option<u16>)> {
    let rest = destination.strip_prefix("ssh://")?;
    let rest = rest.split_once('@').map_or(rest, |(_, host)| host);
    let (host, tail) = match rest.strip_prefix('[') {
        Some(bracketed) => bracketed.split_once(']')?,
        None => rest.split_at(rest.find([':', '/']).unwrap_or(rest.len())),
    };
    let port = match tail.strip_prefix(':') {
        Some(port) => {
            let port = port.strip_suffix('/').unwrap_or(port);
            match port {
                "" => None,
                _ => Some(port.parse::<u16>().ok().filter(|&port| port > 0)?),
            }
        }
        None if tail.is_empty() || tail == "/" => None,
        None => return None,
    };
    Some((host, port))
}

/// Whether the host of a connection, as `ssh`, `xfreerdp` or `mstsc` take it, names this
/// machine; `None` if the check cannot read it. The URL host parser reads IPv4 in the forms the
/// system resolver takes as well (`127.1`, `0x7f.0.0.1`, `2130706433`). It reads no IPv6 zone
/// (`fe80::1%eth0`), nor a user or a port in the host.
pub(crate) fn host_is_loopback(host: &str) -> Option<bool> {
    if let Ok(ip) = host.parse::<Ipv6Addr>() {
        return Some(is_loopback(&Host::<&str>::Ipv6(ip)));
    }
    Host::parse(host).ok().map(|host| is_loopback(&host))
}

/// `127.0.0.0/8`, `::1` and `localhost`, and what reaches this machine as well: `0.0.0.0` and
/// `::`, IPv4 mapped into IPv6, and the names under `localhost` that some resolvers map to it.
fn is_loopback<S: AsRef<str>>(host: &Host<S>) -> bool {
    let v4 = |ip: Ipv4Addr| ip.is_loopback() || ip.is_unspecified();
    match host {
        Host::Ipv4(ip) => v4(*ip),
        Host::Ipv6(ip) => {
            ip.is_loopback() || ip.is_unspecified() || ip.to_ipv4_mapped().is_some_and(v4)
        }
        Host::Domain(name) => {
            let name = name.as_ref().trim_end_matches('.').to_ascii_lowercase();
            name == "localhost" || name.ends_with(".localhost")
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Mutex};

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

    /// A connection to `host`:`port` with no tunnel of its own, as an automatic one looks without
    /// its mapping.
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
    fn stcp_with_a_visitor_port_outside_the_range_keeps_original_target() {
        // 78925 is 13389 + 65536: a cast to u16 would have found the visitor at 13389.
        for vport in [78925, -1] {
            let conn = connection("c1");
            let mut mapping = tunnel("c1", "stcp", "rdp");
            mapping.visitor_port = Some(vport);
            let resolved = resolve_connection(&conn, &[mapping], &same_ports());
            assert!(resolved.via_tunnel, "{vport}");
            assert_eq!(
                resolved.connection.host.as_deref(),
                Some("server.internal"),
                "{vport}"
            );
            assert_eq!(resolved.connection.port, Some(3389), "{vport}");
        }
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
    fn https_resolves_without_a_running_frpc() {
        // An HTTPS tunnel needs no visitor: the desktop reaches it at its domain.
        let conn = connection("c1");
        let mut mapping = tunnel("c1", "https", "web");
        mapping.custom_domains = Some("a.example.com".to_string());
        let resolved = resolve_connection(&conn, &[mapping], &[]);
        assert!(resolved.via_tunnel);
        assert_eq!(resolved.tunnel_name.as_deref(), Some("tunnel-1"));
        assert_eq!(resolved.tunnel_type.as_deref(), Some("https"));
        assert_eq!(
            json(&resolved.connection),
            json(&Connection {
                url: Some("https://a.example.com".to_string()),
                ..conn.clone()
            })
        );
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
        // A non-admin reads only the mappings of the servers assigned to them; without one, the
        // server's automatic connection names the visitor's server port on loopback. A mapping of
        // another connection changes nothing.
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

    /// The local ports the port map gives the visitors of other workspaces in the tests below.
    const OTHERS: [u16; 2] = [6000, 23010];

    /// The refusal of a target at `port`.
    fn refusal(port: u16) -> String {
        format!(
            "port {port} on this machine belongs to the tunnel of another workspace; start the \
             tunnel of this workspace to connect"
        )
    }

    /// A web connection that opens `url`.
    fn web(url: &str) -> Connection {
        Connection {
            kind: ConnectionKind::Web,
            host: None,
            port: None,
            url: Some(url.to_string()),
            ..connection("web")
        }
    }

    #[test]
    fn foreign_port_on_loopback_without_an_own_binding_is_refused() {
        let ssh = |host: &str, port: u16| literal(ConnectionKind::Ssh, host, port);
        for (case, conn, port) in [
            ("127.0.0.1", ssh("127.0.0.1", 6000), 6000),
            ("127.0.0.0/8", ssh("127.0.0.2", 23010), 23010),
            ("localhost", ssh("localhost", 6000), 6000),
            ("LOCALHOST.", ssh("LOCALHOST.", 6000), 6000),
            ("a name under localhost", ssh("db.localhost", 6000), 6000),
            ("::1", ssh("::1", 6000), 6000),
            ("[::1]", ssh("[::1]", 6000), 6000),
            ("127.1", ssh("127.1", 6000), 6000),
            ("hex", ssh("0x7f.0.0.1", 6000), 6000),
            ("decimal", ssh("2130706433", 6000), 6000),
            ("0.0.0.0", ssh("0.0.0.0", 6000), 6000),
            ("IPv4 mapped", ssh("::ffff:127.0.0.1", 6000), 6000),
            ("padded", ssh(" 127.0.0.1 ", 6000), 6000),
            // ssh takes the host from after the last `@`.
            ("a user in the host", ssh("root@127.0.0.1", 6000), 6000),
            (
                "an IPv6 zone in the user",
                ssh("fe80::1%@127.0.0.1", 6000),
                6000,
            ),
            (
                "rdp, a port in the host",
                literal(ConnectionKind::Rdp, "127.0.0.1:6000", 3389),
                6000,
            ),
            (
                "rdp, a port in the host of an IPv6 address",
                literal(ConnectionKind::Rdp, "[::1]:6000", 3389),
                6000,
            ),
            (
                "rdp, the port field next to a port in the host",
                literal(ConnectionKind::Rdp, "localhost:3390", 23010),
                23010,
            ),
            (
                "rdp",
                literal(ConnectionKind::Rdp, "127.0.0.1", 23010),
                23010,
            ),
            (
                "web without a URL yet",
                literal(ConnectionKind::Web, "127.0.0.1", 6000),
                6000,
            ),
        ] {
            let refused = reject_foreign_port(&conn, &OTHERS, &[]);
            assert_eq!(
                refused.map_err(|e| e.to_string()),
                Err(refusal(port)),
                "{case}"
            );
        }

        // Without a port, the target is at the one `rdp` takes.
        let rdp = Connection {
            port: None,
            ..literal(ConnectionKind::Rdp, "localhost", 3389)
        };
        let refused = reject_foreign_port(&rdp, &[3389], &[]);
        assert_eq!(refused.map_err(|e| e.to_string()), Err(refusal(3389)));
    }

    /// The refusal of a host the check cannot read.
    const UNREAD: &str = "the host of this connection cannot be read and may lead to the tunnel \
                          of another workspace on this machine; write the host as a name or an \
                          address, and the user and the port in their own fields";

    #[test]
    fn foreign_port_in_an_ssh_uri_is_refused() {
        // OpenSSH reads a destination `ssh://` itself; its port counts unless `-p` comes, and
        // `ssh.rs` passes `-p` only for a port other than 22.
        let ssh = |host: &str, port: Option<u16>| Connection {
            port,
            ..literal(ConnectionKind::Ssh, host, 0)
        };
        for (host, port, refused) in [
            ("ssh://127.0.0.1:6000", Some(22), 6000),
            ("ssh://127.0.0.1:6000", None, 6000),
            ("ssh://[127.0.0.1]:6000/", None, 6000),
            ("ssh://127.0.0.1:6000/", None, 6000),
            ("ssh://admin;opt=1@localhost:23010", None, 23010),
            // The user ends at the first `@`.
            ("ssh://server.internal/@127.0.0.1:6000", None, 6000),
            ("ssh://server.internal?@127.0.0.1:6000", None, 6000),
            // `-p` wins.
            ("ssh://127.0.0.1:6001", Some(23010), 23010),
        ] {
            let case = format!("{host} at {port:?}");
            let result = reject_foreign_port(&ssh(host, port), &OTHERS, &[]);
            assert_eq!(
                result.map_err(|e| e.to_string()),
                Err(refusal(refused)),
                "{case}"
            );
        }

        for (host, port) in [
            ("ssh://127.0.0.1:6000", Some(2222)),
            ("ssh://127.0.0.1", None),
            ("ssh://127.0.0.1:", Some(22)),
            ("ssh://server.internal:6000", None),
            ("ssh://127.0.0.1@server.internal:6000", None),
        ] {
            let result = reject_foreign_port(&ssh(host, port), &OTHERS, &[]);
            assert!(result.is_ok(), "{host} at {port:?}");
        }

        for (case, host) in [
            ("a port by service name, x11 is 6000", "ssh://127.0.0.1:x11"),
            ("a path, which ssh refuses", "ssh://127.0.0.1:6000/x"),
            ("upper case, no URI to ssh", "SSH://127.0.0.1:6000"),
        ] {
            let result = reject_foreign_port(&ssh(host, None), &OTHERS, &[]);
            assert_eq!(
                result.map_err(|e| e.to_string()),
                Err(UNREAD.to_string()),
                "{case}"
            );
        }
    }

    #[test]
    fn foreign_port_with_a_host_the_check_cannot_read() {
        // It may name this machine at any port, so every port of another workspace counts.
        let unread = [
            // ssh takes no port from the host; a user `ssh://x` would make it a URI that does.
            literal(ConnectionKind::Ssh, "127.0.0.1:6000", 22),
            // No zone is read, so a link-local address with one is refused as well.
            literal(ConnectionKind::Ssh, "fe80::1%eth0", 22),
            literal(ConnectionKind::Rdp, "127.0.0.1:6000:7000", 3389),
            literal(ConnectionKind::Rdp, "x@127.0.0.1:6000", 3389),
        ];
        for conn in &unread {
            let result = reject_foreign_port(conn, &OTHERS, &[]);
            assert_eq!(
                result.map_err(|e| e.to_string()),
                Err(UNREAD.to_string()),
                "{conn:?}"
            );
            assert!(reject_foreign_port(conn, &[], &[]).is_ok(), "{conn:?}");
        }
    }

    #[test]
    fn foreign_port_an_own_visitor_listens_on_is_allowed() {
        let target = literal(ConnectionKind::Ssh, "127.0.0.1", 6000);
        let own = [binding("db-visitor", 6000, 6000)];
        assert!(reject_foreign_port(&target, &OTHERS, &own).is_ok());
        assert!(reject_foreign_port(&web("http://localhost:6000"), &OTHERS, &own).is_ok());

        // An own visitor at another local port leaves 6000 to the other workspace.
        let elsewhere = [binding("db-visitor", 6000, 23005)];
        assert!(reject_foreign_port(&target, &OTHERS, &elsewhere).is_err());
        // Resolved through that visitor, the target is its local port.
        let resolved = resolve_connection(&target, &[], &elsewhere).connection;
        assert!(reject_foreign_port(&resolved, &OTHERS, &elsewhere).is_ok());
    }

    #[test]
    fn foreign_port_on_another_host_is_allowed() {
        for (case, conn) in [
            (
                "a name",
                literal(ConnectionKind::Ssh, "server.internal", 6000),
            ),
            (
                "an address",
                literal(ConnectionKind::Rdp, "192.0.2.10", 23010),
            ),
            (
                "a user in the host",
                literal(ConnectionKind::Ssh, "root@server.example.com", 6000),
            ),
            (
                "loopback as the user in the host",
                literal(ConnectionKind::Ssh, "127.0.0.1@server.example.com", 6000),
            ),
            (
                "rdp, a port in the host",
                literal(ConnectionKind::Rdp, "server:3390", 3389),
            ),
            (
                "rdp, a foreign port in the host of another machine",
                literal(ConnectionKind::Rdp, "192.0.2.10:6000", 3389),
            ),
            (
                "a name that starts like loopback",
                literal(ConnectionKind::Ssh, "127.0.0.1.example.com", 6000),
            ),
            (
                "a name that starts like localhost",
                literal(ConnectionKind::Ssh, "localhost.example.com", 6000),
            ),
            ("a web URL", web("https://server.internal:6000/")),
            (
                "loopback only as the user of a web URL",
                web("http://127.0.0.1@server.internal:6000/"),
            ),
            (
                "loopback in the URL of a connection that is no web one",
                Connection {
                    url: Some("http://127.0.0.1:6000".to_string()),
                    ..literal(ConnectionKind::Ssh, "server.internal", 6000)
                },
            ),
        ] {
            assert!(reject_foreign_port(&conn, &OTHERS, &[]).is_ok(), "{case}");
        }
    }

    #[test]
    fn foreign_port_in_a_web_url_is_refused() {
        for (url, port) in [
            ("http://127.0.0.1:6000", 6000),
            ("https://localhost:6000/path?q=1", 6000),
            ("http://[::1]:23010/", 23010),
            ("http://127.1:6000", 6000),
            // The browser gets it as https://127.0.0.1:6000.
            ("127.0.0.1:6000", 6000),
        ] {
            let refused = reject_foreign_port(&web(url), &OTHERS, &[]);
            assert_eq!(
                refused.map_err(|e| e.to_string()),
                Err(refusal(port)),
                "{url}"
            );
        }
        // Next to a host of its own that is no loopback.
        let both = Connection {
            host: Some("server.internal".to_string()),
            port: Some(443),
            ..web("http://127.0.0.1:6000")
        };
        assert!(reject_foreign_port(&both, &OTHERS, &[]).is_err());
    }

    #[test]
    fn foreign_port_without_an_entry_is_allowed() {
        let targets = [
            literal(ConnectionKind::Ssh, "127.0.0.1", 6000),
            literal(ConnectionKind::Rdp, "localhost", 23010),
            web("http://127.0.0.1:6000"),
        ];
        for conn in &targets {
            assert!(reject_foreign_port(conn, &[], &[]).is_ok(), "{conn:?}");
        }
        // A loopback port of no other workspace.
        let free = literal(ConnectionKind::Ssh, "127.0.0.1", 6001);
        assert!(reject_foreign_port(&free, &OTHERS, &[]).is_ok());
        assert!(reject_foreign_port(&web("http://127.0.0.1"), &OTHERS, &[]).is_ok());
    }

    /// Serve HTTP on a fresh loopback port, one request per connection: the n-th request gets
    /// the n-th of `replies` (status line and body); `None`, like any request after them, sees
    /// its connection closed unanswered. The request line of every request lands in the log.
    async fn serve(
        replies: Vec<Option<(&'static str, String)>>,
    ) -> (String, Arc<Mutex<Vec<String>>>) {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://127.0.0.1:{}", listener.local_addr().unwrap().port());
        let log = Arc::new(Mutex::new(Vec::new()));
        let seen = Arc::clone(&log);
        tokio::spawn(async move {
            let mut replies = replies.into_iter();
            loop {
                let (mut tcp, _) = listener.accept().await.unwrap();
                let mut head = Vec::new();
                let mut buf = [0u8; 1024];
                while !head.windows(4).any(|w| w == b"\r\n\r\n") {
                    let n = tcp.read(&mut buf).await.unwrap();
                    if n == 0 {
                        break;
                    }
                    head.extend_from_slice(&buf[..n]);
                }
                let head = String::from_utf8_lossy(&head);
                seen.lock()
                    .unwrap()
                    .push(head.lines().next().unwrap_or_default().to_string());
                if let Some((status, body)) = replies.next().flatten() {
                    let reply = format!(
                        "HTTP/1.1 {status}\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
                        body.len()
                    );
                    tcp.write_all(reply.as_bytes()).await.unwrap();
                }
                let _ = tcp.shutdown().await;
            }
        });
        (url, log)
    }

    /// A session of `ops-admin` on `server`.
    async fn signed_in(server: String) -> SessionState {
        let session = SessionState::default();
        session
            .set(
                server,
                "access".to_string(),
                "refresh".to_string(),
                "ops-admin".to_string(),
                false,
            )
            .await;
        session
    }

    /// The mappings the session holds, as JSON.
    async fn held(session: &SessionState) -> serde_json::Value {
        serde_json::to_value(&*session.tunnels().await).unwrap()
    }

    /// The mappings the server lists first in the tests below.
    fn listed() -> serde_json::Value {
        serde_json::to_value([tunnel("c1", "stcp", "rdp")]).unwrap()
    }

    const FETCH: &str = "GET /api/frp/tunnels HTTP/1.1";

    #[tokio::test]
    async fn fetch_tunnels_failing_on_the_server_or_the_network_keeps_the_last_mappings() {
        for (case, failure) in [
            ("500", Some(("500 Internal Server Error", String::new()))),
            ("503", Some(("503 Service Unavailable", String::new()))),
            ("connection closed unanswered", None),
        ] {
            let (server, log) = serve(vec![Some(("200 OK", listed().to_string())), failure]).await;
            let session = signed_in(server).await;

            let fetched = fetch_tunnels(&session).await.unwrap();
            assert_eq!(serde_json::to_value(&fetched).unwrap(), listed(), "{case}");
            assert_eq!(held(&session).await, listed(), "{case}");

            // A fetch that fails on the way leaves the mappings of the last one.
            assert!(fetch_tunnels(&session).await.is_err(), "{case}");
            assert_eq!(held(&session).await, listed(), "{case}");
            assert_eq!(*log.lock().unwrap(), [FETCH, FETCH], "{case}");
        }
    }

    #[tokio::test]
    async fn fetch_tunnels_takes_mappings_with_ports_outside_the_range() {
        let mut far = serde_json::to_value(tunnel("c2", "stcp", "rdp")).unwrap();
        far["id"] = "t-far".into();
        far["localPort"] = 70000.into();
        far["visitorPort"] = 70000.into();
        let mut low = serde_json::to_value(tunnel("c3", "stcp", "ssh")).unwrap();
        low["id"] = "t-low".into();
        low["localPort"] = (-1).into();
        low["visitorPort"] = 0.into();
        let listed = serde_json::json!([tunnel("c1", "stcp", "rdp"), far, low]);
        let (server, _) = serve(vec![Some(("200 OK", listed.to_string()))]).await;
        let session = signed_in(server).await;

        let fetched = fetch_tunnels(&session).await.unwrap();
        assert_eq!(serde_json::to_value(&fetched).unwrap(), listed);
        assert_eq!(held(&session).await, listed);
    }

    #[tokio::test]
    async fn fetch_tunnels_refused_drops_the_mappings_in_the_session() {
        let renewed = r#"{"access_token":"renewed","refresh_token":"refresh-2"}"#;
        for (case, refusal, requests) in [
            (
                "403",
                vec![Some(("403 Forbidden", String::new()))],
                vec![FETCH, FETCH],
            ),
            (
                "401 after a renewal",
                vec![
                    Some(("401 Unauthorized", String::new())),
                    Some(("200 OK", renewed.to_string())),
                    Some(("401 Unauthorized", String::new())),
                ],
                vec![FETCH, FETCH, "POST /api/auth/refresh HTTP/1.1", FETCH],
            ),
        ] {
            let mut replies = vec![Some(("200 OK", listed().to_string()))];
            replies.extend(refusal);
            let (server, log) = serve(replies).await;
            let session = signed_in(server).await;

            fetch_tunnels(&session).await.unwrap();
            assert_eq!(held(&session).await, listed(), "{case}");

            assert!(fetch_tunnels(&session).await.is_err(), "{case}");
            assert_eq!(held(&session).await, serde_json::json!([]), "{case}");
            assert_eq!(*log.lock().unwrap(), requests, "{case}");
            // The refusal drops the mappings, not the session.
            assert!(session.current().await.is_some(), "{case}");
        }
    }
}
