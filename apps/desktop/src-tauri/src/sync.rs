// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use crate::error::AppError;
use crate::models::Connection;
use crate::session::SessionState;
use crate::storage::write_connections;
use crate::validation::{sanitize_synced_connections, validate_https_url};

pub async fn sync_connections(
    app: tauri::AppHandle,
    url: String,
    allow_self_signed: bool,
) -> Result<Vec<Connection>, AppError> {
    let connections = fetch(&url, allow_self_signed).await?;
    write_connections(&app, &connections)?;
    Ok(connections)
}

/// The launchable connections at the sync source `url`.
async fn fetch(url: &str, allow_self_signed: bool) -> Result<Vec<Connection>, AppError> {
    validate_https_url(url)?;
    // https-only is enforced above. A sync runs only in a sync workspace, from the
    // source it keeps (`workspace::sync_url`); such a workspace has no server, and
    // the device identity is for the server of a workspace only. The fetch never
    // presents it: it goes like a device that isn't enrolled, pinning on first use
    // (TOFU) when self-signed certificates are allowed and checking the public CA
    // otherwise.
    let client = crate::http_client::build_client_without_identity(url, allow_self_signed)?;
    let response = client.get(url).send().await?.error_for_status()?;
    // Parse leniently like fetch_connections_jwt: the server list may hold kinds
    // the launcher can't open (or malformed rows) — skip those instead of failing
    // the whole sync by strict-decoding the batch into Vec<Connection>.
    let raw = read_list(response).await?;
    Ok(sanitize_synced_connections(parse_launchable_connections(
        raw,
    )))
}

/// The most of a connection list a fetch reads, the same bound as a playbook answer
/// (`ansible.rs`).
const MAX_LIST_BYTES: usize = 16 * 1024 * 1024;

