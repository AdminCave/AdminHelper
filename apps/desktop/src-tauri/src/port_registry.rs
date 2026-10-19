// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! The local port every visitor listens on, one map for all AdminHelper processes of the user:
//! `port-registry.json` in the app data dir, read and written under a lock on a file beside it.

use std::fs;
use std::io::{self, Write};
use std::net::{Ipv4Addr, TcpListener};
use std::ops::RangeInclusive;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::error::AppError;

/// The owner of the visitors of this process, until every workspace brings its own (R-0431).
pub const DEFAULT_OWNER: &str = "default";

/// Where a visitor goes whose server port is taken: below the ephemeral ports of Linux
/// (32768-60999) and Windows (49152-65535), outside the server's visitor ports (6000-6999).
pub const FALLBACK_PORTS: RangeInclusive<u16> = 23000..=23999;

const REGISTRY_FILE: &str = "port-registry.json";
const LOCK_FILE: &str = "port-registry.lock";

#[derive(Debug, Default, PartialEq, Serialize, Deserialize)]
struct Registry {
    entries: Vec<Entry>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct Entry {
    owner: String,
    visitor: String,
    server_port: u16,
    local_port: u16,
}

/// The port map in one directory. Keeps nothing in memory: every call reads the file.
#[derive(Clone)]
pub struct PortRegistry {
    dir: PathBuf,
}

impl PortRegistry {
    pub fn new(data_dir: &Path) -> Self {
        Self {
            dir: data_dir.to_path_buf(),
        }
    }

    /// The local port of every visitor `owner` runs, given as (name, server port), in the order
    /// given. A visitor that has an entry keeps its port; with `recheck` only if the port still
    /// binds on `127.0.0.1`, for when no frpc of `owner` runs that would hold it. Any other gets
    /// a port as [`free_port`] picks it. The entries of `owner` for visitors not given go.
    pub fn assign(
        &self,
        owner: &str,
        visitors: &[(String, u16)],
        recheck: bool,
    ) -> Result<Vec<(String, u16)>, AppError> {
        let _lock = self.lock()?;
        let loaded = self.load()?;
        let mut entries: Vec<Entry> = loaded
            .entries
            .iter()
            .filter(|entry| {
                entry.owner != owner || visitors.iter().any(|(name, _)| *name == entry.visitor)
            })
            .cloned()
            .collect();
        let mut assigned = Vec::with_capacity(visitors.len());
        for (name, server_port) in visitors {
            let own = entries
                .iter()
                .position(|entry| entry.owner == owner && entry.visitor == *name);
            let local_port = match own {
                // No bind test without recheck: the visitor's own frpc most likely holds the port.
                Some(i) if !recheck || binds(entries[i].local_port) => {
                    entries[i].server_port = *server_port;
                    entries[i].local_port
                }
                _ => {
                    // Someone else took the port of an entry while no frpc of the owner ran.
                    if let Some(i) = own {
                        entries.remove(i);
                    }
                    let local_port = free_port(&entries, *server_port, &binds)?;
                    entries.push(Entry {
                        owner: owner.to_string(),
                        visitor: name.clone(),
                        server_port: *server_port,
                        local_port,
                    });
                    local_port
                }
            };
            assigned.push((name.clone(), local_port));
        }
        let updated = Registry { entries };
        if updated != loaded {
            self.store(&updated)?;
        }
        Ok(assigned)
    }

    /// Holds the lock of the map until the returned file drops.
    fn lock(&self) -> Result<fs::File, AppError> {
        fs::create_dir_all(&self.dir)?;
        let file = open_private(&self.dir.join(LOCK_FILE), false)?;
        file.lock()?;
        Ok(file)
    }

    /// The map on disk; empty if there is none or it does not parse. Under the lock only.
    fn load(&self) -> Result<Registry, AppError> {
        let bytes = match fs::read(self.dir.join(REGISTRY_FILE)) {
            Ok(bytes) => bytes,
            Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(Registry::default()),
            Err(e) => return Err(e.into()),
        };
        Ok(serde_json::from_slice(&bytes).unwrap_or_else(|e| {
            log::warn!("{REGISTRY_FILE} does not parse, the port map starts empty: {e}");
            Registry::default()
        }))
    }

