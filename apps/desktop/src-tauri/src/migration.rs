// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! The move of the data from before workspaces (R-0431) into the workspace layout, once per app
//! data dir. The settings, connections and port map of the one workspace an older version knew
//! become the workspace "Standard" in its mode; local connections, a sync URL and a server URL
//! that mode left unused become "Lokal", "Sync" and "Server" beside it. All of them keep the
//! keyring keys without a prefix, so stored passwords and an enrolled identity stay in use.
//!
//! The old files stay as they are: each run reads them, and an older version reads them again
//! after a downgrade. A run builds each workspace in `<id>.partial/` and renames it, writes
//! `prefs.json`, hands over the port map and writes `workspaces.json` last, at once. Until that
//! file is there, the next run builds everything anew from the old files.

#![cfg_attr(
    not(test),
    expect(
        dead_code,
        reason = "no caller yet: the start of every process (R-0431 T10) runs the migration"
    )
)]

use std::fs::{self, File};
use std::io;
use std::path::{Path, PathBuf};

use crate::error::AppError;
use crate::models::{Settings, SyncMode};
use crate::port_registry::{PortRegistry, DEFAULT_OWNER};
use crate::storage::{
    connections_file_name, harden_permissions, migrate_between, write_json_pretty, Prefs,
    PREFS_FILE,
};
use crate::workspace::{
    Meta, Registry, RegistryEntry, Workspace, WorkspaceId, PALETTE, REGISTRY_FILE,
};

/// In the app data dir: the lock every migration takes.
const LOCK_FILE: &str = "migrate.lock";

/// In the app data dir: the settings of the one workspace before R-0431, as older versions named
/// them.
const LEGACY_SETTINGS: &str = "settings.json";

/// A workspace the migration can make. The ids are fixed, so a run after an abort finds what the
/// run before it left.
#[derive(Clone, Copy)]
struct Template {
    id: &'static str,
    name: &'static str,
    color: &'static str,
}

const STANDARD: Template = Template {
    id: "standard",
    name: "Standard",
    color: PALETTE[0],
};
const LOCAL: Template = Template {
    id: "lokal",
    name: "Lokal",
    color: PALETTE[1],
};
const SYNC: Template = Template {
    id: "sync",
    name: "Sync",
    color: PALETTE[2],
};
const SERVER: Template = Template {
    id: "server",
    name: "Server",
    color: PALETTE[4],
};

/// Every workspace a run may have left; nothing but the migration makes these ids.
const TEMPLATES: [Template; 4] = [STANDARD, LOCAL, SYNC, SERVER];

/// A workspace this run makes.
struct Planned {
    id: WorkspaceId,
    meta: Meta,
    /// Takes over the connections in the app data dir, those of the mode they were written in.
    connections: bool,
}

impl Planned {
    fn new(
        template: Template,
        kind: SyncMode,
        settings: &Settings,
        connections: bool,
    ) -> Result<Self, AppError> {
        // Each kind takes its own address; the login name belongs to the server.
        let (url, last_username) = match kind {
            SyncMode::Local => (None, None),
            SyncMode::Sync => (filled(settings.sync_url.as_deref()), None),
            SyncMode::Server => (
                filled(settings.server_url.as_deref()),
                filled(settings.last_username.as_deref()),
            ),
        };
        Ok(Self {
            id: WorkspaceId::parse(template.id)?,
            meta: Meta {
                kind,
                name: template.name.to_string(),
                color: template.color.to_string(),
                url,
                interval_minutes: settings.interval_minutes,
                allow_self_signed_certs: settings.allow_self_signed_certs,
                last_username,
                legacy_keys: true,
            },
            connections,
        })
    }
}

/// Moves the data in the app data dir `base` into the workspace layout, unless `workspaces.json`
/// says that happened. Processes that call it at once take turns under `migrate.lock`; all but
/// the first find it done.
pub fn migrate(base: &Path) -> Result<(), AppError> {
    migrate_with(base, &mut |_| Ok(()))
}