/// The JSON list in `response`. An answer over [`MAX_LIST_BYTES`] is refused by its declared
/// length before any of the body is read, else as soon as more has arrived; no error quotes
/// the answer.
async fn read_list(mut response: reqwest::Response) -> Result<Vec<serde_json::Value>, AppError> {
    let too_large = || {
        AppError::Validation(format!(
            "the connection list could not be loaded (answer larger than {} MiB)",
            MAX_LIST_BYTES / (1024 * 1024)
        ))
    };
    if response
        .content_length()
        .is_some_and(|length| length > MAX_LIST_BYTES as u64)
    {
        return Err(too_large());
    }
    let mut body = Vec::new();
    while let Some(chunk) = response.chunk().await? {
        if body.len() + chunk.len() > MAX_LIST_BYTES {
            return Err(too_large());
        }
        body.extend_from_slice(&chunk);
    }
    serde_json::from_slice(&body).map_err(|_| {
        AppError::Validation(
            "the connection list could not be loaded (unexpected answer)".to_string(),
        )
    })
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
/// connections of the session that is there now. The session keeps the list for the check of
/// a stored password ([`SessionState::keep_connections`]); a refusal (401, 403) drops the last
/// one, a fetch that fails otherwise (network, server error) leaves it.
async fn fetch_server_connections(session: &SessionState) -> Result<Vec<Connection>, AppError> {
    let (response, user) = crate::auth::authenticated_get(session, "/api/connections").await?;
    if matches!(
        response.status(),
        reqwest::StatusCode::UNAUTHORIZED | reqwest::StatusCode::FORBIDDEN
    ) {
        // None of the last ones count any more. A session gone meanwhile has none left to drop.
        let _ = session.keep_connections(&user, Vec::new()).await;
    }
    let raw = read_list(response.error_for_status()?).await?;
    let connections = sanitize_synced_connections(parse_launchable_connections(raw));
    session.keep_connections(&user, connections.clone()).await?;
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

    #[tokio::test]
    async fn sync_fetch_goes_without_the_device_identity() {
        // An enrolled identity that can't build an mTLS client: a fetch that wanted it would
        // fail on loading it before any connection; one without it reaches the network.
        let _keyring = crate::keyring_store::memory();
        let _standard = crate::workspace::enter(crate::workspace::Workspace {
            id: crate::workspace::WorkspaceId::parse("standard").unwrap(),
            name: "Standard".to_string(),
            legacy_keys: true,
        });
        for key in ["enroll|key", "enroll|cert", "enroll|ca"] {
            crate::keyring_store::set(key, "not a pem").unwrap();
        }
        assert!(crate::enrollment::is_enrolled());
        // Held, not freed: nobody answers at the sync source.
        let (_reserved, port) = crate::test_tls::refused_port();
        let url = format!("https://127.0.0.1:{port}/c.json");

        for allow_self_signed in [false, true] {
            let fetched = fetch(&url, allow_self_signed).await;
            assert!(
                matches!(fetched, Err(AppError::Network(_))),
                "allow_self_signed={allow_self_signed}: {fetched:?}"
            );
        }
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

    /// Serve HTTP on a fresh loopback port, one request per connection: the n-th request gets
    /// the n-th of `replies` (status line and body); `None`, like any request after them, sees
    /// its connection closed unanswered. The request line of every request lands in the log.
    async fn serve(
        replies: Vec<Option<(&'static str, String)>>,
    ) -> (String, std::sync::Arc<std::sync::Mutex<Vec<String>>>) {
        use std::sync::{Arc, Mutex};
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

    /// The ids of the connections the session holds.
    async fn held(session: &SessionState) -> Vec<String> {
        session
            .connections()
            .await
            .iter()
            .map(|c| c.id.clone())
            .collect()
    }

    /// What the server lists first in the tests below: one connection to keep, one the
    /// launcher cannot open.
    const LISTED: &str = r#"[{"id":"1","name":"a","kind":"rdp","host":"rdp.example.com","port":3389},{"id":"2","name":"b","kind":"vnc","host":"h"}]"#;

    const FETCH: &str = "GET /api/connections HTTP/1.1";

    #[tokio::test]
    async fn server_connections_failing_on_the_server_or_the_network_keep_the_last_ones() {
        for (case, failure) in [
            ("500", Some(("500 Internal Server Error", String::new()))),
            ("503", Some(("503 Service Unavailable", String::new()))),
            ("connection closed unanswered", None),
        ] {
            let (server, log) = serve(vec![Some(("200 OK", LISTED.to_string())), failure]).await;
            let session = signed_in(server).await;

            let fetched: Vec<String> = fetch_server_connections(&session)
                .await
                .unwrap()
                .into_iter()
                .map(|c| c.id)
                .collect();
            assert_eq!(fetched, ["1"], "{case}");
            // The session holds what the webview got.
            assert_eq!(held(&session).await, ["1"], "{case}");

            assert!(fetch_server_connections(&session).await.is_err(), "{case}");
            assert_eq!(held(&session).await, ["1"], "{case}");
            assert_eq!(*log.lock().unwrap(), [FETCH, FETCH], "{case}");
        }
    }

    #[tokio::test]
    async fn server_connections_over_the_bound_are_refused_and_keep_the_last_ones() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};

        // A list one byte over the bound: a JSON array of one string.
        let oversized = format!("[\"{}\"]", "x".repeat(MAX_LIST_BYTES - 3));
        assert_eq!(oversized.len(), MAX_LIST_BYTES + 1);

        // Declared by its length: refused before the body is read.
        let (server, _log) = serve(vec![
            Some(("200 OK", LISTED.to_string())),
            Some(("200 OK", oversized.clone())),
        ])
        .await;
        let session = signed_in(server).await;
        fetch_server_connections(&session).await.unwrap();
        let refused = fetch_server_connections(&session).await.unwrap_err();
        assert!(
            refused.to_string().contains("larger than 16 MiB"),
            "{refused}"
        );
        assert!(!refused.to_string().contains("xxxx"), "{refused}");
        assert_eq!(held(&session).await, ["1"]);

        // Without a declared length (read until the connection closes): refused while reading.
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let server = format!("http://127.0.0.1:{}", listener.local_addr().unwrap().port());
        let session = signed_in(server).await;
        let serve_list_then_unsized = async {
            for without_length in [false, true] {
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
                let reply = if without_length {
                    format!("HTTP/1.1 200 OK\r\nconnection: close\r\n\r\n{oversized}")
                } else {
                    format!(
                        "HTTP/1.1 200 OK\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{LISTED}",
                        LISTED.len()
                    )
                };
                // The client may stop reading and close first.
                let _ = tcp.write_all(reply.as_bytes()).await;
                let _ = tcp.shutdown().await;
            }
        };
        let fetch_twice = async {
            fetch_server_connections(&session).await.unwrap();
            fetch_server_connections(&session).await
        };
        let (fetched, ()) = tokio::join!(fetch_twice, serve_list_then_unsized);
        let refused = fetched.unwrap_err();
        assert!(
            refused.to_string().contains("larger than 16 MiB"),
            "{refused}"
        );
        assert_eq!(held(&session).await, ["1"]);
    }

    #[tokio::test]
    async fn server_connections_that_are_no_list_are_refused_without_quoting_the_answer() {
        let (server, _log) = serve(vec![
            Some(("200 OK", LISTED.to_string())),
            Some(("200 OK", r#""answer-text-of-the-server""#.to_string())),
        ])
        .await;
        let session = signed_in(server).await;
        fetch_server_connections(&session).await.unwrap();

        let refused = fetch_server_connections(&session).await.unwrap_err();
        assert!(
            refused.to_string().contains("unexpected answer"),
            "{refused}"
        );
        assert!(!refused.to_string().contains("answer-text"), "{refused}");
        assert_eq!(held(&session).await, ["1"]);
    }

    #[tokio::test]
    async fn server_connections_refused_drop_the_ones_in_the_session() {
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
            let mut replies = vec![Some(("200 OK", LISTED.to_string()))];
            replies.extend(refusal);
            let (server, log) = serve(replies).await;
            let session = signed_in(server).await;

            fetch_server_connections(&session).await.unwrap();
            assert_eq!(held(&session).await, ["1"], "{case}");

            assert!(fetch_server_connections(&session).await.is_err(), "{case}");
            assert_eq!(held(&session).await, Vec::<String>::new(), "{case}");
            assert_eq!(*log.lock().unwrap(), requests, "{case}");
            // The refusal drops the connections, not the session.
            assert!(session.current().await.is_some(), "{case}");
        }
    }
}