    /// Replaces the map on disk at once: a crash leaves the old file or the new one. Under the
    /// lock only, which also makes the fixed temp name safe.
    fn store(&self, registry: &Registry) -> Result<(), AppError> {
        let json = serde_json::to_vec_pretty(registry)?;
        let tmp = self.dir.join(format!("{REGISTRY_FILE}.tmp"));
        let mut file = open_private(&tmp, true)?;
        file.write_all(&json)?;
        drop(file);
        fs::rename(&tmp, self.dir.join(REGISTRY_FILE))?;
        Ok(())
    }
}

#[cfg(test)]
impl PortRegistry {
    /// Make the map hold exactly `entries` of `owner`, each (visitor, server port, local port), as
    /// an earlier run would have left it.
    pub fn seed(&self, owner: &str, entries: &[(&str, u16, u16)]) {
        let _lock = self.lock().unwrap();
        let entries = entries
            .iter()
            .map(|&(visitor, server_port, local_port)| Entry {
                owner: owner.to_string(),
                visitor: visitor.to_string(),
                server_port,
                local_port,
            })
            .collect();
        self.store(&Registry { entries }).unwrap();
    }
}

/// The server port if it is 1024 or above, no entry holds it and `binds` says it binds, else the
/// first such port of [`FALLBACK_PORTS`]. No other port leaves here.
fn free_port(
    entries: &[Entry],
    server_port: u16,
    binds: &dyn Fn(u16) -> bool,
) -> Result<u16, AppError> {
    let free = |port: u16| !entries.iter().any(|entry| entry.local_port == port) && binds(port);
    // Below 1024 the desktop would listen on the port of a system service (22, 80, 445, ...)
    // wherever the OS lets a user bind there. Port 0 goes with them: it always binds, the OS
    // picks one.
    (server_port >= 1024)
        .then_some(server_port)
        .into_iter()
        .chain(FALLBACK_PORTS)
        .find(|&port| free(port))
        .ok_or_else(|| {
            AppError::Io(io::Error::new(
                io::ErrorKind::AddrInUse,
                format!(
                    "no free local port for a visitor in {}-{}",
                    FALLBACK_PORTS.start(),
                    FALLBACK_PORTS.end()
                ),
            ))
        })
}

/// Whether a listener can take `port` on `127.0.0.1` right now.
fn binds(port: u16) -> bool {
    TcpListener::bind((Ipv4Addr::LOCALHOST, port)).is_ok()
}

/// Opens `path` to write, created 0600 on Unix; on Windows the user's ACLs of the app data dir
/// apply.
fn open_private(path: &Path, truncate: bool) -> io::Result<fs::File> {
    let mut options = fs::OpenOptions::new();
    options.write(true).create(true).truncate(truncate);
    #[cfg(unix)]
    std::os::unix::fs::OpenOptionsExt::mode(&mut options, 0o600);
    options.open(path)
}

#[cfg(test)]
mod tests {
    use std::cell::RefCell;
    use std::fs;
    use std::net::{Ipv4Addr, TcpListener};
    use std::path::PathBuf;
    use std::time::Duration;

    use super::{AppError, PortRegistry, DEFAULT_OWNER, FALLBACK_PORTS, LOCK_FILE, REGISTRY_FILE};

