// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! The local session history of a workspace (R-1068): `sessions.json` beside the connections.
//! A server workspace keeps its history on the server; this file serves local and sync ones.

use crate::error::AppError;
use crate::storage::{read_json_or_default, write_json_pretty};
use chrono::{DateTime, Duration, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

/// How long a session is kept, the same as on the server (Kevin 2026-11-03).
const RETENTION_DAYS: i64 = 90;
/// How many sessions of one connection are kept (Kevin 2026-11-03).
const PER_CONNECTION: usize = 50;

/// One connect, in the shape the server's session list has, plus the connection it belongs to.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionEntry {
    pub id: String,
    pub connection_id: String,
    pub device: Option<String>,
    pub started_at: String,
    pub ended_at: Option<String>,
}

#[derive(Debug, Default, Serialize, Deserialize)]
struct SessionFile {
    #[serde(default)]
    sessions: Vec<SessionEntry>,
}

// Two connects of one process would otherwise read the file both before either writes it, and
// one session would be lost.
static FILE_LOCK: Mutex<()> = Mutex::new(());
static COUNTER: AtomicU64 = AtomicU64::new(0);

fn stamp(at: DateTime<Utc>) -> String {
    at.to_rfc3339_opts(SecondsFormat::Millis, true)
}

fn started(entry: &SessionEntry) -> Option<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(&entry.started_at)
        .ok()
        .map(|at| at.with_timezone(&Utc))
}

/// Keeps what is younger than the retention and the newest [`PER_CONNECTION`] of each
/// connection. An entry whose start does not parse goes as well: nothing could show it.
fn prune(sessions: &mut Vec<SessionEntry>, now: DateTime<Utc>) {
    let oldest = now - Duration::days(RETENTION_DAYS);
    sessions.retain(|s| started(s).is_some_and(|at| at >= oldest));
    sessions.sort_by(|a, b| b.started_at.cmp(&a.started_at));
    let mut seen: std::collections::HashMap<String, usize> = std::collections::HashMap::new();
    sessions.retain(|s| {
        let count = seen.entry(s.connection_id.clone()).or_default();
        *count += 1;
        *count <= PER_CONNECTION
    });
}

/// The name this computer goes by, the device of a session: the registration has no name of
/// its own (R-1068, Entscheidung T5).
pub fn device_name() -> Option<String> {
    #[cfg(target_os = "linux")]
    if let Ok(name) = std::fs::read_to_string("/proc/sys/kernel/hostname") {
        let name = name.trim();
        if !name.is_empty() {
            return Some(name.to_string());
        }
    }
    let from_env = std::env::var("COMPUTERNAME").or_else(|_| std::env::var("HOSTNAME"));
    if let Ok(name) = from_env {
        let name = name.trim();
        if !name.is_empty() {
            return Some(name.to_string());
        }
    }
    let output = std::process::Command::new("hostname").output().ok()?;
    let name = String::from_utf8_lossy(&output.stdout).trim().to_string();
    (!name.is_empty()).then_some(name)
}

/// Begins a session of `connection_id` in the history at `path`.
pub fn start_at(
    path: &Path,
    connection_id: &str,
    device: Option<String>,
    now: DateTime<Utc>,
) -> Result<SessionEntry, AppError> {
    let _guard = FILE_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let mut file: SessionFile = read_json_or_default(path)?;
    let entry = SessionEntry {
        id: format!(
            "{:x}-{:x}-{:x}",
            now.timestamp_nanos_opt().unwrap_or_default(),
            std::process::id(),
            COUNTER.fetch_add(1, Ordering::Relaxed)
        ),
        connection_id: connection_id.to_string(),
        device,
        started_at: stamp(now),
        ended_at: None,
    };
    file.sessions.push(entry.clone());
    prune(&mut file.sessions, now);
    write_json_pretty(path, &file)?;
    Ok(entry)
}

/// Ends the session `id`; ending it again keeps the first end, an unknown one is no error (the
/// retention may have taken it while it ran).
pub fn end_at(path: &Path, id: &str, now: DateTime<Utc>) -> Result<(), AppError> {
    let _guard = FILE_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let mut file: SessionFile = read_json_or_default(path)?;
    let Some(entry) = file.sessions.iter_mut().find(|s| s.id == id) else {
        return Ok(());
    };
    if entry.ended_at.is_none() {
        entry.ended_at = Some(stamp(now));
        write_json_pretty(path, &file)?;
    }
    Ok(())
}