/// [`migrate`], calling `step` with the name of each step once it is done; an error from `step`
/// ends the run there, as a crash would.
fn migrate_with(
    base: &Path,
    step: &mut dyn FnMut(&str) -> Result<(), AppError>,
) -> Result<(), AppError> {
    fs::create_dir_all(base)?;
    let _lock = MigrateLock::take(&base.join(LOCK_FILE))?;
    // Whether the registry parses is for its readers: a run here would build over the
    // workspaces it names.
    if base.join(REGISTRY_FILE).try_exists()? {
        return Ok(());
    }
    let settings = legacy_settings(base)?;
    let planned = plan(base, &settings)?;

    // What an aborted run left. No process opens a workspace the registry does not name.
    for template in TEMPLATES {
        let dir = data_dir(base, &WorkspaceId::parse(template.id)?);
        remove_dir(&partial(&dir))?;
        remove_dir(&dir)?;
    }
    step("cleared")?;
    for ws in &planned {
        let dir = data_dir(base, &ws.id);
        let partial = partial(&dir);
        build(base, &partial, ws, &settings.mode)?;
        step(&format!("built {}", ws.id))?;
        fs::rename(&partial, &dir)?;
        step(&format!("placed {}", ws.id))?;
    }
    write_json_pretty(&base.join(PREFS_FILE), &Prefs::from(&settings))?;
    step("prefs")?;
    let ports = PortRegistry::new(base);
    match planned.iter().find(|ws| ws.meta.kind == SyncMode::Server) {
        Some(server) => ports.rename_owner(DEFAULT_OWNER, &server.id.to_string())?,
        None => ports.release(DEFAULT_OWNER)?,
    }
    step("ports")?;
    commit(
        base,
        &Registry {
            workspaces: planned
                .iter()
                .map(|ws| RegistryEntry { id: ws.id.clone() })
                .collect(),
            last_used: Some(WorkspaceId::parse(STANDARD.id)?),
            migrated_notice: true,
        },
    )?;
    let ids: Vec<String> = planned.iter().map(|ws| ws.id.to_string()).collect();
    log::info!("moved the data into the workspaces {}", ids.join(", "));
    Ok(())
}

/// The settings an older version left in `base`, or their defaults (local mode) if it left none.
/// A file that does not parse stops the migration: built from the defaults, the workspaces would
/// have lost its server for good. The error names the file and where it breaks, never a value
/// from it: serde quotes the values it rejects.
fn legacy_settings(base: &Path) -> Result<Settings, AppError> {
    let bytes = match fs::read(base.join(LEGACY_SETTINGS)) {
        Ok(bytes) => bytes,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(Settings::default()),
        Err(e) => return Err(e.into()),
    };
    serde_json::from_slice(&bytes).map_err(|e| {
        AppError::Io(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "{LEGACY_SETTINGS}: does not parse ({:?} error at line {}, column {})",
                e.classify(),
                e.line(),
                e.column()
            ),
        ))
    })
}

/// The workspaces the data in `base` makes: "Standard" in the mode of `settings`, and one beside
/// it for each kind of data that mode left unused.
fn plan(base: &Path, settings: &Settings) -> Result<Vec<Planned>, AppError> {
    let mut planned = vec![Planned::new(
        STANDARD,
        settings.mode.clone(),
        settings,
        true,
    )?];
    let local_store = base.join(connections_file_name(&SyncMode::Local));
    if settings.mode != SyncMode::Local && holds_connections(&local_store)? {
        planned.push(Planned::new(LOCAL, SyncMode::Local, settings, true)?);
    }
    if settings.mode != SyncMode::Sync && filled(settings.sync_url.as_deref()).is_some() {
        planned.push(Planned::new(SYNC, SyncMode::Sync, settings, false)?);
    }
    if settings.mode != SyncMode::Server && filled(settings.server_url.as_deref()).is_some() {
        planned.push(Planned::new(SERVER, SyncMode::Server, settings, false)?);
    }
    Ok(planned)
}

/// The value, unless there is none or it is blank: the settings dialog saves an empty field as
/// `""`.
fn filled(value: Option<&str>) -> Option<String> {
    value
        .filter(|value| !value.trim().is_empty())
        .map(String::from)
}

/// Whether the connections file at `path` holds any. One that does not parse counts: it is the
/// user's data all the same, and the copy keeps it byte for byte.
fn holds_connections(path: &Path) -> Result<bool, AppError> {
    match fs::read(path) {
        Ok(bytes) => Ok(!serde_json::from_slice::<Vec<serde_json::Value>>(&bytes)
            .is_ok_and(|connections| connections.is_empty())),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(e) => Err(e.into()),
    }
}

/// The data dir of the workspace `id` in `base`; it hangs on the id alone.
fn data_dir(base: &Path, id: &WorkspaceId) -> PathBuf {
    Workspace {
        id: id.clone(),
        name: String::new(),
        legacy_keys: true,
    }
    .data_dir(base)
}

/// Where the data dir `dir` is built before it gets its name; no workspace id holds a `.`.
fn partial(dir: &Path) -> PathBuf {
    let mut partial = dir.as_os_str().to_owned();
    partial.push(".partial");
    PathBuf::from(partial)
}

