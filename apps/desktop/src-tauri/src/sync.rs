// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use url::Url;

use crate::error::AppError;
use crate::models::Connection;
use crate::storage::write_connections;
use crate::validation::sanitize_synced_connections;

fn validate_https_url(raw: &str) -> Result<(), AppError> {
    let url = Url::parse(raw)?;
    if url.scheme() != "https" {
        return Err(AppError::Validation(
            "Nur https:// URLs sind erlaubt".to_string(),
        ));
    }
    Ok(())
}

pub async fn sync_connections(
    app: tauri::AppHandle,
    url: String,
    allow_self_signed: bool,
) -> Result<Vec<Connection>, AppError> {
    validate_https_url(&url)?;
    // Same TOFU-pinning client as the authenticated paths (https-only is enforced
    // above; build_client adds the pinning on the self-signed path).
    let client = crate::auth::build_client(&url, allow_self_signed)?;
    let response = client.get(&url).send().await?.error_for_status()?;
    // Parse leniently like fetch_connections_jwt: the server list may hold kinds
    // the launcher can't open (or malformed rows) — skip those instead of failing
    // the whole sync by strict-decoding the batch into Vec<Connection>.
    let raw: Vec<serde_json::Value> = response.json().await?;
    let connections = sanitize_synced_connections(parse_launchable_connections(raw));
    write_connections(&app, &connections)?;
    Ok(connections)
}

/// The desktop launcher only understands ssh/rdp/web connections; the server may
/// also hold vnc/custom ones (managed in the infrastructure hub). Parse leniently
/// so a single unsupported entry can't fail the whole fetch: keep the kinds we can
/// launch and skip the rest. serverId rides along via the Connection struct.
fn parse_launchable_connections(raw: Vec<serde_json::Value>) -> Vec<Connection> {
    raw.into_iter()
        .filter(|v| {
            matches!(
                v.get("kind").and_then(|k| k.as_str()),
                Some("ssh") | Some("rdp") | Some("web")
            )
        })
        .filter_map(|v| serde_json::from_value::<Connection>(v).ok())
        .collect()
}

pub async fn fetch_connections_jwt(
    app: tauri::AppHandle,
    server_url: &str,
    token: &str,
    allow_self_signed: bool,
) -> Result<Vec<Connection>, AppError> {
    let response =
        crate::auth::authenticated_get(server_url, token, "/api/connections", allow_self_signed)
            .await?
            .error_for_status()?;
    let raw: Vec<serde_json::Value> = response.json().await?;
    let connections = sanitize_synced_connections(parse_launchable_connections(raw));
    write_connections(&app, &connections)?;
    Ok(connections)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn keeps_launchable_kinds_and_skips_vnc_custom() {
        let raw = vec![
            json!({"id": "1", "name": "a", "kind": "ssh", "host": "h"}),
            json!({"id": "2", "name": "b", "kind": "vnc", "host": "h"}),
            json!({"id": "3", "name": "c", "kind": "custom", "host": "h"}),
            json!({"id": "4", "name": "d", "kind": "web", "url": "https://x"}),
        ];
        let ids: Vec<String> = parse_launchable_connections(raw)
            .into_iter()
            .map(|c| c.id)
            .collect();
        assert_eq!(ids, vec!["1".to_string(), "4".to_string()]);
    }

    #[test]
    fn preserves_server_id() {
        let raw = vec![json!({"id": "1", "name": "a", "kind": "ssh", "serverId": "srv-9"})];
        let out = parse_launchable_connections(raw);
        assert_eq!(out[0].server_id.as_deref(), Some("srv-9"));
    }

    #[test]
    fn skips_malformed_entries_without_failing_the_batch() {
        let raw = vec![
            json!({"id": "1", "name": "a", "kind": "ssh"}),
            json!({"kind": "ssh"}), // missing required id/name -> skipped, not fatal
        ];
        assert_eq!(parse_launchable_connections(raw).len(), 1);
    }
}
