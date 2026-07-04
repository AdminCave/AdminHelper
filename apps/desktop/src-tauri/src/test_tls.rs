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
use tokio::net::TcpListener;
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

/// GET https://127.0.0.1:{port}/ with a 5s timeout, returning the status or Err on
/// any failure. Connects by IP so a server cert's "localhost" SAN is not relied on.
pub async fn get(client: &reqwest::Client, port: u16) -> Result<reqwest::StatusCode, ()> {
    let url = format!("https://127.0.0.1:{port}/");
    match tokio::time::timeout(Duration::from_secs(5), client.get(url).send()).await {
        Ok(Ok(resp)) => Ok(resp.status()),
        _ => Err(()),
    }
}