fn remove_dir(dir: &Path) -> Result<(), AppError> {
    match fs::remove_dir_all(dir) {
        Err(e) if e.kind() != io::ErrorKind::NotFound => Err(e.into()),
        _ => Ok(()),
    }
}

/// Fills `dir`, the data dir of `ws` before it gets its name. `mode` is the mode the old files
/// were written in.
fn build(base: &Path, dir: &Path, ws: &Planned, mode: &SyncMode) -> Result<(), AppError> {
    fs::create_dir_all(dir)?;
    ws.meta.store(dir)?;
    if ws.connections {
        let name = connections_file_name(&ws.meta.kind);
        copy_if_present(&base.join(name), &dir.join(name))?;
        // Before the local store had a file of its own, local mode kept its connections in the
        // cache file. `migrate_between` takes them only in that mode and only if no store is
        // there.
        migrate_between(
            &base.join(connections_file_name(&SyncMode::Server)),
            &dir.join(connections_file_name(&SyncMode::Local)),
            mode,
        )?;
    }
    Ok(())
}

fn copy_if_present(from: &Path, to: &Path) -> Result<(), AppError> {
    match fs::copy(from, to) {
        Ok(_) => {
            harden_permissions(to);
            Ok(())
        }
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(e) => Err(e.into()),
    }
}

/// Writes the registry, which ends the migration, at once on every platform: a crash leaves no
/// file or the whole one. (`Registry::store` writes in place on Windows; a torn registry would
/// neither parse nor let the next run start over.)
fn commit(base: &Path, registry: &Registry) -> Result<(), AppError> {
    let tmp = base.join(format!("{REGISTRY_FILE}.tmp"));
    fs::write(&tmp, serde_json::to_vec_pretty(registry)?)?;
    harden_permissions(&tmp);
    fs::rename(&tmp, base.join(REGISTRY_FILE))?;
    Ok(())
}

/// Keeps every other migration of the app data dir waiting until it drops. The lock sits on a
/// file of its own: on Windows it can bar every other handle from the bytes it covers.
struct MigrateLock(File);

impl MigrateLock {
    fn take(path: &Path) -> Result<Self, AppError> {
        let mut options = fs::OpenOptions::new();
        options.read(true).write(true).create(true).truncate(false);
        #[cfg(unix)]
        std::os::unix::fs::OpenOptionsExt::mode(&mut options, 0o600);
        let file = options.open(path)?;
        file.lock()?;
        Ok(Self(file))
    }
}

