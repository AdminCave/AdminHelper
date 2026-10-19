// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use crate::error::AppError;
use crate::models::Connection;
use crate::session::SessionState;
use crate::storage::write_connections;
use crate::validation::{same_server_destination, sanitize_synced_connections, validate_https_url};

pub async fn sync_connections(
    app: tauri::AppHandle,
    url: String,
    allow_self_signed: bool,
    server_url: Option<String>,
) -> Result<Vec<Connection>, AppError> {
    validate_https_url(&url)?;
    // https-only is enforced above. On an enrolled device the client with the
    // identity pins the enrollment CA; a client without it (or on a device that
    // isn't enrolled) pins on first use (TOFU) when self-signed certificates are
    // allowed and checks the public CA otherwise. The device identity is for the
    // user's own server only: with it, any other host fails the enrollment CA pin
    // (ERR_CA_PIN_MISMATCH).
    let client = if sync_uses_identity(&url, server_url.as_deref()) {
        crate::http_client::build_client(&url, allow_self_signed)?
    } else {
        crate::http_client::build_client_without_identity(&url, allow_self_signed)?
    };
    let response = client.get(&url).send().await?.error_for_status()?;
    // Parse leniently like fetch_connections_jwt: the server list may hold kinds
    // the launcher can't open (or malformed rows) — skip those instead of failing
    // the whole sync by strict-decoding the batch into Vec<Connection>.
    let raw: Vec<serde_json::Value> = response.json().await?;
    let connections = sanitize_synced_connections(parse_launchable_connections(raw));
    write_connections(&app, &connections)?;
    Ok(connections)
}

/// Whether a sync from `sync_url` presents the device identity: only when it has
/// the origin (scheme, host, port) of the stored `serverUrl`, the same comparison
/// that pins the JWT to the logged-in server. No `serverUrl`, no identity.
fn sync_uses_identity(sync_url: &str, server_url: Option<&str>) -> bool {
    server_url.is_some_and(|server| same_server_destination(sync_url, server))
}

/// The desktop launcher only understands ssh/rdp/web connections, the only kinds
/// the server accepts too (connections/schemas.py); a list from a sync URL may
/// still hold others, or a malformed row. Parse leniently so a single unsupported
/// entry can't fail the whole fetch: keep the kinds we can launch and skip the
/// rest. serverId rides along via the Connection struct.
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
    session: &SessionState,
) -> Result<Vec<Connection>, AppError> {
    let connections = fetch_server_connections(session).await?;
    write_connections(&app, &connections)?;
    Ok(connections)
}

/// The launchable connections of the signed-in user. A list that arrives after its user
/// signed out, or after someone else signed in, is refused: it must not replace the
/// connections of the session that is there now.
async fn fetch_server_connections(session: &SessionState) -> Result<Vec<Connection>, AppError> {
    let (response, user) = crate::auth::authenticated_get(session, "/api/connections").await?;
    let raw: Vec<serde_json::Value> = response.error_for_status()?.json().await?;
    session.ensure_signed_in(&user).await?;
    Ok(sanitize_synced_connections(parse_launchable_connections(
        raw,
    )))
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

    #[test]
    fn sync_identity_same_origin_as_the_server_url() {
        // Default port, host case and a trailing slash don't change the origin; path and query
        // never count.
        let server = Some("https://ah.example");
        for sync_url in [
            "https://ah.example/api/connections?api_key=k",
            "https://ah.example:443/api/connections",
            "https://AH.Example/api/connections",
            "https://ah.example/",
        ] {
            assert!(
                sync_uses_identity(sync_url, server),
                "{sync_url} must use the identity"
            );
        }
        assert!(sync_uses_identity(
            "https://ah.example:8443/api/connections",
            Some("https://AH.example:8443/")
        ));
    }

    #[test]
    fn sync_identity_foreign_origin_goes_without() {
        let server = Some("https://ah.example:8443");
        for sync_url in [
            "https://other.example:8443/connections.json", // host
            "https://ah.example/connections.json",         // port (443)
            "https://ah.example:9443/connections.json",    // port
            "https://ah.example.other.test:8443/x",        // suffix trick
        ] {
            assert!(
                !sync_uses_identity(sync_url, server),
                "{sync_url} must go without the identity"
            );
        }
        // Scheme: a loopback server URL may be http, the sync URL is always https.
        assert!(!sync_uses_identity(
            "https://localhost:8443/connections.json",
            Some("http://localhost:8443")
        ));
    }

    #[test]
    fn sync_identity_without_server_url_goes_without() {
        assert!(!sync_uses_identity(
            "https://ah.example/api/connections",
            None
        ));
        assert!(!sync_uses_identity(
            "https://ah.example/api/connections",
            Some("")
        ));
    }

    #[tokio::test]
    async fn connections_of_a_session_gone_meanwhile_are_refused() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};

        // Who signs in while the list is on its way; `None` signs out.
        for next in [Some("ops-admin"), Some("someone-else"), None] {
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let server = format!("http://127.0.0.1:{}", listener.local_addr().unwrap().port());
            let session = SessionState::default();
            session
                .set(
                    server.clone(),
                    "access".to_string(),
                    "refresh".to_string(),
                    "ops-admin".to_string(),
                    false,
                )
                .await;

            let serve = async {
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
                match next {
                    Some(user) => {
                        session
                            .set(
                                server.clone(),
                                "next".to_string(),
                                "next-refresh".to_string(),
                                user.to_string(),
                                false,
                            )
                            .await
                    }
                    None => drop(session.take().await),
                }
                let body = r#"[{"id":"1","name":"a","kind":"ssh","host":"srv.example"}]"#;
                let reply = format!(
                    "HTTP/1.1 200 OK\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
                    body.len()
                );
                tcp.write_all(reply.as_bytes()).await.unwrap();
                let _ = tcp.shutdown().await;
            };
            let (fetched, ()) = tokio::join!(fetch_server_connections(&session), serve);

            match next {
                // The same user signed in again: the connections are still theirs.
                Some("ops-admin") => {
                    let ids: Vec<String> = fetched
                        .expect("the connections")
                        .into_iter()
                        .map(|c| c.id)
                        .collect();
                    assert_eq!(ids, ["1"]);
                }
                _ => assert!(fetched.is_err(), "{next:?}"),
            }
        }
    }
}
