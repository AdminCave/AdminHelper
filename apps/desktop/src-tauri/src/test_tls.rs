// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! In-process TLS test harness shared by the enrollment and tofu security tests,
//! so both exercise the same test server instead of drifting copies (2.82). The
//! per-test `server_config` stays local to each module — they differ (tofu has no
//! client auth, enrollment pins an mTLS client verifier).

use std::sync::Arc;
use std::time::Duration;

use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpSocket};
use tokio_rustls::TlsAcceptor;

/// Accept exactly one TLS connection, answer a minimal HTTP/1.1 200, and stay
/// tolerant of a client that aborts mid-handshake (the reject case).
pub async fn serve_once(listener: TcpListener, config: Arc<rustls::ServerConfig>) {
    let acceptor = TlsAcceptor::from(config);
    if let Ok((tcp, _)) = listener.accept().await {
        if let Ok(mut tls) = acceptor.accept(tcp).await {
            let mut buf = [0u8; 1024];
            let _ = tls.read(&mut buf).await;
            let _ = tls
                .write_all(b"HTTP/1.1 200 OK\r\ncontent-length: 0\r\nconnection: close\r\n\r\n")
                .await;
            let _ = tls.flush().await;
            let _ = tls.shutdown().await;
        }
    }
}

/// A port nobody listens on, held while the returned socket lives. A listener bound
/// and dropped frees its port, and a parallel test's `bind(0)` can be handed it: the
/// "refused" test then reaches that test's `serve_once` and takes its one connection.
/// This socket is bound without SO_REUSEADDR and never listens, so no other bind
/// gets the port and a connect to it is refused.
pub fn refused_port() -> (TcpSocket, u16) {
    let socket = TcpSocket::new_v4().unwrap();
    socket.bind("127.0.0.1:0".parse().unwrap()).unwrap();
    let port = socket.local_addr().unwrap().port();
    (socket, port)
}

/// GET https://127.0.0.1:{port}/ with a 5s timeout, returning the status or Err on
/// any failure. Connects by IP so a server cert's "localhost" SAN is not relied on.
pub async fn get(client: &reqwest::Client, port: u16) -> Result<reqwest::StatusCode, ()> {
    let url = format!("https://127.0.0.1:{port}/");
    match tokio::time::timeout(Duration::from_secs(5), client.get(url).send()).await {
        Ok(Ok(resp)) => Ok(resp.status()),
        _ => Err(()),
    }
}

#[tokio::test]
async fn refused_port_is_held_and_refuses_connections() {
    let (_reserved, port) = refused_port();
    let bind = TcpListener::bind(("127.0.0.1", port)).await;
    assert_eq!(
        bind.err().map(|e| e.kind()),
        Some(std::io::ErrorKind::AddrInUse),
        "another bind got the held port {port}"
    );
    let connect = tokio::net::TcpStream::connect(("127.0.0.1", port)).await;
    assert_eq!(
        connect.err().map(|e| e.kind()),
        Some(std::io::ErrorKind::ConnectionRefused),
        "a connect to the held port {port} was not refused"
    );
}
