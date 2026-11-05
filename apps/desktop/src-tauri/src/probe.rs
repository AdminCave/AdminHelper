// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::time::{Duration, Instant};

use futures_util::stream::{self, StreamExt};
use serde::Deserialize;
use tokio::net::{lookup_host, TcpStream};
use tokio::time::timeout;

use crate::error::AppError;

const TIMEOUT: Duration = Duration::from_millis(1500);
const CONCURRENCY: usize = 16;
const MAX_TARGETS: usize = 256;

#[derive(Debug, Clone, Deserialize)]
pub struct ProbeTarget {
    pub host: String,
    pub port: u16,
}

/// TCP connect time in milliseconds per target, in input order; `None` when the
/// target did not accept within the time limit (name resolution included).
pub async fn probe_all(targets: Vec<ProbeTarget>) -> Result<Vec<Option<u64>>, AppError> {
    if targets.len() > MAX_TARGETS {
        return Err(AppError::Validation(format!(
            "too many probe targets: {} (at most {MAX_TARGETS})",
            targets.len()
        )));
    }
    if let Some(t) = targets.iter().find(|t| t.port == 0) {
        return Err(AppError::Validation(format!(
            "invalid port 0 for probe target {}",
            t.host
        )));
    }
    Ok(stream::iter(targets)
        .map(|t| async move {
            timeout(TIMEOUT, probe_one(&t.host, t.port))
                .await
                .ok()
                .flatten()
        })
        .buffered(CONCURRENCY)
        .collect()
        .await)
}

// Only the connect itself is timed, so a slow first DNS answer does not show up as latency.
async fn probe_one(host: &str, port: u16) -> Option<u64> {
    let addrs = lookup_host((host, port)).await.ok()?;
    for addr in addrs {
        let started = Instant::now();
        if TcpStream::connect(addr).await.is_ok() {
            return Some(started.elapsed().as_millis() as u64);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::net::TcpListener;

    fn target(host: &str, port: u16) -> ProbeTarget {
        ProbeTarget {
            host: host.to_string(),
            port,
        }
    }

    #[tokio::test]
    async fn probe_reports_a_listening_port_and_null_for_a_closed_one() {
        let open = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let open_port = open.local_addr().unwrap().port();
        let closed = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let closed_port = closed.local_addr().unwrap().port();
        drop(closed);

        let got = probe_all(vec![
            target("127.0.0.1", open_port),
            target("127.0.0.1", closed_port),
        ])
        .await
        .unwrap();
        assert_eq!(got.len(), 2);
        assert!(
            got[0].is_some(),
            "listening port must report a latency: {got:?}"
        );
        assert_eq!(got[1], None);
    }

    #[tokio::test]
    async fn probe_rejects_more_than_256_targets() {
        let ok = probe_all(vec![target("127.0.0.1", 9); MAX_TARGETS + 1]).await;
        assert!(matches!(ok, Err(AppError::Validation(_))), "{ok:?}");
    }

    #[tokio::test]
    async fn probe_rejects_port_zero() {
        let got = probe_all(vec![target("127.0.0.1", 0)]).await;
        assert!(matches!(got, Err(AppError::Validation(_))), "{got:?}");
    }

    #[tokio::test]
    async fn probe_returns_nothing_for_no_targets() {
        assert_eq!(probe_all(vec![]).await.unwrap(), Vec::<Option<u64>>::new());
    }
}