    /// A fresh directory for one test case under the system temp dir.
    fn scratch_dir(case: &str) -> PathBuf {
        let dir =
            std::env::temp_dir().join(format!("ah-port-registry-{case}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        dir
    }

    /// Distinct ports nothing listens on right now, from the OS rather than fixed numbers. Bound
    /// all at once, so the OS cannot hand out one twice.
    fn free_ports<const N: usize>() -> [u16; N] {
        let listeners: Vec<TcpListener> = (0..N)
            .map(|_| TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap())
            .collect();
        std::array::from_fn(|i| listeners[i].local_addr().unwrap().port())
    }

    fn free_port() -> u16 {
        let [port] = free_ports();
        port
    }

    fn visitor(name: &str, server_port: u16) -> (String, u16) {
        (name.to_string(), server_port)
    }

    #[test]
    fn port_registry_takes_the_server_port_when_it_is_free() {
        let dir = scratch_dir("free");
        let port = free_port();

        let assigned = PortRegistry::new(&dir)
            .assign(DEFAULT_OWNER, &[visitor("ssh", port)], false)
            .unwrap();

        assert_eq!(assigned, [visitor("ssh", port)]);
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn port_registry_falls_back_when_the_server_port_is_bound() {
        let dir = scratch_dir("bound");
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
        let port = listener.local_addr().unwrap().port();

        let assigned = PortRegistry::new(&dir)
            .assign(DEFAULT_OWNER, &[visitor("ssh", port)], false)
            .unwrap();

        let local = assigned[0].1;
        assert_ne!(local, port);
        assert!(
            FALLBACK_PORTS.contains(&local),
            "{local} is no fallback port"
        );
        drop(listener);
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn port_registry_never_takes_server_port_0() {
        // Port 0 always binds: the OS picks one.
        let dir = scratch_dir("zero");

        let assigned = PortRegistry::new(&dir)
            .assign(DEFAULT_OWNER, &[visitor("ssh", 0)], false)
            .unwrap();

        assert!(FALLBACK_PORTS.contains(&assigned[0].1));
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn port_registry_sends_a_server_port_below_1024_to_the_fallback_ports() {
        // Some systems let any user bind there (Windows, Linux with a lowered
        // ip_unprivileged_port_start): the bind test may not decide.
        let tested = RefCell::new(Vec::new());
        let binds = |port: u16| {
            tested.borrow_mut().push(port);
            true
        };
        for port in [0, 1, 22, 80, 445, 1023] {
            tested.borrow_mut().clear();
            assert_eq!(
                super::free_port(&[], port, &binds).unwrap(),
                *FALLBACK_PORTS.start(),
                "{port}"
            );
            assert!(!tested.borrow().contains(&port), "bind-tested {port}");
        }
        assert_eq!(super::free_port(&[], 1024, &binds).unwrap(), 1024);

        let dir = scratch_dir("privileged");
        let assigned = PortRegistry::new(&dir)
            .assign(DEFAULT_OWNER, &[visitor("http", 80)], false)
            .unwrap();
        assert!(FALLBACK_PORTS.contains(&assigned[0].1), "{assigned:?}");
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn port_registry_recheck_moves_an_own_port_someone_else_took() {
        let dir = scratch_dir("recheck");
        let registry = PortRegistry::new(&dir);
        let port = free_port();
        let ssh = [visitor("ssh", port)];
        assert_eq!(registry.assign(DEFAULT_OWNER, &ssh, false).unwrap(), ssh);
        // A recheck keeps a port that still binds.
        assert_eq!(registry.assign(DEFAULT_OWNER, &ssh, true).unwrap(), ssh);

        // No frpc of the owner runs, and someone else takes the port.
        let foreign = TcpListener::bind((Ipv4Addr::LOCALHOST, port)).unwrap();
        // Without a recheck the entry keeps it: its own frpc would hold it.
        assert_eq!(registry.assign(DEFAULT_OWNER, &ssh, false).unwrap(), ssh);
        let moved = registry.assign(DEFAULT_OWNER, &ssh, true).unwrap();
        assert_ne!(moved[0].1, port);
        assert!(FALLBACK_PORTS.contains(&moved[0].1), "{moved:?}");

        // The new port sticks, also once the old one is free again.
        drop(foreign);
        assert_eq!(registry.assign(DEFAULT_OWNER, &ssh, false).unwrap(), moved);
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn port_registry_keeps_a_visitors_port_without_a_bind_test() {
        let dir = scratch_dir("sticky");
        let registry = PortRegistry::new(&dir);
        // Visitor names are whatever the server sends.
        let name = "a \"quoted\"\nname, ü";
        let port = free_port();
        let first = registry
            .assign(DEFAULT_OWNER, &[visitor(name, port)], false)
            .unwrap();
        assert_eq!(first, [visitor(name, port)]);

        // Its own frpc binds the port; the next round must not see it as taken.
        let frpc = TcpListener::bind((Ipv4Addr::LOCALHOST, port)).unwrap();
        let again = registry
            .assign(DEFAULT_OWNER, &[visitor(name, port)], false)
            .unwrap();
        assert_eq!(again, first);

        // A new server port is no new visitor either.
        let moved = registry
            .assign(DEFAULT_OWNER, &[visitor(name, free_port())], false)
            .unwrap();
        assert_eq!(moved[0].1, port);
        drop(frpc);
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn port_registry_gives_two_owners_of_one_server_port_different_local_ports() {
        let dir = scratch_dir("owners");
        let registry = PortRegistry::new(&dir);
        let port = free_port();

        let mine = registry
            .assign(DEFAULT_OWNER, &[visitor("ssh", port)], false)
            .unwrap();
        let theirs = registry
            .assign("other", &[visitor("ssh", port)], false)
            .unwrap();

        assert_eq!(mine[0].1, port);
        assert_ne!(theirs[0].1, port);
        assert!(FALLBACK_PORTS.contains(&theirs[0].1));
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn port_registry_handles_on_one_file_see_each_other() {
        let dir = scratch_dir("handles");
        let port = free_port();
        let first = PortRegistry::new(&dir)
            .assign(DEFAULT_OWNER, &[visitor("ssh", port)], false)
            .unwrap();

        // A second handle, as another process would open it.
        let second = PortRegistry::new(&dir);
        let frpc = TcpListener::bind((Ipv4Addr::LOCALHOST, port)).unwrap();
        assert_eq!(
            second
                .assign(DEFAULT_OWNER, &[visitor("ssh", port)], false)
                .unwrap(),
            first
        );
        drop(frpc);
        let theirs = second
            .assign("other", &[visitor("rdp", port)], false)
            .unwrap();
        assert_ne!(theirs[0].1, port);
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn port_registry_drops_the_owners_visitors_it_no_longer_gets() {
        let dir = scratch_dir("drop");
        let registry = PortRegistry::new(&dir);
        let [kept, dropped, other] = free_ports();
        registry
            .assign(
                DEFAULT_OWNER,
                &[visitor("kept", kept), visitor("dropped", dropped)],
                false,
            )
            .unwrap();
        registry
            .assign("other", &[visitor("other", other)], false)
            .unwrap();

        registry
            .assign(DEFAULT_OWNER, &[visitor("kept", kept)], false)
            .unwrap();

        // The dropped visitor's port is free again; the kept one's and the other owner's are not.
        let third = registry
            .assign(
                "third",
                &[
                    visitor("a", dropped),
                    visitor("b", kept),
                    visitor("c", other),
                ],
                false,
            )
            .unwrap();
        assert_eq!(third[0], visitor("a", dropped));
        assert_ne!(third[1].1, kept);
        assert_ne!(third[2].1, other);
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn port_registry_starts_a_broken_file_empty() {
        let dir = scratch_dir("broken");
        fs::create_dir_all(&dir).unwrap();
        let path = dir.join(REGISTRY_FILE);
        fs::write(&path, b"{\"entries\": [\xff").unwrap();
        let port = free_port();

        let assigned = PortRegistry::new(&dir)
            .assign(DEFAULT_OWNER, &[visitor("ssh", port)], false)
            .unwrap();

        assert_eq!(assigned, [visitor("ssh", port)]);
        let written: serde_json::Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        assert_eq!(written["entries"].as_array().unwrap().len(), 1);
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn port_registry_file_holds_the_entries_private_and_leaves_no_temp() {
        let dir = scratch_dir("file");
        let port = free_port();
        let local = PortRegistry::new(&dir)
            .assign(DEFAULT_OWNER, &[visitor("ssh", port)], false)
            .unwrap()[0]
            .1;

        let path = dir.join(REGISTRY_FILE);
        let written: serde_json::Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        assert_eq!(
            written,
            serde_json::json!({"entries": [{
                "owner": DEFAULT_OWNER,
                "visitor": "ssh",
                "serverPort": port,
                "localPort": local,
            }]})
        );
        let mut names: Vec<String> = fs::read_dir(&dir)
            .unwrap()
            .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
            .collect();
        names.sort();
        assert_eq!(names, [REGISTRY_FILE, LOCK_FILE]);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = fs::metadata(&path).unwrap().permissions().mode() & 0o777;
            assert_eq!(mode, 0o600);
        }
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn port_registry_assign_waits_for_the_lock() {
        let dir = scratch_dir("lock");
        let held = PortRegistry::new(&dir).lock().unwrap();
        let other = PortRegistry::new(&dir);
        let port = free_port();

        let assigning =
            std::thread::spawn(move || other.assign(DEFAULT_OWNER, &[visitor("ssh", port)], false));
        std::thread::sleep(Duration::from_millis(200));
        assert!(!assigning.is_finished(), "assign ran past the held lock");
        assert!(!dir.join(REGISTRY_FILE).exists());

        drop(held);
        assert_eq!(assigning.join().unwrap().unwrap(), [visitor("ssh", port)]);
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn port_registry_without_a_free_fallback_port_fails() {
        let dir = scratch_dir("full");
        fs::create_dir_all(&dir).unwrap();
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        let entries: Vec<serde_json::Value> = FALLBACK_PORTS
            .map(|local| {
                serde_json::json!({
                    "owner": "other",
                    "visitor": format!("v{local}"),
                    "serverPort": local,
                    "localPort": local,
                })
            })
            .collect();
        fs::write(
            dir.join(REGISTRY_FILE),
            serde_json::to_vec(&serde_json::json!({ "entries": entries })).unwrap(),
        )
        .unwrap();

        let result = PortRegistry::new(&dir).assign(DEFAULT_OWNER, &[visitor("ssh", port)], false);

        assert!(
            matches!(&result, Err(AppError::Io(e)) if e.kind() == std::io::ErrorKind::AddrInUse),
            "{result:?}"
        );
        drop(listener);
        fs::remove_dir_all(&dir).ok();
    }
}
