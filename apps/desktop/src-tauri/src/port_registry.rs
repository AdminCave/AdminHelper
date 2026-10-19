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

/// The owner of every entry from before workspaces (R-0431); the migration hands its entries to
/// the migrated server workspace. Every other owner is a workspace id.
#[cfg_attr(
    not(test),
    expect(
        dead_code,
        reason = "only the migration (R-0431 T4) takes it up, and nothing runs that before T10"
    )
)]
pub const DEFAULT_OWNER: &str = "default";

/// Where a visitor goes whose server port is taken: below the ephemeral ports of Linux
/// (32768-60999) and Windows (49152-65535), outside the server's visitor ports (6000-6999).
pub const FALLBACK_PORTS: RangeInclusive<u16> = 23000..=23999;

/// The most visitors one owner gets ports for.
const MAX_VISITORS: usize = 500;

/// The most ports of [`FALLBACK_PORTS`] one owner holds: the range keeps room for at least four
/// workspaces, however many visitors a server sends.
const MAX_FALLBACK_PORTS: usize = 250;

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
    /// a port as [`free_port`] picks it. The entries of `owner` for visitors not given go. More
    /// than [`MAX_VISITORS`] visitors, or a visitor that would take `owner` past
    /// [`MAX_FALLBACK_PORTS`], is an error, and the map stays as it was.
    pub fn assign(
        &self,
        owner: &str,
        visitors: &[(String, u16)],
        recheck: bool,
    ) -> Result<Vec<(String, u16)>, AppError> {
        if visitors.len() > MAX_VISITORS {
            return Err(AppError::Validation(format!(
                "{} visitors, more than the {MAX_VISITORS} a workspace can take",
                visitors.len()
            )));
        }
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
                    // By where the port lies, not how it came: a server port in the range takes
                    // room from the other owners all the same.
                    let held = entries
                        .iter()
                        .filter(|entry| {
                            entry.owner == owner && FALLBACK_PORTS.contains(&entry.local_port)
                        })
                        .count();
                    if FALLBACK_PORTS.contains(&local_port) && held >= MAX_FALLBACK_PORTS {
                        return Err(AppError::Io(io::Error::new(
                            io::ErrorKind::AddrInUse,
                            format!(
                                "no local port for a visitor: this workspace already holds \
                                 {MAX_FALLBACK_PORTS} of the fallback ports {}-{}",
                                FALLBACK_PORTS.start(),
                                FALLBACK_PORTS.end()
                            ),
                        )));
                    }
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

    /// The local ports of every owner but `owner`: they lead to the visitors of another
    /// workspace.
    #[cfg_attr(
        not(test),
        expect(
            dead_code,
            reason = "the check of loopback targets (R-0431 T8) takes it up"
        )
    )]
    pub fn local_ports_of_others(&self, owner: &str) -> Result<Vec<u16>, AppError> {
        let _lock = self.lock()?;
        Ok(self
            .load()?
            .entries
            .into_iter()
            .filter(|entry| entry.owner != owner)
            .map(|entry| entry.local_port)
            .collect())
    }

    /// Hands the entries of `from` to `to`, local ports and all. Where `to` has an entry for the
    /// visitor already, that one stays and the one of `from` goes: one entry per visitor and
    /// owner. `to` ends with no more than [`MAX_VISITORS`] entries and [`MAX_FALLBACK_PORTS`]
    /// ports of [`FALLBACK_PORTS`]; the entries of `from` past either go, in the order of the
    /// map, so a map from before the caps cannot keep the fallback ports from the other owners.
    #[cfg_attr(
        not(test),
        expect(
            dead_code,
            reason = "only the migration (R-0431 T4) takes it up, and nothing runs that before T10"
        )
    )]
    pub fn rename_owner(&self, from: &str, to: &str) -> Result<(), AppError> {
        if from == to {
            return Ok(());
        }
        self.update(|entries| {
            let mut held: Vec<String> = entries
                .iter()
                .filter(|entry| entry.owner == to)
                .map(|entry| entry.visitor.clone())
                .collect();
            let mut fallback = entries
                .iter()
                .filter(|entry| entry.owner == to && FALLBACK_PORTS.contains(&entry.local_port))
                .count();
            let mut past_share = 0;
            entries.retain_mut(|entry| {
                if entry.owner != from {
                    return true;
                }
                if held.contains(&entry.visitor) {
                    return false;
                }
                let in_fallback = FALLBACK_PORTS.contains(&entry.local_port);
                if held.len() >= MAX_VISITORS || (in_fallback && fallback >= MAX_FALLBACK_PORTS) {
                    past_share += 1;
                    return false;
                }
                held.push(entry.visitor.clone());
                fallback += usize::from(in_fallback);
                entry.owner = to.to_string();
                true
            });
            if past_share > 0 {
                log::warn!(
                    "{REGISTRY_FILE}: dropped {past_share} entries of {from} past the share of {to}"
                );
            }
        })
    }

    /// Drops every entry of `owner`.
    #[cfg_attr(
        not(test),
        expect(
            dead_code,
            reason = "the migration (R-0431 T4) and the purge (T13) take it up"
        )
    )]
    pub fn release(&self, owner: &str) -> Result<(), AppError> {
        self.update(|entries| entries.retain(|entry| entry.owner != owner))
    }

    /// Drops the entries of every owner not in `owners`.
    #[cfg_attr(
        not(test),
        expect(dead_code, reason = "the launcher (R-0431 T11) takes it up")
    )]
    pub fn retain_owners(&self, owners: &[&str]) -> Result<(), AppError> {
        self.update(|entries| entries.retain(|entry| owners.contains(&entry.owner.as_str())))
    }

    /// Applies `change` to the entries under the lock and writes the map if that changed it.
    #[cfg_attr(
        not(test),
        expect(
            dead_code,
            reason = "only the methods above call it, none of them called yet"
        )
    )]
    fn update(&self, change: impl FnOnce(&mut Vec<Entry>)) -> Result<(), AppError> {
        let _lock = self.lock()?;
        let loaded = self.load()?;
        let mut updated = Registry {
            entries: loaded.entries.clone(),
        };
        change(&mut updated.entries);
        if updated != loaded {
            self.store(&updated)?;
        }
        Ok(())
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
    use std::path::{Path, PathBuf};
    use std::time::Duration;

    use super::{
        AppError, PortRegistry, DEFAULT_OWNER, FALLBACK_PORTS, LOCK_FILE, MAX_FALLBACK_PORTS,
        MAX_VISITORS, REGISTRY_FILE,
    };

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

    /// Make the map in `dir` hold exactly `entries`, each (owner, visitor, server port, local
    /// port).
    fn write_map(dir: &Path, entries: &[(&str, &str, u16, u16)]) {
        let entries: Vec<serde_json::Value> = entries
            .iter()
            .map(|&(owner, visitor, server_port, local_port)| {
                serde_json::json!({
                    "owner": owner,
                    "visitor": visitor,
                    "serverPort": server_port,
                    "localPort": local_port,
                })
            })
            .collect();
        fs::create_dir_all(dir).unwrap();
        fs::write(
            dir.join(REGISTRY_FILE),
            serde_json::to_vec(&serde_json::json!({ "entries": entries })).unwrap(),
        )
        .unwrap();
    }

    /// The entries of the map in `dir`, each (owner, visitor, local port), sorted.
    fn entries_in(dir: &Path) -> Vec<(String, String, u16)> {
        let map: serde_json::Value =
            serde_json::from_slice(&fs::read(dir.join(REGISTRY_FILE)).unwrap()).unwrap();
        let mut entries: Vec<(String, String, u16)> = map["entries"]
            .as_array()
            .unwrap()
            .iter()
            .map(|entry| {
                (
                    entry["owner"].as_str().unwrap().to_string(),
                    entry["visitor"].as_str().unwrap().to_string(),
                    u16::try_from(entry["localPort"].as_u64().unwrap()).unwrap(),
                )
            })
            .collect();
        entries.sort();
        entries
    }

    fn entry(owner: &str, visitor: &str, local_port: u16) -> (String, String, u16) {
        (owner.to_string(), visitor.to_string(), local_port)
    }

    #[test]
    fn port_registry_rejects_more_visitors_than_an_owner_may_have_and_keeps_the_map() {
        let dir = scratch_dir("many");
        let visitors: Vec<(String, u16)> = (30000..)
            .take(MAX_VISITORS + 1)
            .map(|port| visitor(&format!("v{port}"), port))
            .collect();
        // An earlier run gave all but the last their ports; kept, they take no bind test.
        let mut seeded: Vec<(&str, &str, u16, u16)> = visitors[..MAX_VISITORS]
            .iter()
            .map(|(name, port)| ("mine", name.as_str(), *port, *port))
            .collect();
        seeded.push(("other", "ssh", 6000, 6000));
        write_map(&dir, &seeded);
        let registry = PortRegistry::new(&dir);
        assert_eq!(
            registry
                .assign("mine", &visitors[..MAX_VISITORS], false)
                .unwrap()
                .len(),
            MAX_VISITORS
        );
        let before = fs::read(dir.join(REGISTRY_FILE)).unwrap();

        let result = registry.assign("mine", &visitors, false);

        assert!(
            matches!(&result, Err(AppError::Validation(_))),
            "{result:?}"
        );
        assert_eq!(fs::read(dir.join(REGISTRY_FILE)).unwrap(), before);
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn port_registry_gives_an_owner_no_more_than_its_share_of_fallback_ports() {
        let dir = scratch_dir("share");
        // An earlier run gave the owner all but one of its share; kept, they take no bind test.
        let mut visitors: Vec<(String, u16)> = FALLBACK_PORTS
            .take(MAX_FALLBACK_PORTS - 1)
            .map(|port| visitor(&format!("v{port}"), port))
            .collect();
        let seeded: Vec<(&str, &str, u16, u16)> = visitors
            .iter()
            .map(|(name, port)| ("mine", name.as_str(), *port, *port))
            .collect();
        write_map(&dir, &seeded);
        let registry = PortRegistry::new(&dir);
        // Someone else listens on the server port of the visitors to come.
        let holder = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
        let taken = holder.local_addr().unwrap().port();

        visitors.push(visitor("last", taken));
        let assigned = registry.assign("mine", &visitors, false).unwrap();
        let last = assigned[MAX_FALLBACK_PORTS - 1].1;
        assert!(FALLBACK_PORTS.contains(&last), "{last} is no fallback port");

        visitors.push(visitor("one too many", taken));
        let before = fs::read(dir.join(REGISTRY_FILE)).unwrap();
        let result = registry.assign("mine", &visitors, false);
        assert!(
            matches!(&result, Err(AppError::Io(e)) if e.kind() == std::io::ErrorKind::AddrInUse),
            "{result:?}"
        );
        assert_eq!(fs::read(dir.join(REGISTRY_FILE)).unwrap(), before);

        // A free server port is no fallback port: the owner still gets it.
        visitors.pop();
        let free = free_port();
        visitors.push(visitor("free", free));
        let assigned = registry.assign("mine", &visitors, false).unwrap();
        assert_eq!(assigned.last(), Some(&visitor("free", free)));

        // Another owner still gets a fallback port.
        let theirs = registry
            .assign("other", &[visitor("ssh", taken)], false)
            .unwrap();
        assert!(FALLBACK_PORTS.contains(&theirs[0].1), "{theirs:?}");
        drop(holder);
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn port_registry_lists_the_local_ports_of_the_other_owners() {
        let dir = scratch_dir("others");
        write_map(
            &dir,
            &[
                ("mine", "ssh", 6000, 6000),
                ("mine", "rdp", 6001, 23000),
                ("other", "ssh", 6000, 23001),
                ("third", "web", 6002, 6002),
            ],
        );

        let mut others = PortRegistry::new(&dir)
            .local_ports_of_others("mine")
            .unwrap();

        others.sort_unstable();
        assert_eq!(others, [6002, 23001]);
        let empty = scratch_dir("others-empty");
        assert!(PortRegistry::new(&empty)
            .local_ports_of_others("mine")
            .unwrap()
            .is_empty());
        fs::remove_dir_all(&dir).ok();
        fs::remove_dir_all(&empty).ok();
    }

    #[test]
    fn port_registry_renames_an_owner_and_its_visitors_keep_their_ports() {
        let dir = scratch_dir("rename");
        write_map(
            &dir,
            &[
                (DEFAULT_OWNER, "ssh", 6000, 6000),
                (DEFAULT_OWNER, "rdp", 6001, 23000),
                ("standard", "rdp", 6001, 23001),
                ("other", "ssh", 6000, 23002),
            ],
        );
        let registry = PortRegistry::new(&dir);

        registry.rename_owner(DEFAULT_OWNER, "standard").unwrap();

        // Where the new owner has the visitor already, its own entry stays: one entry per
        // visitor and owner.
        assert_eq!(
            entries_in(&dir),
            [
                entry("other", "ssh", 23002),
                entry("standard", "rdp", 23001),
                entry("standard", "ssh", 6000),
            ]
        );
        let before = fs::read(dir.join(REGISTRY_FILE)).unwrap();
        registry.rename_owner("nobody", "standard").unwrap();
        registry.rename_owner("standard", "standard").unwrap();
        assert_eq!(fs::read(dir.join(REGISTRY_FILE)).unwrap(), before);
        // Kept, the renamed entries take no bind test.
        assert_eq!(
            registry
                .assign(
                    "standard",
                    &[visitor("ssh", 6000), visitor("rdp", 6001)],
                    false
                )
                .unwrap(),
            [visitor("ssh", 6000), visitor("rdp", 23001)]
        );
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn port_registry_renames_no_more_than_the_share_of_the_new_owner() {
        let dir = scratch_dir("rename-share");
        // A map from before the caps: the old owner holds more visitors and fallback ports than
        // an owner may. The new owner holds one fallback port already.
        let count = u16::try_from(MAX_VISITORS + 60).unwrap();
        let in_fallback = u16::try_from(MAX_FALLBACK_PORTS + 50).unwrap();
        let names: Vec<String> = (0..count).map(|i| format!("v{i}")).collect();
        let mut seeded = vec![
            ("standard", "own", 6000, 23999),
            ("other", "ssh", 6000, 23998),
        ];
        for (i, name) in (0..count).zip(&names) {
            let local = if i < in_fallback {
                FALLBACK_PORTS.start() + i
            } else {
                30000 + i
            };
            seeded.push((DEFAULT_OWNER, name.as_str(), local, local));
        }
        write_map(&dir, &seeded);

        PortRegistry::new(&dir)
            .rename_owner(DEFAULT_OWNER, "standard")
            .unwrap();

        let entries = entries_in(&dir);
        let standard: Vec<&(String, String, u16)> = entries
            .iter()
            .filter(|(owner, _, _)| owner == "standard")
            .collect();
        assert_eq!(standard.len(), MAX_VISITORS);
        assert_eq!(
            standard
                .iter()
                .filter(|(_, _, port)| FALLBACK_PORTS.contains(port))
                .count(),
            MAX_FALLBACK_PORTS
        );
        // In the order of the map: the entries before a cap stay, with their ports; the ones past
        // it go.
        for (visitor, port, kept) in [
            ("own", 23999, true),
            ("v0", 23000, true),
            ("v248", 23248, true),
            ("v249", 23249, false),
            ("v299", 23299, false),
            ("v300", 30300, true),
            ("v549", 30549, true),
            ("v550", 30550, false),
        ] {
            assert_eq!(
                entries.contains(&entry("standard", visitor, port)),
                kept,
                "{visitor}"
            );
        }
        assert!(entries.contains(&entry("other", "ssh", 23998)));
        assert!(entries.iter().all(|(owner, _, _)| owner != DEFAULT_OWNER));
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn port_registry_releases_the_entries_of_an_owner() {
        let dir = scratch_dir("release");
        write_map(
            &dir,
            &[
                ("mine", "ssh", 6000, 6000),
                ("mine", "rdp", 6001, 23000),
                ("other", "ssh", 6000, 23001),
            ],
        );
        let registry = PortRegistry::new(&dir);

        registry.release("mine").unwrap();

        assert_eq!(entries_in(&dir), [entry("other", "ssh", 23001)]);
        let before = fs::read(dir.join(REGISTRY_FILE)).unwrap();
        registry.release("nobody").unwrap();
        assert_eq!(fs::read(dir.join(REGISTRY_FILE)).unwrap(), before);
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn port_registry_retains_only_the_entries_of_the_owners_named() {
        let dir = scratch_dir("retain");
        write_map(
            &dir,
            &[
                ("standard", "ssh", 6000, 6000),
                ("w-0a1b2c3d", "ssh", 6000, 23000),
                ("w-deadbeef", "ssh", 6000, 23001),
                (DEFAULT_OWNER, "rdp", 6001, 6001),
            ],
        );
        let registry = PortRegistry::new(&dir);

        registry
            .retain_owners(&["standard", "w-0a1b2c3d", "w-00000000"])
            .unwrap();

        assert_eq!(
            entries_in(&dir),
            [
                entry("standard", "ssh", 6000),
                entry("w-0a1b2c3d", "ssh", 23000),
            ]
        );
        registry.retain_owners(&[]).unwrap();
        assert!(entries_in(&dir).is_empty());
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn port_registry_reads_and_changes_owners_under_the_lock() {
        let dir = scratch_dir("owners-lock");
        write_map(&dir, &[("mine", "ssh", 6000, 6000)]);
        let held = PortRegistry::new(&dir).lock().unwrap();
        type Call = fn(&PortRegistry) -> Result<(), AppError>;
        let calls: [Call; 4] = [
            |registry| registry.local_ports_of_others("mine").map(drop),
            |registry| registry.rename_owner("mine", "theirs"),
            |registry| registry.release("theirs"),
            |registry| registry.retain_owners(&["mine"]),
        ];

        let calling: Vec<_> = calls
            .into_iter()
            .map(|call| {
                let registry = PortRegistry::new(&dir);
                std::thread::spawn(move || call(&registry))
            })
            .collect();
        std::thread::sleep(Duration::from_millis(200));
        assert!(
            calling.iter().all(|call| !call.is_finished()),
            "a call ran past the held lock"
        );

        drop(held);
        for call in calling {
            call.join().unwrap().unwrap();
        }
        fs::remove_dir_all(&dir).ok();
    }
}