impl Drop for MigrateLock {
    fn drop(&mut self) {
        // Windows frees the lock of a closed handle when it gets round to it; the next start
        // need not wait for that.
        let _ = self.0.unlock();
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;
    use std::fs::{self, File};
    use std::path::{Path, PathBuf};
    use std::sync::{Arc, Barrier};
    use std::thread;
    use std::time::Duration;

    use serde_json::json;

    use super::{migrate, migrate_with, LOCK_FILE};
    use crate::error::AppError;
    use crate::models::SyncMode;
    use crate::port_registry::DEFAULT_OWNER;
    use crate::workspace::{Meta, Registry, RegistryEntry, WorkspaceId, PALETTE, REGISTRY_FILE};

    /// A directory of its own for one test case under the system temp dir, gone with the guard.
    /// Not created: the migration makes the app data dir it is given.
    struct Scratch(PathBuf);

    impl Scratch {
        fn new(case: &str) -> Self {
            let dir =
                std::env::temp_dir().join(format!("ah-migration-{case}-{}", std::process::id()));
            let _ = fs::remove_dir_all(&dir);
            Self(dir)
        }
    }

    impl Drop for Scratch {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    /// The files of the layout before workspaces, as older versions named them.
    const SETTINGS: &str = "settings.json";
    const CACHE_FILE: &str = "connections.json";
    const LOCAL_FILE: &str = "connections.local.json";
    const LEGACY: [&str; 3] = [SETTINGS, CACHE_FILE, LOCAL_FILE];
    const PORT_MAP: &str = "port-registry.json";

    const CACHE: &str = r#"[{"id":"from-the-server"}]"#;
    const LOCAL: &str = r#"[{"id":"mine"}]"#;

    /// What a version before workspaces wrote in server mode, with a sync URL beside the
    /// server URL and every global setting off its default.
    const SERVER_SETTINGS: &str = r#"{
        "mode": "server",
        "url": "https://sync.example.com/connections.json",
        "intervalMinutes": 7,
        "language": "en",
        "storePasswords": true,
        "rdpScalingMode": "hdpi",
        "rdpWindowMode": "custom",
        "rdpCustomSize": "1600x900",
        "rdpPerformanceProfile": "lan",
        "allowSelfSignedCerts": true,
        "serverUrl": "https://ah.example.com",
        "lastUsername": "admin",
        "osNotifications": true
    }"#;
    const SERVER_URL: &str = "https://ah.example.com";
    const SYNC_URL: &str = "https://sync.example.com/connections.json";

    /// [`SERVER_SETTINGS`] with the fields of `changes` in place of its own.
    fn settings(changes: serde_json::Value) -> String {
        let mut settings: serde_json::Value = serde_json::from_str(SERVER_SETTINGS).unwrap();
        for (key, value) in changes.as_object().unwrap() {
            settings[key] = value.clone();
        }
        settings.to_string()
    }

    /// Lays out the app data dir `base` as a version before workspaces left it.
    fn legacy(base: &Path, files: &[(&str, &str)]) {
        fs::create_dir_all(base).unwrap();
        for (name, content) in files {
            fs::write(base.join(name), content).unwrap();
        }
    }

    /// The bytes of each file of the old layout, `None` where there is none.
    fn legacy_bytes(base: &Path) -> Vec<Option<Vec<u8>>> {
        LEGACY
            .iter()
            .map(|name| fs::read(base.join(name)).ok())
            .collect()
    }

    /// Make the port map in `base` hold exactly `entries`, each (owner, visitor, server port,
    /// local port).
    fn write_ports(base: &Path, entries: &[(&str, &str, u16, u16)]) {
        let entries: Vec<serde_json::Value> = entries
            .iter()
            .map(|&(owner, visitor, server_port, local_port)| {
                json!({
                    "owner": owner,
                    "visitor": visitor,
                    "serverPort": server_port,
                    "localPort": local_port,
                })
            })
            .collect();
        fs::create_dir_all(base).unwrap();
        fs::write(
            base.join(PORT_MAP),
            serde_json::to_vec(&json!({ "entries": entries })).unwrap(),
        )
        .unwrap();
    }

    /// The entries of the port map in `base`, each (owner, visitor, local port), sorted.
    fn ports_in(base: &Path) -> Vec<(String, String, u16)> {
        let map: serde_json::Value =
            serde_json::from_slice(&fs::read(base.join(PORT_MAP)).unwrap()).unwrap();
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

    fn port(owner: &str, visitor: &str, local_port: u16) -> (String, String, u16) {
        (owner.to_string(), visitor.to_string(), local_port)
    }

    /// A server install with data for every extra workspace: local connections, a sync URL,
    /// and ports of its own and of another owner in the port map.
    fn server_install(base: &Path) {
        legacy(
            base,
            &[
                (SETTINGS, SERVER_SETTINGS),
                (CACHE_FILE, CACHE),
                (LOCAL_FILE, LOCAL),
            ],
        );
        write_ports(
            base,
            &[
                (DEFAULT_OWNER, "ssh", 6000, 6000),
                (DEFAULT_OWNER, "rdp", 6001, 23000),
                ("other", "ssh", 6000, 23001),
            ],
        );
    }

    /// Every directory (with a trailing `/`) and file under `dir`, files with their bytes. Lock
    /// files hold nothing and stay out: on Windows the lock of a closed handle can linger, and
    /// a read then fails.
    fn snapshot(dir: &Path) -> BTreeMap<String, Option<Vec<u8>>> {
        fn walk(dir: &Path, prefix: &str, out: &mut BTreeMap<String, Option<Vec<u8>>>) {
            for entry in fs::read_dir(dir).unwrap() {
                let entry = entry.unwrap();
                let name = format!("{prefix}{}", entry.file_name().to_string_lossy());
                if entry.file_type().unwrap().is_dir() {
                    let name = format!("{name}/");
                    walk(&entry.path(), &name, out);
                    out.insert(name, None);
                } else if !name.ends_with(".lock") {
                    out.insert(name, Some(fs::read(entry.path()).unwrap()));
                }
            }
        }
        let mut out = BTreeMap::new();
        walk(dir, "", &mut out);
        out
    }

    /// The data dir of the workspace `id` in `base`.
    fn dir_of(base: &Path, id: &str) -> PathBuf {
        base.join("workspaces").join(id)
    }

    /// The names in `dir`, sorted.
    fn names_in(dir: &Path) -> Vec<String> {
        let mut names: Vec<String> = fs::read_dir(dir)
            .unwrap()
            .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
            .collect();
        names.sort();
        names
    }

    fn read(path: PathBuf) -> String {
        fs::read_to_string(path).unwrap()
    }

    fn registry(ids: &[&str]) -> Registry {
        Registry {
            workspaces: ids
                .iter()
                .map(|id| RegistryEntry {
                    id: WorkspaceId::parse(id).unwrap(),
                })
                .collect(),
            last_used: Some(WorkspaceId::parse("standard").unwrap()),
            migrated_notice: true,
        }
    }

    /// The meta of a migrated workspace of [`SERVER_SETTINGS`].
    fn meta(
        kind: SyncMode,
        name: &str,
        color: &str,
        url: Option<&str>,
        last_username: Option<&str>,
    ) -> Meta {
        Meta {
            kind,
            name: name.to_string(),
            color: color.to_string(),
            url: url.map(String::from),
            interval_minutes: 7,
            allow_self_signed_certs: true,
            last_username: last_username.map(String::from),
            legacy_keys: true,
        }
    }

    fn prefs_in(base: &Path) -> serde_json::Value {
        serde_json::from_slice(&fs::read(base.join("prefs.json")).unwrap()).unwrap()
    }

    /// A run that stops with an error at its step `abort_at` (counted from 0), as a crash there
    /// would; it runs through if it has no such step.
    fn run_aborting_at(base: &Path, abort_at: usize) -> Result<(), AppError> {
        let mut steps = 0;
        migrate_with(base, &mut |_| {
            steps += 1;
            if steps > abort_at {
                Err(AppError::Validation("aborted".to_string()))
            } else {
                Ok(())
            }
        })
    }

    #[test]
    fn a_server_install_becomes_standard_and_its_other_data_lokal_and_sync() {
        let scratch = Scratch::new("server");
        let base = &scratch.0;
        server_install(base);
        let before = legacy_bytes(base);

        migrate(base).unwrap();

        assert_eq!(
            Registry::load(base).unwrap(),
            Some(registry(&["standard", "lokal", "sync"]))
        );
        assert_eq!(
            names_in(&base.join("workspaces")),
            ["lokal", "standard", "sync"]
        );
        let standard = dir_of(base, "standard");
        assert_eq!(
            Meta::load(&standard).unwrap(),
            meta(
                SyncMode::Server,
                "Standard",
                PALETTE[0],
                Some(SERVER_URL),
                Some("admin")
            )
        );
        assert_eq!(names_in(&standard), [CACHE_FILE, "workspace.json"]);
        assert_eq!(read(standard.join(CACHE_FILE)), CACHE);
        let lokal = dir_of(base, "lokal");
        assert_eq!(
            Meta::load(&lokal).unwrap(),
            meta(SyncMode::Local, "Lokal", PALETTE[1], None, None)
        );
        assert_eq!(names_in(&lokal), [LOCAL_FILE, "workspace.json"]);
        assert_eq!(read(lokal.join(LOCAL_FILE)), LOCAL);
        let sync = dir_of(base, "sync");
        assert_eq!(
            Meta::load(&sync).unwrap(),
            meta(SyncMode::Sync, "Sync", PALETTE[2], Some(SYNC_URL), None)
        );
        // The cache file is the server's: the sync workspace fetches its own.
        assert_eq!(names_in(&sync), ["workspace.json"]);
        assert_eq!(
            prefs_in(base),
            json!({
                "language": "en",
                "storePasswords": true,
                "rdpScalingMode": "hdpi",
                "rdpWindowMode": "custom",
                "rdpCustomSize": "1600x900",
                "rdpPerformanceProfile": "lan",
                "osNotifications": true,
            })
        );
        // The visitors keep their local ports, now under the server workspace.
        assert_eq!(
            ports_in(base),
            [
                port("other", "ssh", 23001),
                port("standard", "rdp", 23000),
                port("standard", "ssh", 6000),
            ]
        );
        assert_eq!(legacy_bytes(base), before);
    }

    #[test]
    fn a_sync_install_with_a_server_url_becomes_standard_and_server() {
        let scratch = Scratch::new("sync");
        let base = &scratch.0;
        legacy(
            base,
            &[
                (SETTINGS, &settings(json!({"mode": "sync"}))),
                (CACHE_FILE, CACHE),
                // An empty local store makes no workspace.
                (LOCAL_FILE, "[]"),
            ],
        );
        write_ports(base, &[(DEFAULT_OWNER, "ssh", 6000, 6000)]);
        let before = legacy_bytes(base);

        migrate(base).unwrap();

        assert_eq!(
            Registry::load(base).unwrap(),
            Some(registry(&["standard", "server"]))
        );
        let standard = dir_of(base, "standard");
        assert_eq!(
            Meta::load(&standard).unwrap(),
            meta(SyncMode::Sync, "Standard", PALETTE[0], Some(SYNC_URL), None)
        );
        assert_eq!(names_in(&standard), [CACHE_FILE, "workspace.json"]);
        assert_eq!(read(standard.join(CACHE_FILE)), CACHE);
        let server = dir_of(base, "server");
        assert_eq!(
            Meta::load(&server).unwrap(),
            meta(
                SyncMode::Server,
                "Server",
                PALETTE[4],
                Some(SERVER_URL),
                Some("admin")
            )
        );
        assert_eq!(names_in(&server), ["workspace.json"]);
        assert_eq!(ports_in(base), [port("server", "ssh", 6000)]);
        assert_eq!(legacy_bytes(base), before);
    }

    #[test]
    fn a_local_install_takes_its_store_and_leaves_the_cache_and_empty_urls() {
        let scratch = Scratch::new("local");
        let base = &scratch.0;
        legacy(
            base,
            &[
                (
                    SETTINGS,
                    // The settings dialog saves an empty field as "".
                    &settings(
                        json!({"mode": "local", "url": "", "serverUrl": " ", "lastUsername": ""}),
                    ),
                ),
                (CACHE_FILE, CACHE),
                (LOCAL_FILE, LOCAL),
            ],
        );
        write_ports(
            base,
            &[
                (DEFAULT_OWNER, "ssh", 6000, 6000),
                ("other", "ssh", 6000, 23001),
            ],
        );
        let before = legacy_bytes(base);

        migrate(base).unwrap();

        assert_eq!(Registry::load(base).unwrap(), Some(registry(&["standard"])));
        let standard = dir_of(base, "standard");
        assert_eq!(
            Meta::load(&standard).unwrap(),
            meta(SyncMode::Local, "Standard", PALETTE[0], None, None)
        );
        assert_eq!(names_in(&standard), [LOCAL_FILE, "workspace.json"]);
        assert_eq!(read(standard.join(LOCAL_FILE)), LOCAL);
        // No server workspace takes the ports of the old owner: they go.
        assert_eq!(ports_in(base), [port("other", "ssh", 23001)]);
        assert_eq!(legacy_bytes(base), before);
    }

    #[test]
    fn a_local_install_from_before_the_split_takes_the_cache_file_as_its_store() {
        let scratch = Scratch::new("pre-split");
        let base = &scratch.0;
        let old = r#"[{"id":"from-before-the-split"}]"#;
        legacy(
            base,
            &[
                (
                    SETTINGS,
                    &settings(json!({"mode": "local", "url": null, "serverUrl": null})),
                ),
                (CACHE_FILE, old),
            ],
        );

        migrate(base).unwrap();

        let standard = dir_of(base, "standard");
        assert_eq!(names_in(&standard), [LOCAL_FILE, "workspace.json"]);
        assert_eq!(read(standard.join(LOCAL_FILE)), old);
        assert_eq!(Registry::load(base).unwrap(), Some(registry(&["standard"])));
    }

    #[test]
    fn without_settings_the_standard_workspace_is_local_with_the_defaults() {
        let scratch = Scratch::new("no-settings");
        let base = &scratch.0;
        // Who never opened the settings has local connections and no settings.json.
        legacy(base, &[(LOCAL_FILE, LOCAL)]);

        migrate(base).unwrap();

        let standard = dir_of(base, "standard");
        assert_eq!(
            Meta::load(&standard).unwrap(),
            Meta {
                interval_minutes: 1,
                allow_self_signed_certs: false,
                ..meta(SyncMode::Local, "Standard", PALETTE[0], None, None)
            }
        );
        assert_eq!(read(standard.join(LOCAL_FILE)), LOCAL);
        assert_eq!(
            prefs_in(base),
            json!({
                "language": null,
                "storePasswords": false,
                "rdpScalingMode": "auto",
                "rdpWindowMode": "fit",
                "rdpCustomSize": null,
                "rdpPerformanceProfile": "auto",
                "osNotifications": false,
            })
        );
        assert_eq!(Registry::load(base).unwrap(), Some(registry(&["standard"])));
    }

    #[test]
    fn a_first_start_makes_an_empty_local_standard_workspace() {
        let scratch = Scratch::new("first-start");
        let base = &scratch.0;
        assert!(!base.exists());

        migrate(base).unwrap();

        assert_eq!(Registry::load(base).unwrap(), Some(registry(&["standard"])));
        let standard = dir_of(base, "standard");
        assert_eq!(names_in(&standard), ["workspace.json"]);
        assert_eq!(Meta::load(&standard).unwrap().kind, SyncMode::Local);
        assert!(!base.join(PORT_MAP).exists());
    }

    #[test]
    fn a_local_store_that_does_not_parse_still_moves_into_lokal() {
        // It is the user's data all the same; the copy keeps it byte for byte.
        let scratch = Scratch::new("local-broken");
        let base = &scratch.0;
        legacy(base, &[(SETTINGS, SERVER_SETTINGS), (LOCAL_FILE, "{oops")]);

        migrate(base).unwrap();

        assert_eq!(read(dir_of(base, "lokal").join(LOCAL_FILE)), "{oops");
    }

    #[test]
    fn settings_that_do_not_parse_stop_the_migration_and_leave_all_be() {
        // Torn, and well-formed with a value no version wrote.
        for broken in ["{oops", r#"{"mode": "geheim"}"#] {
            let scratch = Scratch::new("settings-broken");
            let base = &scratch.0;
            legacy(base, &[(SETTINGS, broken), (LOCAL_FILE, LOCAL)]);
            let before = legacy_bytes(base);

            for _ in 0..2 {
                let error = migrate(base).unwrap_err().to_string();
                // The log line of the start names the file, and quotes nothing of it.
                assert!(error.starts_with("settings.json: "), "{error}");
                assert!(error.contains("line 1"), "{error}");
                assert!(!error.contains("geheim"), "{error}");
                assert_eq!(Registry::load(base).unwrap(), None, "{broken}");
                assert!(!base.join("workspaces").exists(), "{broken}");
                assert!(!base.join("prefs.json").exists(), "{broken}");
                assert_eq!(legacy_bytes(base), before, "{broken}");
            }
        }
    }

    #[test]
    fn a_registry_that_does_not_parse_still_counts_as_migrated() {
        // Registry::store writes in place on Windows: a crash there leaves it empty or torn. A
        // run that took that for "not migrated" would build the workspaces anew from the old
        // files, over what was done in them since.
        let scratch = Scratch::new("registry-torn");
        let base = &scratch.0;
        server_install(base);
        migrate(base).unwrap();
        let added_later = r#"[{"id":"mine"},{"id":"added-in-the-workspace"}]"#;
        fs::write(dir_of(base, "lokal").join(LOCAL_FILE), added_later).unwrap();
        let registry = fs::read(base.join(REGISTRY_FILE)).unwrap();

        for torn in [&registry[..0], &registry[..registry.len() / 2]] {
            fs::write(base.join(REGISTRY_FILE), torn).unwrap();
            let before = snapshot(base);

            migrate(base).unwrap();

            assert_eq!(snapshot(base), before);
            assert_eq!(read(dir_of(base, "lokal").join(LOCAL_FILE)), added_later);
        }
    }

    #[test]
    fn an_abort_after_any_step_ends_where_a_run_without_one_does() {
        let reference = Scratch::new("abort-reference");
        server_install(&reference.0);
        let mut steps = Vec::new();
        migrate_with(&reference.0, &mut |step| {
            steps.push(step.to_string());
            Ok(())
        })
        .unwrap();
        assert_eq!(
            steps,
            [
                "cleared",
                "built standard",
                "placed standard",
                "built lokal",
                "placed lokal",
                "built sync",
                "placed sync",
                "prefs",
                "ports",
            ]
        );
        let expected = snapshot(&reference.0);

        // An abort, then a second run that aborts too (or runs through), then a last run.
        for first in 0..steps.len() {
            for second in 0..=steps.len() {
                let after = format!(
                    "abort after {:?}, then after {:?}",
                    steps[first],
                    steps.get(second)
                );
                let scratch = Scratch::new(&format!("abort-{first}-{second}"));
                server_install(&scratch.0);
                let before = legacy_bytes(&scratch.0);

                assert!(run_aborting_at(&scratch.0, first).is_err(), "{after}");
                assert_eq!(Registry::load(&scratch.0).unwrap(), None, "{after}");
                assert_eq!(
                    run_aborting_at(&scratch.0, second).is_ok(),
                    second == steps.len(),
                    "{after}"
                );
                migrate(&scratch.0).unwrap();

                assert_eq!(snapshot(&scratch.0), expected, "{after}");
                assert_eq!(legacy_bytes(&scratch.0), before, "{after}");
            }
        }
    }

    #[test]
    fn leftovers_of_an_aborted_run_are_built_anew_and_other_workspaces_stay() {
        let plant_foreign = |base: &Path| {
            // A workspace that is no migration's: not touched.
            fs::create_dir_all(dir_of(base, "w-0a1b2c3d")).unwrap();
            fs::write(dir_of(base, "w-0a1b2c3d").join("keep"), "mine").unwrap();
        };
        let reference = Scratch::new("leftovers-reference");
        server_install(&reference.0);
        plant_foreign(&reference.0);
        migrate(&reference.0).unwrap();
        let expected = snapshot(&reference.0);

        let scratch = Scratch::new("leftovers");
        let base = &scratch.0;
        server_install(base);
        plant_foreign(base);
        for (path, content) in [
            ("workspaces/standard.partial/connections.json", "torn"),
            ("workspaces/standard/connections.json", "stale"),
            ("workspaces/standard/workspace.json", "{torn"),
            // A workspace of an earlier run that this one does not make.
            ("workspaces/server/workspace.json", "{}"),
            ("workspaces/lokal.partial/workspace.json", ""),
            ("prefs.json", "{torn"),
            ("prefs.json.tmp", "torn"),
            ("workspaces.json.tmp", "{torn"),
        ] {
            let path = base.join(path);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, content).unwrap();
        }
        fs::create_dir_all(dir_of(base, "sync.partial")).unwrap();

        migrate(base).unwrap();

        assert_eq!(snapshot(base), expected);
    }

    #[test]
    fn a_run_after_a_finished_one_changes_nothing_even_if_the_old_files_change() {
        let scratch = Scratch::new("again");
        let base = &scratch.0;
        server_install(base);
        migrate(base).unwrap();
        let migrated = snapshot(base);

        migrate(base).unwrap();
        assert_eq!(snapshot(base), migrated);

        // An older version, started in between, changes the old files: they are its own now.
        legacy(
            base,
            &[
                (SETTINGS, &settings(json!({"mode": "local"}))),
                (LOCAL_FILE, "[]"),
            ],
        );
        write_ports(base, &[(DEFAULT_OWNER, "web", 6002, 6002)]);
        let changed = snapshot(base);
        migrate(base).unwrap();
        assert_eq!(snapshot(base), changed);
        assert_eq!(
            Meta::load(&dir_of(base, "standard")).unwrap().kind,
            SyncMode::Server
        );
    }

    #[test]
    fn two_runs_at_once_end_in_one_result() {
        let reference = Scratch::new("concurrent-reference");
        server_install(&reference.0);
        migrate(&reference.0).unwrap();

        let scratch = Scratch::new("concurrent");
        server_install(&scratch.0);
        let start = Arc::new(Barrier::new(2));
        let runs: Vec<_> = (0..2)
            .map(|_| {
                let base = scratch.0.clone();
                let start = Arc::clone(&start);
                thread::spawn(move || {
                    start.wait();
                    migrate(&base)
                })
            })
            .collect();
        for run in runs {
            run.join().unwrap().unwrap();
        }

        assert_eq!(snapshot(&scratch.0), snapshot(&reference.0));
    }

    #[test]
    fn a_run_waits_for_the_lock_of_another() {
        let scratch = Scratch::new("lock");
        server_install(&scratch.0);
        let held = File::options()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(scratch.0.join(LOCK_FILE))
            .unwrap();
        held.lock().unwrap();

        let migrating = {
            let base = scratch.0.clone();
            thread::spawn(move || migrate(&base))
        };
        thread::sleep(Duration::from_millis(200));
        assert!(!migrating.is_finished(), "ran past the held lock");
        assert!(!scratch.0.join("workspaces").exists());

        held.unlock().unwrap();
        drop(held);
        migrating.join().unwrap().unwrap();
        assert_eq!(
            Registry::load(&scratch.0).unwrap(),
            Some(registry(&["standard", "lokal", "sync"]))
        );
    }

    #[test]
    fn the_server_workspace_takes_no_more_than_its_share_of_the_old_port_map() {
        let scratch = Scratch::new("port-share");
        let base = &scratch.0;
        legacy(base, &[(SETTINGS, SERVER_SETTINGS)]);
        // A map from before the caps of 500 visitors and 250 fallback ports (23000-23999) an
        // owner may hold: 300 fallback ports and 260 others.
        let names: Vec<String> = (0..560).map(|i| format!("v{i}")).collect();
        let mut entries = vec![("other", "ssh", 6000, 23999)];
        for (i, name) in (0u16..).zip(&names) {
            let local = if i < 300 { 23000 + i } else { 30000 + i };
            entries.push((DEFAULT_OWNER, name.as_str(), local, local));
        }
        write_ports(base, &entries);

        migrate(base).unwrap();

        let ports = ports_in(base);
        let standard: Vec<u16> = ports
            .iter()
            .filter(|(owner, _, _)| owner == "standard")
            .map(|&(_, _, local)| local)
            .collect();
        assert_eq!(standard.len(), 500);
        assert_eq!(
            standard
                .iter()
                .filter(|local| (23000..=23999).contains(*local))
                .count(),
            250
        );
        assert!(ports.contains(&port("other", "ssh", 23999)));
        assert!(ports.iter().all(|(owner, _, _)| owner != DEFAULT_OWNER));
    }
}
