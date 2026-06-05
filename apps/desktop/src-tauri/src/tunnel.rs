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