/// The newest `limit` sessions of `connection_id` within the retention, newest first.
pub fn list_at(
    path: &Path,
    connection_id: &str,
    limit: usize,
    now: DateTime<Utc>,
) -> Result<Vec<SessionEntry>, AppError> {
    let _guard = FILE_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let mut file: SessionFile = read_json_or_default(path)?;
    prune(&mut file.sessions, now);
    Ok(file
        .sessions
        .into_iter()
        .filter(|s| s.connection_id == connection_id)
        .take(limit)
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn t0() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 11, 5, 10, 0, 0).unwrap()
    }

    /// An empty directory of its own per call, removed when the test ends.
    struct Scratch(std::path::PathBuf);

    impl Scratch {
        fn path(&self) -> &Path {
            &self.0
        }
    }

    impl Drop for Scratch {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn dir() -> Scratch {
        static SEQ: AtomicU64 = AtomicU64::new(0);
        let dir = std::env::temp_dir().join(format!(
            "ah-sessions-{}-{}",
            std::process::id(),
            SEQ.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&dir).unwrap();
        Scratch(dir)
    }

    #[test]
    fn session_start_end_and_list_newest_first() {
        let d = dir();
        let path = d.path().join("sessions.json");
        let a = start_at(&path, "c1", Some("box".into()), t0()).unwrap();
        let b = start_at(&path, "c1", None, t0() + Duration::minutes(5)).unwrap();
        start_at(&path, "c2", None, t0() + Duration::minutes(6)).unwrap();
        assert_ne!(a.id, b.id);

        end_at(&path, &a.id, t0() + Duration::minutes(1)).unwrap();
        // A second end keeps the first one; an unknown id is no error.
        end_at(&path, &a.id, t0() + Duration::minutes(9)).unwrap();
        end_at(&path, "gone", t0()).unwrap();

        let list = list_at(&path, "c1", 5, t0() + Duration::minutes(10)).unwrap();
        assert_eq!(
            list.iter().map(|s| s.id.as_str()).collect::<Vec<_>>(),
            vec![b.id.as_str(), a.id.as_str()]
        );
        assert_eq!(list[1].device.as_deref(), Some("box"));
        assert_eq!(list[1].started_at, "2026-11-05T10:00:00.000Z");
        assert_eq!(
            list[1].ended_at.as_deref(),
            Some("2026-11-05T10:01:00.000Z")
        );
        assert_eq!(list[0].ended_at, None);
        assert_eq!(
            list_at(&path, "c1", 1, t0()).unwrap().len(),
            1,
            "limit is honoured"
        );
        assert!(list_at(&d.path().join("none.json"), "c1", 5, t0())
            .unwrap()
            .is_empty());
    }

    #[test]
    fn session_history_keeps_90_days_and_50_per_connection() {
        let d = dir();
        let path = d.path().join("sessions.json");
        let old = start_at(&path, "c1", None, t0() - Duration::days(91)).unwrap();
        let kept = start_at(&path, "c1", None, t0() - Duration::days(89)).unwrap();
        // The listing hides what aged past the retention since the last write...
        let at_later = t0() + Duration::days(2);
        let ids: Vec<_> = list_at(&path, "c1", 50, at_later)
            .unwrap()
            .into_iter()
            .map(|s| s.id)
            .collect();
        assert!(!ids.contains(&kept.id));
        // ...and the next write removes it from the file.
        for i in 0..55 {
            start_at(&path, "c1", None, t0() + Duration::seconds(i)).unwrap();
        }
        start_at(&path, "c2", None, t0()).unwrap();
        let raw = std::fs::read_to_string(&path).unwrap();
        assert!(!raw.contains(&old.id));
        assert!(!raw.contains(&kept.id), "the 50 newest crowd out the older");
        let c1 = list_at(&path, "c1", 100, t0() + Duration::minutes(1)).unwrap();
        assert_eq!(c1.len(), 50);
        assert_eq!(c1[0].started_at, stamp(t0() + Duration::seconds(54)));
        assert_eq!(list_at(&path, "c2", 100, t0()).unwrap().len(), 1);
    }

    #[test]
    fn session_file_that_does_not_parse_is_an_error_not_an_empty_history() {
        let d = dir();
        let path = d.path().join("sessions.json");
        std::fs::write(&path, "{broken").unwrap();
        assert!(start_at(&path, "c1", None, t0()).is_err());
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "{broken");
    }

    #[test]
    fn session_device_name_is_not_empty() {
        assert!(device_name().is_some_and(|n| !n.trim().is_empty()));
    }
}
