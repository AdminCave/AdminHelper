// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! The launcher (R-0431): the workspaces the picker lists, the making, editing, opening and
//! deleting of a workspace, the purge a delete starts, the start of the launcher from a
//! workspace, and the port map entries no workspace owns any more. Once the migration made
//! `workspaces.json`, only the launcher writes it, and it never makes one: without it the
//! migration has not run, and a registry made here would keep the old data out of the
//! workspaces for good.

use std::collections::BTreeSet;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{mpsc, Mutex, MutexGuard, PoisonError};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use sha2::{Digest, Sha256};
use url::Origin;

use crate::enrollment::{self, ResetOutcome};
use crate::error::AppError;
use crate::keyring_store;
use crate::migration;
use crate::models::{Connection, Settings, SyncMode, WorkspaceDraft, WorkspaceList};
use crate::password;
use crate::port_registry::PortRegistry;
use crate::storage;
use crate::validation::{validate_https_url, validate_server_url_secure};
use crate::workspace::{
    self, acquire, failure, is_open, server_origin, Meta, Registry, RegistryEntry, Workspace,
    WorkspaceId, PALETTE, REGISTRY_FILE,
};

/// The longest name of a workspace, in characters.
const NAME_MAX_CHARS: usize = 40;

/// How long [`open`] waits for the workspace it started to hold its lock, and how often it looks.
const OPEN_TIMEOUT: Duration = Duration::from_secs(10);
const OPEN_PROBE: Duration = Duration::from_millis(200);

/// How long [`delete`] waits for the purge it started: the purge asks the server (connect and
/// read time out after 10 and 45 s) and the keyring, which can hang on a D-Bus that does.
const PURGE_TIMEOUT: Duration = Duration::from_secs(120);

/// The exit codes of a purge that deleted its workspace, one for each outcome of its revoke.
/// None of them is a code of a start that fails (`workspace::EXIT_*`), 0 (an app that ended as
/// apps do) or 101 (a panic): no other end of the purge reads as a delete.
const EXIT_REVOKED: i32 = 10;
const EXIT_LOCAL_ONLY: i32 = 11;
const EXIT_NOT_ENROLLED: i32 = 12;

/// Held for every read, change and write of `workspaces.json`. One launcher runs per device (the
/// single-instance plugin), but its commands run side by side: without the guard, a listing that
/// clears the migration note would write back a registry that lacks the workspace a save just
/// added.
static REGISTRY_GUARD: Mutex<()> = Mutex::new(());

fn registry_guard() -> MutexGuard<'static, ()> {
    // It guards no data in memory: a panic under it leaves nothing half changed.
    REGISTRY_GUARD
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
}

/// Held for every [`delete`], so the deletes of one launcher run one after the other. The purge
/// of a migrated workspace leaves the keys without a prefix to another migrated workspace while
/// there is one; two such purges side by side would each see the other, and the keys, the
/// device identity among them, would stay with no workspace and never be revoked. The file of
/// the RDP keys handed over has one writer this way, too.
static DELETE_GUARD: Mutex<()> = Mutex::new(());

/// The workspaces in the app data dir `base` with whether each is open, which one was used last,
/// and the notes on the migration that are due (that it happened, and the name of an unreadable
/// `settings.json` it set aside); each comes once, and the listing clears it. A registry entry
/// whose directory is gone (a delete that did not reach the registry), or whose `workspace.json`
/// does not load, is left out with a log line: one broken workspace must not leave the picker
/// empty. The latter stays a workspace all the same (its id stays taken, its ports stay).
pub fn list(base: &Path) -> Result<WorkspaceList, AppError> {
    let _guard = registry_guard();
    let mut registry = load_registry(base)?;
    let mut workspaces = Vec::with_capacity(registry.workspaces.len());
    for entry in &registry.workspaces {
        let ws = paths_of(&entry.id);
        let dir = ws.data_dir(base);
        if !dir.try_exists()? {
            log::warn!(
                "{REGISTRY_FILE} names the workspace {}, which has no directory; not listed",
                entry.id
            );
            continue;
        }
        let meta = match Meta::load(&dir) {
            Ok(meta) => meta,
            Err(e) => {
                log::warn!(
                    "the workspace.json of the workspace {} does not load ({}); not listed",
                    entry.id,
                    failure(&e)
                );
                continue;
            }
        };
        let open = is_open(&ws.lock_path(base))?;
        workspaces.push(meta.info(entry.id.clone(), open));
    }
    let migrated_notice = registry.migrated_notice;
    let unreadable_settings = registry.unreadable_settings.take();
    if migrated_notice || unreadable_settings.is_some() {
        registry.migrated_notice = false;
        registry.store(base)?;
    }
    let last_used = registry
        .last_used
        .filter(|id| workspaces.iter().any(|ws| ws.id == *id));
    Ok(WorkspaceList {
        workspaces,
        last_used,
        migrated_notice,
        unreadable_settings,
    })
}

/// Makes the workspace `draft` describes, or edits the one it names, and gives its id. A new
/// workspace has keyring keys of its own (`legacyKeys: false`). An edit takes the name, colour
/// and URL, only while the workspace is closed, never another kind, and no URL of another server
/// while the workspace has a device identity. The draft is checked here, without a network call.
pub fn save(base: &Path, draft: &WorkspaceDraft) -> Result<WorkspaceId, AppError> {
    let (name, url) = checked(draft)?;
    let _guard = registry_guard();
    let mut registry = load_registry(base)?;
    let Some(id) = &draft.id else {
        let defaults = Settings::default();
        let meta = Meta {
            kind: draft.kind.clone(),
            name,
            color: draft.color.clone(),
            url,
            interval_minutes: defaults.interval_minutes,
            allow_self_signed_certs: defaults.allow_self_signed_certs,
            last_username: None,
            legacy_keys: false,
        };
        return create(base, &mut registry, &meta);
    };
    edit(base, &registry, id, draft, name, url)
}

/// Drops the port map entries of every owner that is no workspace in the app data dir `base`:
/// one whose delete did not reach the map, or what an older version wrote after a downgrade.
/// For the start of the launcher, after the migration handed over the entries from before
/// workspaces; without a registry it is an error and drops nothing.
pub fn drop_orphan_ports(base: &Path) -> Result<(), AppError> {
    // Held throughout, so no workspace this launcher makes meanwhile loses its entries.
    let _guard = registry_guard();
    let registry = load_registry(base)?;
    let mut owners = Vec::with_capacity(registry.workspaces.len());
    for entry in &registry.workspaces {
        if paths_of(&entry.id).data_dir(base).try_exists()? {
            owners.push(entry.id.to_string());
        }
    }
    let owners: Vec<&str> = owners.iter().map(String::as_str).collect();
    PortRegistry::new(base).retain_owners(&owners)
}

/// Opens the workspace `id` of the app data dir `base` in a process of its own, which `spawner`
/// starts with `--workspace <id>`, and returns once that process holds the workspace's lock, so
/// the launcher can end without leaving the user with nothing. Blocks for up to
/// [`OPEN_TIMEOUT`]. An error, with nothing started, for a workspace that is open or that the
/// registry, its directory or its `workspace.json` does not make whole. Before the start the
/// registry names it as last used, so the picker selects it again whether it opens or not. An
/// error, too, if the process ends before it holds the lock or still holds none at the
/// deadline; such a process is left to run.
pub fn open(base: &Path, id: &WorkspaceId, spawner: &impl Spawner) -> Result<(), AppError> {
    open_within(base, id, spawner, OPEN_TIMEOUT, OPEN_PROBE)
}

/// [`open`], waiting up to `timeout` and looking every `probe`.
fn open_within(
    base: &Path,
    id: &WorkspaceId,
    spawner: &impl Spawner,
    timeout: Duration,
    probe: Duration,
) -> Result<(), AppError> {
    let lock = mark_opening(base, id)?;
    let mut child = spawner
        .spawn(&["--workspace", &id.to_string()])
        .map_err(|e| {
            AppError::Io(io::Error::new(
                e.kind(),
                format!("the workspace {id} did not start: {e}"),
            ))
        })?;
    let deadline = Instant::now() + timeout;
    loop {
        if is_open(&lock)? {
            return Ok(());
        }
        if let Some(status) = child.try_wait()? {
            return Err(AppError::Io(io::Error::other(format!(
                "the workspace {id} ended before it opened ({status})"
            ))));
        }
        let left = deadline.saturating_duration_since(Instant::now());
        if left.is_zero() {
            return Err(AppError::Io(io::Error::new(
                io::ErrorKind::TimedOut,
                format!("the workspace {id} did not open within {timeout:?}"),
            )));
        }
        thread::sleep(probe.min(left));
    }
}

/// Checks that the workspace `id` in `base` can be opened, names it as last used and gives the
/// path of its lock.
fn mark_opening(base: &Path, id: &WorkspaceId) -> Result<PathBuf, AppError> {
    let _guard = registry_guard();
    let mut registry = load_registry(base)?;
    let ws = paths_of(id);
    let dir = ws.data_dir(base);
    if !registry.workspaces.iter().any(|entry| entry.id == *id) || !dir.try_exists()? {
        return Err(AppError::Validation(format!("there is no workspace {id}")));
    }
    // The process would not start it either.
    if let Err(e) = Meta::load(&dir) {
        return Err(AppError::Validation(format!(
            "the workspace.json of the workspace {id} does not load ({}); it does not open",
            failure(&e)
        )));
    }
    let lock = ws.lock_path(base);
    if is_open(&lock)? {
        return Err(AppError::Validation(format!(
            "the workspace {id} is open already"
        )));
    }
    if registry.last_used.as_ref() != Some(id) {
        registry.last_used = Some(id.clone());
        registry.store(base)?;
    }
    Ok(lock)
}

/// Deletes the workspace `id` of the app data dir `base` and gives how its device identity
/// went. `spawner` starts the purge (`--workspace <id> --purge`, [`purge`]), a process of the
/// workspace's own: the keys and the identity hang on its keyring prefix, which the launcher
/// never takes. Blocks until the purge ends, for up to [`PURGE_TIMEOUT`]. Only the registry
/// entry is required: a workspace without its directory or with a `workspace.json` that does
/// not load is deleted all the same. An error, with nothing started, for a workspace that is
/// open or that the registry does not name; an error, too, for a purge that ends with no
/// outcome or not in time. The registry drops the workspace only after its purge: a purge that
/// fails leaves it there to delete again.
pub fn delete(
    base: &Path,
    id: &WorkspaceId,
    spawner: &impl Spawner,
) -> Result<ResetOutcome, AppError> {
    delete_within(base, id, spawner, PURGE_TIMEOUT, OPEN_PROBE)
}

/// [`delete`], waiting up to `timeout` and looking every `probe`.
fn delete_within(
    base: &Path,
    id: &WorkspaceId,
    spawner: &impl Spawner,
    timeout: Duration,
    probe: Duration,
) -> Result<ResetOutcome, AppError> {
    let _deleting = DELETE_GUARD.lock().unwrap_or_else(PoisonError::into_inner);
    check_deletable(base, id)?;
    let mut child = spawner
        .spawn(&["--workspace", &id.to_string(), "--purge"])
        .map_err(|e| {
            AppError::Io(io::Error::new(
                e.kind(),
                format!("the workspace {id} was not deleted: its purge did not start: {e}"),
            ))
        })?;
    let deadline = Instant::now() + timeout;
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        let left = deadline.saturating_duration_since(Instant::now());
        if left.is_zero() {
            return Err(AppError::Io(io::Error::new(
                io::ErrorKind::TimedOut,
                format!("the workspace {id} was not deleted within {timeout:?}"),
            )));
        }
        thread::sleep(probe.min(left));
    };
    let outcome = status.code().and_then(purge_outcome).ok_or_else(|| {
        AppError::Io(io::Error::other(format!(
            "the workspace {id} was not deleted ({status})"
        )))
    })?;
    unregister(base, id)?;
    Ok(outcome)
}

/// Checks that the registry in `base` names the workspace `id` and that it is closed.
fn check_deletable(base: &Path, id: &WorkspaceId) -> Result<(), AppError> {
    let _guard = registry_guard();
    let registry = load_registry(base)?;
    if !registry.workspaces.iter().any(|entry| entry.id == *id) {
        return Err(AppError::Validation(format!("there is no workspace {id}")));
    }
    if is_open(&paths_of(id).lock_path(base))? {
        return Err(AppError::Validation(format!(
            "the workspace {id} is open; close it to delete it"
        )));
    }
    Ok(())
}

/// Takes the workspace `id` out of the registry in `base`, and out of last used.
fn unregister(base: &Path, id: &WorkspaceId) -> Result<(), AppError> {
    let _guard = registry_guard();
    let mut registry = load_registry(base)?;
    registry.workspaces.retain(|entry| entry.id != *id);
    if registry.last_used.as_ref() == Some(id) {
        registry.last_used = None;
    }
    registry.store(base)
}

/// The exit code of a purge that deleted its workspace with `outcome`.
pub fn purge_exit_code(outcome: ResetOutcome) -> i32 {
    match outcome {
        ResetOutcome::Revoked => EXIT_REVOKED,
        ResetOutcome::LocalOnly => EXIT_LOCAL_ONLY,
        ResetOutcome::NotEnrolled => EXIT_NOT_ENROLLED,
    }
}

/// The outcome a purge that ended with `code` deleted its workspace with; none if it did not.
fn purge_outcome(code: i32) -> Option<ResetOutcome> {
    match code {
        EXIT_REVOKED => Some(ResetOutcome::Revoked),
        EXIT_LOCAL_ONLY => Some(ResetOutcome::LocalOnly),
        EXIT_NOT_ENROLLED => Some(ResetOutcome::NotEnrolled),
        _ => None,
    }
}

/// Deletes the workspace of this process, the purge child ([`delete`]); `base` is the app data
/// dir, `meta` its `workspace.json`, none if that does not load or the directory is gone. A
/// server workspace with a URL revokes its device first: `revoke` gets the URL and gives how
/// that went (`enrollment::reset_identity` at a real purge); without a server to ask, an
/// identity goes here only (`LocalOnly`). Then its identity, its RDP keys, the index, its port
/// map entries and its directory go. The index goes on its own, once its keys
/// are deleted or handed over, and the directory last: a purge that stopped on the way runs
/// again. What names keys to delete or hand over is read before anything changes: a name that is
/// no RDP key of this workspace, or a file of names that does not load, stops the purge before it
/// revokes or deletes a thing.
///
/// A migrated workspace keeps its keys without a prefix, as every migrated one does. Its
/// identity is that of a server: another migrated workspace of the same installation shares
/// it, and then the purge revokes nothing and leaves it be (`NotEnrolled`: no identity of its
/// own). Its RDP keys may be any migrated workspace's: while another one is there, the purge
/// hands them over, and the purge of the last migrated workspace deletes them with its own.
/// Its keys are those its index names and those from before workspaces that no index names
/// but its connections do (`password::unindexed_keys`); a connections file that does not load
/// stops the purge, too.
pub fn purge(
    base: &Path,
    meta: Option<&Meta>,
    revoke: impl FnOnce(&str) -> Result<ResetOutcome, AppError>,
) -> Result<ResetOutcome, AppError> {
    let ws = workspace::current()?;
    let dir = ws.data_dir(base);
    let mut rdp_keys = password::indexed_keys(&dir, &ws.keyring_prefix())?;
    if ws.legacy_keys {
        rdp_keys.extend(password::unindexed_keys(&ws, &connections_in(&dir, meta)?));
    }
    let (identity_shared, keys_shared) = if ws.legacy_keys {
        let others = other_migrated(base, &ws.id)?;
        let own = meta.and_then(server_origin);
        let identity_shared = others
            .iter()
            .any(|other| shares_identity(own.as_ref(), other.as_ref()));
        (identity_shared, !others.is_empty())
    } else {
        (false, false)
    };
    // The keys handed over before: the last migrated workspace deletes them, any other adds its
    // own. Read here with the rest, so a file that does not load stops the purge before the
    // revoke; a purge that hands over no key leaves the file unread.
    let handed_over = if ws.legacy_keys && !(keys_shared && rdp_keys.is_empty()) {
        password::handed_over_keys(base)?
    } else {
        BTreeSet::new()
    };

    let outcome = if identity_shared {
        ResetOutcome::NotEnrolled
    } else {
        let outcome = match meta {
            Some(Meta {
                kind: SyncMode::Server,
                url: Some(url),
                ..
            }) => revoke(url)?,
            _ if enrollment::is_enrolled() => ResetOutcome::LocalOnly,
            _ => ResetOutcome::NotEnrolled,
        };
        // After the revoke, which remembers a leaf it could not revoke for an enrollment
        // that does not come now.
        enrollment::purge_identity()?;
        outcome
    };
    if keys_shared {
        password::hand_over_keys(base, handed_over, &rdp_keys)?;
    } else {
        for key in rdp_keys.iter().chain(&handed_over) {
            keyring_store::delete(key)?;
        }
        if ws.legacy_keys {
            password::forget_handed_over_keys(base)?;
        }
    }
    password::remove_index(&dir)?;
    PortRegistry::new(base).release(&ws.id.to_string())?;
    match fs::remove_dir_all(&dir) {
        Err(e) if e.kind() != io::ErrorKind::NotFound => Err(e.into()),
        _ => Ok(outcome),
    }
}

/// The migrated workspaces in `base` other than `id`, each with its `workspace.json`; none for
/// one whose `workspace.json` does not load, which counts as migrated by its id. A workspace
/// whose directory is gone counts no more: its purge has run.
fn other_migrated(base: &Path, id: &WorkspaceId) -> Result<Vec<Option<Meta>>, AppError> {
    let registry = load_registry(base).map_err(|e| unreadable(REGISTRY_FILE, e))?;
    let mut others = Vec::new();
    for entry in registry.workspaces.iter().filter(|entry| entry.id != *id) {
        let dir = paths_of(&entry.id).data_dir(base);
        if !dir.try_exists()? {
            continue;
        }
        match Meta::load(&dir) {
            Ok(meta) if meta.legacy_keys => others.push(Some(meta)),
            Ok(_) => {}
            Err(_) if migration::is_migration_id(&entry.id) => others.push(None),
            Err(_) => {}
        }
    }
    Ok(others)
}

/// Whether the identity without a prefix may be that of `other`, a migrated workspace beside
/// the one purged, whose server origin is `own`: `other` is a server workspace of the same
/// installation, or of any while `own` is not known, or one whose `workspace.json` does not
/// load.
fn shares_identity(own: Option<&Origin>, other: Option<&Meta>) -> bool {
    let Some(other) = other else {
        return true;
    };
    server_origin(other).is_some_and(|theirs| own.is_none_or(|own| *own == theirs))
}

/// The connections in `dir`, the data dir of the workspace purged, whose `workspace.json` is
/// `meta`: those in the file of its kind, as the workspace reads them, or in either file while
/// its kind is not known; none without the file. A file that does not load is an error.
fn connections_in(dir: &Path, meta: Option<&Meta>) -> Result<Vec<Connection>, AppError> {
    let files = match meta {
        Some(meta) => vec![storage::connections_file_name(&meta.kind)],
        None => vec![
            storage::connections_file_name(&SyncMode::Local),
            storage::connections_file_name(&SyncMode::Server),
        ],
    };
    let mut connections = Vec::new();
    for file in files {
        match fs::read(dir.join(file)) {
            Ok(bytes) => connections.extend(
                serde_json::from_slice::<Vec<Connection>>(&bytes)
                    .map_err(|e| unreadable(file, e.into()))?,
            ),
            Err(e) if e.kind() == io::ErrorKind::NotFound => {}
            Err(e) => return Err(e.into()),
        }
    }
    Ok(connections)
}

/// `e` from loading `file`, as a log line may say it: the file and where it breaks, never a
/// value from it (serde quotes the values it rejects).
fn unreadable(file: &str, e: AppError) -> AppError {
    match e {
        AppError::Json(_) => {
            AppError::Validation(format!("{file} does not load ({})", failure(&e)))
        }
        e => e,
    }
}

/// Starts the launcher, for "Workspaces…" in a workspace process: `spawner` starts this program
/// without arguments. If a launcher runs already, the new one hands over to it and ends (the
/// single-instance plugin), so nothing here waits for it.
pub fn open_launcher(spawner: &impl Spawner) -> Result<(), AppError> {
    spawner.spawn(&[]).map_err(|e| {
        AppError::Io(io::Error::new(
            e.kind(),
            format!("the launcher did not start: {e}"),
        ))
    })?;
    Ok(())
}

/// Starts this program anew with the arguments it is given, detached from this process. A
/// trait, so [`open`] and [`open_launcher`] run in tests without a process.
pub trait Spawner {
    type Child: Spawned;

    fn spawn(&self, args: &[&str]) -> io::Result<Self::Child>;
}

/// A program a [`Spawner`] started.
pub trait Spawned {
    /// How it ended, if it has; never waits.
    fn try_wait(&mut self) -> io::Result<Option<ExitStatus>>;
}

/// The real one: `program`, detached.
pub struct AppSpawner {
    program: PathBuf,
}

impl AppSpawner {
    /// The spawner of this program ([`std::env::current_exe`]).
    pub fn new() -> io::Result<Self> {
        Ok(Self {
            program: std::env::current_exe()?,
        })
    }
}

/// The process creation flags `DETACHED_PROCESS` and `CREATE_NEW_PROCESS_GROUP`
/// (`Win32::System::Threading`), spelled out as plain `u32`s for `CommandExt::creation_flags`.
#[cfg(windows)]
const DETACHED_PROCESS: u32 = 0x0000_0008;
#[cfg(windows)]
const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;

impl Spawner for AppSpawner {
    type Child = DetachedChild;

    /// Starts the program so that it outlives this process and shares nothing with it: its stdio
    /// goes to null, and it gets a process group of its own (on Windows no console either), so
    /// a Ctrl-C meant for this process does not end it.
    fn spawn(&self, args: &[&str]) -> io::Result<DetachedChild> {
        let mut command = Command::new(&self.program);
        command
            .args(args)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        #[cfg(unix)]
        std::os::unix::process::CommandExt::process_group(&mut command, 0);
        #[cfg(windows)]
        std::os::windows::process::CommandExt::creation_flags(
            &mut command,
            DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        );
        let mut child = command.spawn()?;
        let (ended, end) = mpsc::channel();
        // Waited for on a thread of its own: one that ends while this process runs on (the
        // launcher a workspace started) leaves no zombie behind, whether anyone asks or not.
        thread::spawn(move || {
            let _ = ended.send(child.wait());
        });
        Ok(DetachedChild { end, status: None })
    }
}

/// A program [`AppSpawner`] started.
pub struct DetachedChild {
    end: mpsc::Receiver<io::Result<ExitStatus>>,
    status: Option<ExitStatus>,
}

impl Spawned for DetachedChild {
    fn try_wait(&mut self) -> io::Result<Option<ExitStatus>> {
        if self.status.is_none() {
            match self.end.try_recv() {
                Ok(ended) => self.status = Some(ended?),
                Err(mpsc::TryRecvError::Empty) => {}
                // The waiter is gone without a word: it panicked.
                Err(mpsc::TryRecvError::Disconnected) => {
                    return Err(io::Error::other("lost track of the started program"))
                }
            }
        }
        Ok(self.status)
    }
}

/// The registry in `base`. Without one the migration has not run; the launcher never makes it.
fn load_registry(base: &Path) -> Result<Registry, AppError> {
    Registry::load(base)?.ok_or_else(|| {
        AppError::Io(io::Error::new(
            io::ErrorKind::NotFound,
            format!(
                "no {REGISTRY_FILE} in {}: the data has not been moved into workspaces yet",
                base.display()
            ),
        ))
    })
}

/// The workspace `id` for its paths, which hang on the id alone.
fn paths_of(id: &WorkspaceId) -> Workspace {
    Workspace {
        id: id.clone(),
        name: String::new(),
        legacy_keys: false,
    }
}

/// Where the data dir `dir` is built before it gets its name; no workspace id holds a `.`.
fn partial(dir: &Path) -> PathBuf {
    let mut partial = dir.as_os_str().to_owned();
    partial.push(".partial");
    PathBuf::from(partial)
}

/// The name and URL of `draft` as a workspace keeps them: trimmed, a blank URL none. An error
/// for a name, colour or URL the workspace cannot take.
fn checked(draft: &WorkspaceDraft) -> Result<(String, Option<String>), AppError> {
    if draft.name.chars().any(char::is_control) {
        return Err(AppError::Validation(
            "a workspace name holds no control characters".to_string(),
        ));
    }
    let name = draft.name.trim();
    if !(1..=NAME_MAX_CHARS).contains(&name.chars().count()) {
        return Err(AppError::Validation(format!(
            "a workspace name has 1 to {NAME_MAX_CHARS} characters"
        )));
    }
    if !PALETTE.contains(&draft.color.as_str()) {
        return Err(AppError::Validation(
            "a workspace takes one of the colours of the palette".to_string(),
        ));
    }
    let url = draft
        .url
        .as_deref()
        .map(str::trim)
        .filter(|url| !url.is_empty());
    match (&draft.kind, url) {
        (_, None) => {}
        (SyncMode::Server, Some(url)) => validate_server_url_secure(url)?,
        (SyncMode::Sync, Some(url)) => validate_https_url(url)?,
        (SyncMode::Local, Some(_)) => {
            return Err(AppError::Validation(
                "a local workspace has no URL".to_string(),
            ))
        }
    }
    Ok((name.to_string(), url.map(String::from)))
}

/// Builds the new workspace `meta` describes in a directory of its own, names it and adds it to
/// `registry`. Until the registry names it, no process opens it, and a build that fails leaves
/// nothing behind.
fn create(base: &Path, registry: &mut Registry, meta: &Meta) -> Result<WorkspaceId, AppError> {
    let id = new_id(|id| is_taken(base, registry, id))?;
    let dir = paths_of(&id).data_dir(base);
    let partial = partial(&dir);
    make_private_dir(&partial)?;
    let placed = meta
        .store(&partial)
        .and_then(|()| fs::rename(&partial, &dir).map_err(AppError::from));
    if placed.is_err() {
        let _ = fs::remove_dir_all(&partial);
    }
    placed?;
    registry.workspaces.push(RegistryEntry { id: id.clone() });
    if let Err(e) = registry.store(base) {
        let _ = fs::remove_dir_all(&dir);
        return Err(e);
    }
    Ok(id)
}

/// Gives the workspace `id` the `name` and `url` checked from `draft`, and its colour. A `url`
/// that is the URL of the workspace as the webview got it (`workspace::shown_url`, none for a
/// URL that does not parse) keeps the URL it has. Its lock is held until the edit is written: no
/// process opens the workspace in between.
fn edit(
    base: &Path,
    registry: &Registry,
    id: &WorkspaceId,
    draft: &WorkspaceDraft,
    name: String,
    url: Option<String>,
) -> Result<WorkspaceId, AppError> {
    let ws = paths_of(id);
    let dir = ws.data_dir(base);
    if !registry.workspaces.iter().any(|entry| entry.id == *id) || !dir.try_exists()? {
        return Err(AppError::Validation(format!("there is no workspace {id}")));
    }
    let Some(_lock) = acquire(&ws.lock_path(base))? else {
        return Err(AppError::Validation(format!(
            "the workspace {id} is open; close it to edit it"
        )));
    };
    let meta = workspace::load_meta(id, &dir)?;
    if meta.kind != draft.kind {
        return Err(AppError::Validation(
            "the kind of a workspace stays as it was made".to_string(),
        ));
    }
    // The editor sends the URL back as it got it when the user left it alone; taken as it is,
    // the user, the query and the fragment the webview never saw would be lost.
    let url = if url == meta.url.as_deref().and_then(workspace::shown_url) {
        meta.url.clone()
    } else {
        url
    };
    let edited = Meta {
        name,
        color: draft.color.clone(),
        url,
        ..meta.clone()
    };
    // A purge revokes the identity at the URL the workspace has then: another server would be
    // asked to revoke what it never issued, and its yes would read as a revoke.
    if edited.url != meta.url && server_origin(&edited) != server_origin(&meta) {
        let ws = Workspace {
            id: id.clone(),
            name: meta.name.clone(),
            legacy_keys: meta.legacy_keys,
        };
        if enrollment::holds_identity(&ws.keyring_prefix())? {
            return Err(AppError::Validation(format!(
                "the workspace {id} has a device identity of its server; reset the identity in \
                 the workspace before its URL names another server, or make a new workspace"
            )));
        }
    }
    if edited != meta {
        edited.store(&dir)?;
    }
    Ok(id.clone())
}

/// Whether `id` is in use in `base`: named by `registry`, or with a directory, finished or not,
/// that a failed run may have left.
fn is_taken(base: &Path, registry: &Registry, id: &WorkspaceId) -> Result<bool, AppError> {
    let dir = paths_of(id).data_dir(base);
    Ok(registry.workspaces.iter().any(|entry| entry.id == *id)
        || dir.try_exists()?
        || partial(&dir).try_exists()?)
}

/// Feeds every candidate id: no two in one process hash the same input.
static ID_SEQUENCE: AtomicU64 = AtomicU64::new(0);

/// The first id `w-<8 hex>` that `taken` lets pass.
fn new_id(taken: impl Fn(&WorkspaceId) -> Result<bool, AppError>) -> Result<WorkspaceId, AppError> {
    loop {
        let id = id_candidate()?;
        if !taken(&id)? {
            return Ok(id);
        }
    }
}

/// `w-` and the first 8 hex digits of a hash of the time, the pid and a sequence. Two launchers,
/// or two calls of one, hash different input; 32 bits can still collide, which [`new_id`]
/// catches.
fn id_candidate() -> Result<WorkspaceId, AppError> {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |since| since.as_nanos());
    let mut hash = Sha256::new();
    hash.update(nanos.to_le_bytes());
    hash.update(std::process::id().to_le_bytes());
    hash.update(ID_SEQUENCE.fetch_add(1, Ordering::Relaxed).to_le_bytes());
    let digest = hash.finalize();
    let head = u32::from_be_bytes([digest[0], digest[1], digest[2], digest[3]]);
    WorkspaceId::parse(&format!("w-{head:08x}"))
}

/// Makes `dir`, which must not be there yet, and any parent it lacks; 0700 on Unix, as nothing
/// in a workspace is for other users.
fn make_private_dir(dir: &Path) -> io::Result<()> {
    let mut builder = fs::DirBuilder::new();
    #[cfg(unix)]
    std::os::unix::fs::DirBuilderExt::mode(&mut builder, 0o700);
    if let Some(parent) = dir.parent() {
        builder.recursive(true).create(parent)?;
    }
    builder.recursive(false).create(dir)
}

#[cfg(test)]
mod tests {
    use std::cell::{Cell, RefCell};
    use std::fs;
    use std::io;
    use std::path::{Path, PathBuf};
    use std::process::ExitStatus;
    use std::rc::Rc;
    use std::time::{Duration, Instant};

    use super::{
        delete, delete_within, drop_orphan_ports, is_taken, list, new_id, open, open_launcher,
        open_within, purge, purge_exit_code, purge_outcome, save, server_origin, shares_identity,
        Spawned, Spawner, WorkspaceDraft, WorkspaceId, WorkspaceList,
    };
    use crate::enrollment::{self, ResetOutcome};
    use crate::error::AppError;
    use crate::keyring_store;
    use crate::models::{Connection, ConnectionKind, Settings, SyncMode};
    use crate::password::load_password_keyring;
    use crate::workspace::{
        self, acquire, is_open, startup, InstanceLock, Meta, Registry, RegistryEntry, EXIT_FAILED,
        EXIT_TAKEN, EXIT_UNKNOWN, PALETTE, REGISTRY_FILE,
    };

    /// A directory of its own for one test case under the system temp dir, gone with the guard.
    struct Scratch(PathBuf);

    impl Scratch {
        fn new(case: &str) -> Self {
            let dir =
                std::env::temp_dir().join(format!("ah-launcher-{case}-{}", std::process::id()));
            let _ = fs::remove_dir_all(&dir);
            fs::create_dir_all(&dir).unwrap();
            Self(dir)
        }
    }

    impl Drop for Scratch {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    const PORT_MAP: &str = "port-registry.json";

    fn id(id: &str) -> WorkspaceId {
        WorkspaceId::parse(id).unwrap()
    }

    /// The data dir of the workspace `id` in `base`, spelled out rather than taken from the code
    /// under test.
    fn dir_of(base: &Path, id: &str) -> PathBuf {
        base.join("workspaces").join(id)
    }

    fn lock_of(base: &Path, id: &str) -> PathBuf {
        dir_of(base, id).join("instance.lock")
    }

    /// A workspace as the migration or an earlier edit left it, with every field off the
    /// defaults of a new one.
    fn meta(kind: SyncMode, name: &str, url: Option<&str>) -> Meta {
        Meta {
            kind,
            name: name.to_string(),
            color: PALETTE[0].to_string(),
            url: url.map(String::from),
            interval_minutes: 7,
            allow_self_signed_certs: true,
            last_username: Some("admin".to_string()),
            legacy_keys: true,
        }
    }

    /// Lays out `base` as the migration and earlier launches left it: a data dir for each of
    /// `workspaces`, the registry naming them in that order, the first one last used.
    fn install(base: &Path, workspaces: &[(&str, Meta)], migrated_notice: bool) {
        for (ws, meta) in workspaces {
            meta.store(&dir_of(base, ws)).unwrap();
        }
        Registry {
            workspaces: workspaces
                .iter()
                .map(|(ws, _)| RegistryEntry { id: id(ws) })
                .collect(),
            last_used: workspaces.first().map(|(ws, _)| id(ws)),
            migrated_notice,
            unreadable_settings: None,
        }
        .store(base)
        .unwrap();
    }

    fn registry_of(base: &Path) -> Registry {
        Registry::load(base).unwrap().expect("a registry")
    }

    fn registry_bytes(base: &Path) -> Vec<u8> {
        fs::read(base.join(REGISTRY_FILE)).unwrap()
    }

    /// The names in `base/workspaces`, sorted; none if there is no such dir.
    fn workspace_dirs(base: &Path) -> Vec<String> {
        let Ok(entries) = fs::read_dir(base.join("workspaces")) else {
            return Vec::new();
        };
        let mut names: Vec<String> = entries
            .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
            .collect();
        names.sort();
        names
    }

    /// A listed workspace as (id, name, colour, kind, host, open).
    type Listed = (String, String, String, SyncMode, Option<String>, bool);

    fn listed(list: &WorkspaceList) -> Vec<Listed> {
        list.workspaces
            .iter()
            .map(|ws| {
                (
                    ws.id.to_string(),
                    ws.name.clone(),
                    ws.color.clone(),
                    ws.kind.clone(),
                    ws.host.clone(),
                    ws.open,
                )
            })
            .collect()
    }

    fn row(id: &str, name: &str, kind: SyncMode, host: Option<&str>, open: bool) -> Listed {
        (
            id.to_string(),
            name.to_string(),
            PALETTE[0].to_string(),
            kind,
            host.map(String::from),
            open,
        )
    }

    fn draft(kind: SyncMode, name: &str, url: Option<&str>) -> WorkspaceDraft {
        WorkspaceDraft {
            id: None,
            kind,
            name: name.to_string(),
            color: PALETTE[3].to_string(),
            url: url.map(String::from),
        }
    }

    fn assert_new_id(id: &WorkspaceId) {
        let id = id.to_string();
        let hex = id.strip_prefix("w-").unwrap_or_else(|| panic!("{id}"));
        assert!(
            hex.len() == 8 && hex.bytes().all(|b| b"0123456789abcdef".contains(&b)),
            "{id}"
        );
    }

    #[cfg(unix)]
    fn assert_private_dir(path: &Path) {
        use std::os::unix::fs::PermissionsExt;
        let mode = fs::metadata(path).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o700, "{}", path.display());
    }

    #[cfg(not(unix))]
    fn assert_private_dir(_path: &Path) {}

    fn assert_validation_error<T: std::fmt::Debug>(result: Result<T, AppError>, case: &str) {
        assert!(
            matches!(result, Err(AppError::Validation(_))),
            "{case}: {result:?}"
        );
    }

    #[test]
    fn list_names_each_workspace_and_whether_it_is_open() {
        let scratch = Scratch::new("list");
        let base = &scratch.0;
        install(
            base,
            &[
                (
                    "standard",
                    meta(
                        SyncMode::Server,
                        "Standard",
                        Some("https://AH.example.com:8443/x"),
                    ),
                ),
                ("lokal", meta(SyncMode::Local, "Lokal", None)),
                (
                    "sync",
                    meta(
                        SyncMode::Sync,
                        "Sync",
                        Some("https://sync.example.com/c.json"),
                    ),
                ),
                ("server", meta(SyncMode::Server, "Server", None)),
            ],
            false,
        );
        let held = acquire(&lock_of(base, "sync")).unwrap().unwrap();

        let listing = list(base).unwrap();

        assert_eq!(
            listed(&listing),
            [
                row(
                    "standard",
                    "Standard",
                    SyncMode::Server,
                    Some("ah.example.com"),
                    false
                ),
                row("lokal", "Lokal", SyncMode::Local, None, false),
                row(
                    "sync",
                    "Sync",
                    SyncMode::Sync,
                    Some("sync.example.com"),
                    true
                ),
                row("server", "Server", SyncMode::Server, None, false),
            ]
        );
        assert_eq!(listing.last_used, Some(id("standard")));
        assert!(!listing.migrated_notice);
        // The probe took nothing from the holder.
        assert!(is_open(&lock_of(base, "sync")).unwrap());

        drop(held);
        assert!(listed(&list(base).unwrap()).iter().all(|ws| !ws.5));
    }

    #[test]
    fn list_gives_the_migration_note_exactly_once() {
        let scratch = Scratch::new("notice");
        let base = &scratch.0;
        install(
            base,
            &[("standard", meta(SyncMode::Local, "Standard", None))],
            true,
        );
        let before = registry_of(base);

        assert!(list(base).unwrap().migrated_notice);
        assert!(!list(base).unwrap().migrated_notice);
        assert_eq!(
            registry_of(base),
            Registry {
                migrated_notice: false,
                ..before
            }
        );
        // With no note due, a listing writes nothing.
        let quiet = registry_bytes(base);
        assert!(!list(base).unwrap().migrated_notice);
        assert_eq!(registry_bytes(base), quiet);
    }

    #[test]
    fn list_names_the_settings_the_migration_set_aside_exactly_once() {
        let scratch = Scratch::new("set-aside");
        let base = &scratch.0;
        fs::write(base.join("settings.json"), "{torn").unwrap();
        crate::migration::migrate(base).unwrap();
        let before = registry_of(base);
        let name = before.unreadable_settings.clone().expect("a name");
        // The name alone, in the app data dir, with the UTC time of the run.
        let stamp = name
            .strip_prefix("settings.json.unreadable-")
            .expect("the name of the settings");
        assert!(
            chrono::NaiveDateTime::parse_from_str(stamp, "%Y%m%dT%H%M%SZ").is_ok(),
            "{name}"
        );
        assert_eq!(fs::read_to_string(base.join(&name)).unwrap(), "{torn");

        let listing = list(base).unwrap();

        assert_eq!(listing.unreadable_settings.as_deref(), Some(name.as_str()));
        assert!(listing.migrated_notice);
        let wire = serde_json::to_value(&listing).unwrap();
        assert_eq!(wire["unreadableSettings"], serde_json::json!(name));
        assert_eq!(list(base).unwrap().unreadable_settings, None);
        assert_eq!(
            registry_of(base),
            Registry {
                migrated_notice: false,
                unreadable_settings: None,
                ..before
            }
        );
    }

    #[test]
    fn list_leaves_out_a_registry_entry_without_a_directory() {
        let scratch = Scratch::new("no-dir");
        let base = &scratch.0;
        install(
            base,
            &[("standard", meta(SyncMode::Local, "Standard", None))],
            false,
        );
        Registry {
            workspaces: vec![
                RegistryEntry { id: id("gone") },
                RegistryEntry { id: id("standard") },
            ],
            last_used: Some(id("gone")),
            migrated_notice: false,
            unreadable_settings: None,
        }
        .store(base)
        .unwrap();

        let listing = list(base).unwrap();

        assert_eq!(
            listed(&listing),
            [row("standard", "Standard", SyncMode::Local, None, false)]
        );
        assert_eq!(
            listing.last_used, None,
            "the picker selects no workspace it lacks"
        );
        assert!(!dir_of(base, "gone").exists());
    }

    #[test]
    fn list_leaves_out_a_workspace_whose_meta_does_not_load_and_keeps_it_otherwise() {
        let scratch = Scratch::new("broken-meta");
        let base = &scratch.0;
        install(
            base,
            &[
                ("broken", meta(SyncMode::Server, "Broken", None)),
                ("standard", meta(SyncMode::Local, "Standard", None)),
                ("bare", meta(SyncMode::Local, "Bare", None)),
            ],
            false,
        );
        let broken_meta = dir_of(base, "broken").join("workspace.json");
        fs::write(&broken_meta, "{not json").unwrap();
        fs::remove_file(dir_of(base, "bare").join("workspace.json")).unwrap();
        let registry = registry_bytes(base);

        let listing = list(base).unwrap();

        assert_eq!(
            listed(&listing),
            [row("standard", "Standard", SyncMode::Local, None, false)]
        );
        assert_eq!(
            listing.last_used, None,
            "the last used one is the broken one"
        );
        assert_eq!(registry_bytes(base), registry);

        // Left out of the list, it is still a workspace: its id stays taken, its ports stay, and
        // an edit fails without writing.
        for ws in ["broken", "bare"] {
            assert!(is_taken(base, &registry_of(base), &id(ws)).unwrap(), "{ws}");
            let mut edit = draft(SyncMode::Local, "Kunde A", None);
            edit.id = Some(id(ws));
            assert!(save(base, &edit).is_err(), "{ws}");
        }
        assert_eq!(fs::read_to_string(&broken_meta).unwrap(), "{not json");
        assert!(!dir_of(base, "bare").join("workspace.json").exists());
        write_port_map(
            base,
            &[
                ("standard", "ssh", 6000),
                ("broken", "ssh", 23000),
                ("bare", "rdp", 23001),
            ],
        );
        drop_orphan_ports(base).unwrap();
        assert_eq!(port_owners(base), ["standard", "broken", "bare"]);
        assert_eq!(registry_bytes(base), registry);
    }

    #[test]
    fn save_makes_a_workspace_of_each_kind() {
        let scratch = Scratch::new("create");
        let base = &scratch.0;
        install(
            base,
            &[("standard", meta(SyncMode::Local, "Standard", None))],
            true,
        );
        let defaults = Settings::default();
        for (kind, url, kept, host) in [
            (
                SyncMode::Server,
                Some(" https://ah.example.com "),
                Some("https://ah.example.com"),
                Some("ah.example.com"),
            ),
            (
                SyncMode::Server,
                Some("http://127.0.0.1:8000"),
                Some("http://127.0.0.1:8000"),
                Some("127.0.0.1"),
            ),
            (SyncMode::Server, None, None, None),
            (
                SyncMode::Sync,
                Some("https://sync.example.com/c.json"),
                Some("https://sync.example.com/c.json"),
                Some("sync.example.com"),
            ),
            (SyncMode::Sync, Some("  "), None, None),
            (SyncMode::Local, None, None, None),
        ] {
            let case = format!("{kind:?} {url:?}");
            let before = registry_of(base);

            let made = save(base, &draft(kind.clone(), "  Kunde A  ", url)).unwrap();

            assert_new_id(&made);
            let dir = dir_of(base, &made.to_string());
            assert_eq!(
                Meta::load(&dir).unwrap(),
                Meta {
                    kind: kind.clone(),
                    name: "Kunde A".to_string(),
                    color: PALETTE[3].to_string(),
                    url: kept.map(String::from),
                    interval_minutes: defaults.interval_minutes,
                    allow_self_signed_certs: defaults.allow_self_signed_certs,
                    last_username: None,
                    legacy_keys: false,
                },
                "{case}"
            );
            assert_private_dir(&dir);
            // Appended, and nothing else in the registry changed.
            let mut expected = before.clone();
            expected.workspaces.push(RegistryEntry { id: made.clone() });
            assert_eq!(registry_of(base), expected, "{case}");
            assert!(
                workspace_dirs(base)
                    .iter()
                    .all(|name| !name.ends_with(".partial")),
                "{case}: {:?}",
                workspace_dirs(base)
            );
            let listing = list(base).unwrap();
            let new = listing
                .workspaces
                .iter()
                .find(|ws| ws.id == made)
                .unwrap_or_else(|| panic!("{case}: not listed"));
            assert_eq!(new.host.as_deref(), host, "{case}");
            assert!(!new.open, "{case}");
        }
    }

    /// Gives `path` the Unix `mode` until it drops, then 0700 again.
    #[cfg(unix)]
    struct Mode<'a>(&'a Path);

    #[cfg(unix)]
    impl<'a> Mode<'a> {
        fn set(path: &'a Path, mode: u32) -> Self {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(path, fs::Permissions::from_mode(mode)).unwrap();
            Self(path)
        }
    }

    #[cfg(unix)]
    impl Drop for Mode<'_> {
        fn drop(&mut self) {
            use std::os::unix::fs::PermissionsExt;
            let _ = fs::set_permissions(self.0, fs::Permissions::from_mode(0o700));
        }
    }

    #[cfg(unix)]
    #[test]
    fn save_takes_back_a_new_workspace_the_registry_does_not_take() {
        let scratch = Scratch::new("create-undo");
        let base = &scratch.0;
        install(
            base,
            &[("standard", meta(SyncMode::Local, "Standard", None))],
            false,
        );
        let registry = registry_bytes(base);
        let dirs = workspace_dirs(base);
        // The app data dir turns read-only, `workspaces/` stays writable: the workspace is built
        // and named, then the registry cannot be written.
        let _read_only = Mode::set(base, 0o500);
        assert!(
            fs::write(base.join("probe"), b"").is_err(),
            "{} stays writable: this test needs a user bound by file modes (not root)",
            base.display()
        );

        assert!(save(base, &draft(SyncMode::Local, "Kunde A", None)).is_err());

        assert_eq!(workspace_dirs(base), dirs);
        assert_eq!(registry_bytes(base), registry);
    }

    #[test]
    fn save_refuses_what_a_workspace_cannot_take_and_changes_nothing() {
        let scratch = Scratch::new("invalid");
        let base = &scratch.0;
        install(
            base,
            &[("standard", meta(SyncMode::Local, "Standard", None))],
            false,
        );
        let registry = registry_bytes(base);
        let dirs = workspace_dirs(base);
        let longest = "ä".repeat(40);
        let too_long = "a".repeat(41);
        let mut cases = Vec::new();
        for name in [
            "",
            "   ",
            too_long.as_str(),
            "Kun\nde",
            "Kunde\u{7}",
            "\u{0}",
            "\tKunde",
        ] {
            cases.push((format!("name {name:?}"), draft(SyncMode::Local, name, None)));
        }
        for color in ["", "blue", "#000000", "#3B82F6", " #3b82f6"] {
            let mut bad = draft(SyncMode::Local, "Kunde A", None);
            bad.color = color.to_string();
            cases.push((format!("colour {color:?}"), bad));
        }
        for (kind, url) in [
            (SyncMode::Server, "http://ah.example.com"),
            (SyncMode::Server, "ftp://ah.example.com"),
            (SyncMode::Server, "ah.example.com"),
            (SyncMode::Sync, "http://sync.example.com/c.json"),
            (SyncMode::Sync, "http://127.0.0.1/c.json"),
            (SyncMode::Sync, "not a url"),
            (SyncMode::Local, "https://ah.example.com"),
        ] {
            cases.push((
                format!("{kind:?} url {url:?}"),
                draft(kind, "Kunde A", Some(url)),
            ));
        }

        for (case, bad) in cases {
            assert_validation_error(save(base, &bad), &case);
            assert_eq!(registry_bytes(base), registry, "{case}");
            assert_eq!(workspace_dirs(base), dirs, "{case}");
        }
        // The edges hold: 40 characters, however many bytes.
        assert_new_id(&save(base, &draft(SyncMode::Local, &longest, None)).unwrap());
    }

    #[test]
    fn save_edits_name_colour_and_url_of_a_closed_workspace_and_keeps_the_rest() {
        let scratch = Scratch::new("edit");
        let base = &scratch.0;
        let before = meta(SyncMode::Server, "Standard", Some("https://ah.example.com"));
        install(base, &[("standard", before.clone())], false);
        let registry = registry_bytes(base);

        let edited = save(
            base,
            &WorkspaceDraft {
                id: Some(id("standard")),
                kind: SyncMode::Server,
                name: " Kunde A ".to_string(),
                color: PALETTE[5].to_string(),
                url: Some("https://other.example.com".to_string()),
            },
        )
        .unwrap();

        assert_eq!(edited, id("standard"));
        assert_eq!(
            Meta::load(&dir_of(base, "standard")).unwrap(),
            Meta {
                name: "Kunde A".to_string(),
                color: PALETTE[5].to_string(),
                url: Some("https://other.example.com".to_string()),
                ..before
            }
        );
        assert_eq!(registry_bytes(base), registry);
        // The lock went with the edit.
        assert!(!is_open(&lock_of(base, "standard")).unwrap());
    }

    #[test]
    fn save_refuses_to_edit_an_open_workspace() {
        let scratch = Scratch::new("edit-open");
        let base = &scratch.0;
        let before = meta(SyncMode::Server, "Standard", Some("https://ah.example.com"));
        install(base, &[("standard", before.clone())], false);
        let held = acquire(&lock_of(base, "standard")).unwrap().unwrap();

        let result = save(
            base,
            &WorkspaceDraft {
                id: Some(id("standard")),
                kind: SyncMode::Server,
                name: "Kunde A".to_string(),
                color: PALETTE[0].to_string(),
                url: Some("https://ah.example.com".to_string()),
            },
        );

        assert_validation_error(result, "open");
        assert_eq!(Meta::load(&dir_of(base, "standard")).unwrap(), before);
        assert!(is_open(&lock_of(base, "standard")).unwrap());
        drop(held);
    }

    #[test]
    fn save_keeps_the_kind_and_edits_no_workspace_it_does_not_know() {
        let scratch = Scratch::new("edit-kind");
        let base = &scratch.0;
        let before = meta(SyncMode::Server, "Standard", Some("https://ah.example.com"));
        install(base, &[("standard", before.clone())], false);
        // Named by the registry, its directory gone.
        let mut registry = registry_of(base);
        registry.workspaces.push(RegistryEntry { id: id("gone") });
        registry.store(base).unwrap();
        // A directory the registry does not name.
        meta(SyncMode::Local, "Stray", None)
            .store(&dir_of(base, "w-00000000"))
            .unwrap();
        let registry = registry_bytes(base);

        let edit = |ws: &str, kind: SyncMode| {
            save(
                base,
                &WorkspaceDraft {
                    id: Some(id(ws)),
                    kind,
                    name: "Kunde A".to_string(),
                    color: PALETTE[0].to_string(),
                    url: None,
                },
            )
        };

        assert_validation_error(edit("standard", SyncMode::Local), "other kind");
        assert_validation_error(edit("gone", SyncMode::Server), "no directory");
        assert_validation_error(edit("w-00000000", SyncMode::Local), "not registered");
        assert_validation_error(edit("w-11111111", SyncMode::Local), "unknown");
        assert_eq!(Meta::load(&dir_of(base, "standard")).unwrap(), before);
        assert_eq!(registry_bytes(base), registry);
        assert!(!dir_of(base, "gone").exists());
        assert!(!dir_of(base, "w-11111111").exists());
    }

    #[test]
    fn login_binding_the_url_of_a_workspace_with_a_device_identity_keeps_its_server() {
        let scratch = Scratch::new("edit-identity");
        let base = &scratch.0;
        let _keyring = keyring_store::memory();
        let url = "https://ah.example.com";
        let enrolled = created(SyncMode::Server, "Kunde A", Some(url));
        let fresh = created(SyncMode::Server, "Kunde B", Some(url));
        let first = created(SyncMode::Server, "Kunde C", None);
        let migrated = meta(SyncMode::Server, "Standard", Some(url));
        install(
            base,
            &[
                ("w-0000000a", enrolled.clone()),
                ("w-0000000b", fresh),
                ("w-0000000c", first.clone()),
                ("standard", migrated.clone()),
            ],
            false,
        );
        store(&behind(&prefix_of("w-0000000a"), &IDENTITY[..3]));
        // What a crash between the writes of an enrollment left: an identity all the same.
        store(&behind(&prefix_of("w-0000000c"), &["enroll|ca"]));
        // The identity from before workspaces, which the migrated workspace keeps.
        store(&behind("", &["enroll|key", "enroll|cert"]));
        // The leaf a reset remembers is none.
        store(&behind(&prefix_of("w-0000000b"), &["enroll|replaces"]));
        let edit = |ws: &str, name: &str, url: Option<&str>| {
            save(
                base,
                &WorkspaceDraft {
                    id: Some(id(ws)),
                    kind: SyncMode::Server,
                    name: name.to_string(),
                    color: PALETTE[0].to_string(),
                    url: url.map(String::from),
                },
            )
        };
        let refused = |result: Result<WorkspaceId, AppError>, ws: &str, case: &str| {
            assert!(
                matches!(&result, Err(AppError::Validation(msg))
                    if msg.contains(&format!("the workspace {ws} has a device identity"))),
                "{ws} {case}: {result:?}"
            );
        };

        // Another server, or none, would take the revoke of its purge: refused, nothing written.
        for other in [
            Some("https://other.example.com"),
            Some("https://ah.example.com:8443"),
            Some("http://localhost"),
            None,
        ] {
            refused(
                edit("w-0000000a", "Kunde A", other),
                "w-0000000a",
                &format!("{other:?}"),
            );
            refused(
                edit("standard", "Standard", other),
                "standard",
                &format!("{other:?}"),
            );
        }
        // The first URL names a server as well: the identity may be another one's.
        refused(
            edit("w-0000000c", "Kunde C", Some(url)),
            "w-0000000c",
            "first",
        );
        assert_eq!(Meta::load(&dir_of(base, "w-0000000a")).unwrap(), enrolled);
        assert_eq!(Meta::load(&dir_of(base, "standard")).unwrap(), migrated);
        assert_eq!(Meta::load(&dir_of(base, "w-0000000c")).unwrap(), first);

        // The same server, however the URL names it, and a new name: taken.
        edit(
            "w-0000000a",
            "Kunde A2",
            Some("https://AH.example.com:443/x"),
        )
        .unwrap();
        assert_eq!(
            Meta::load(&dir_of(base, "w-0000000a")).unwrap(),
            Meta {
                name: "Kunde A2".to_string(),
                url: Some("https://AH.example.com:443/x".to_string()),
                ..enrolled
            }
        );
        // Without an identity, another server is taken.
        edit("w-0000000b", "Kunde B", Some("https://other.example.com")).unwrap();
        assert_eq!(
            Meta::load(&dir_of(base, "w-0000000b"))
                .unwrap()
                .url
                .as_deref(),
            Some("https://other.example.com")
        );
        for ws in ["w-0000000a", "w-0000000b", "w-0000000c", "standard"] {
            assert!(!is_open(&lock_of(base, ws)).unwrap(), "{ws}");
        }
    }

    #[test]
    fn login_binding_an_edit_of_a_workspace_json_that_does_not_load_names_no_value() {
        let scratch = Scratch::new("edit-broken");
        let base = &scratch.0;
        install(
            base,
            &[("standard", meta(SyncMode::Server, "Standard", None))],
            false,
        );
        let path = dir_of(base, "standard").join("workspace.json");
        fs::write(&path, r#"{"kind": "geheim"}"#).unwrap();
        let mut edit = draft(SyncMode::Server, "Kunde A", None);
        edit.id = Some(id("standard"));

        let refused = save(base, &edit).unwrap_err().to_string();

        assert!(
            refused.starts_with("the workspace.json of the workspace standard does not load")
                && refused.contains("line 1"),
            "{refused}"
        );
        assert!(!refused.contains("geheim"), "{refused}");
        assert_eq!(fs::read_to_string(&path).unwrap(), r#"{"kind": "geheim"}"#);
    }

    #[test]
    fn save_keeps_the_workspace_url_the_editor_sends_back_as_shown() {
        let scratch = Scratch::new("edit-shown");
        let base = &scratch.0;
        let _keyring = keyring_store::memory();
        let sync = created(
            SyncMode::Sync,
            "Sync",
            Some("https://reader:pw@sync.example.com/c.json?token=abc&v=2#frag"),
        );
        let server = meta(
            SyncMode::Server,
            "Standard",
            Some("https://admin@ah.example.com/base?tenant=t1"),
        );
        // What a migration may have taken over: a URL the parser does not read.
        let unparsed = created(
            SyncMode::Server,
            "Alt",
            Some("https://admin:secret@ah example.com"),
        );
        let plain = created(SyncMode::Server, "Plain", Some("https://AH.example.com"));
        let password = created(
            SyncMode::Server,
            "Kennwort",
            Some("https://:secret@ah2.example.com/"),
        );
        let workspaces = [
            ("w-0000000a", sync),
            ("standard", server),
            ("w-0000000b", unparsed.clone()),
            ("w-0000000c", plain),
            ("w-0000000d", password),
        ];
        install(base, &workspaces, false);

        // What the editor gets.
        let shown: Vec<Option<String>> = list(base)
            .unwrap()
            .workspaces
            .into_iter()
            .map(|ws| ws.url)
            .collect();
        assert_eq!(
            shown,
            [
                Some("https://***@sync.example.com/c.json?token=***&v=***#***".to_string()),
                Some("https://***@ah.example.com/base?tenant=***".to_string()),
                None,
                Some("https://AH.example.com".to_string()),
                Some("https://***@ah2.example.com/".to_string()),
            ]
        );

        // Sent back as it came, with another name and colour: the URL stays as kept, the user
        // and the password, the token and the fragment with it, and the one that does not parse
        // as well.
        for ((ws, before), url) in workspaces.iter().zip(shown) {
            save(
                base,
                &WorkspaceDraft {
                    id: Some(id(ws)),
                    kind: before.kind.clone(),
                    name: "Neu".to_string(),
                    color: PALETTE[5].to_string(),
                    url,
                },
            )
            .unwrap();
            assert_eq!(
                Meta::load(&dir_of(base, ws)).unwrap(),
                Meta {
                    name: "Neu".to_string(),
                    color: PALETTE[5].to_string(),
                    ..before.clone()
                },
                "{ws}"
            );
        }
        // A blank URL is none, too.
        save(
            base,
            &WorkspaceDraft {
                id: Some(id("w-0000000b")),
                kind: SyncMode::Server,
                name: "Alt".to_string(),
                color: PALETTE[0].to_string(),
                url: Some("  ".to_string()),
            },
        )
        .unwrap();
        assert_eq!(Meta::load(&dir_of(base, "w-0000000b")).unwrap(), unparsed);
    }

    #[test]
    fn save_replaces_a_changed_workspace_url_and_drops_a_blank_one() {
        let scratch = Scratch::new("edit-changed");
        let base = &scratch.0;
        let _keyring = keyring_store::memory();
        let before = created(
            SyncMode::Sync,
            "Sync",
            Some("https://reader:pw@sync.example.com/c.json?token=abc"),
        );
        install(base, &[("w-0000000a", before.clone())], false);
        let edit = |url: Option<&str>| {
            before.store(&dir_of(base, "w-0000000a")).unwrap();
            save(
                base,
                &WorkspaceDraft {
                    id: Some(id("w-0000000a")),
                    kind: SyncMode::Sync,
                    name: "Sync".to_string(),
                    color: PALETTE[0].to_string(),
                    url: url.map(String::from),
                },
            )
            .unwrap();
            Meta::load(&dir_of(base, "w-0000000a")).unwrap().url
        };

        assert_eq!(
            edit(Some("https://sync.example.com/c.json?token=def")).as_deref(),
            Some("https://sync.example.com/c.json?token=def")
        );
        // A masked value in another URL is taken as sent: nothing of the old URL is carried over.
        assert_eq!(
            edit(Some("https://sync.example.com/d.json?token=***")).as_deref(),
            Some("https://sync.example.com/d.json?token=***")
        );
        assert_eq!(edit(None), None);
        assert_eq!(edit(Some("  ")), None);
    }

    #[test]
    fn save_checks_the_identity_for_a_changed_workspace_url_as_before() {
        let scratch = Scratch::new("edit-shown-identity");
        let base = &scratch.0;
        let _keyring = keyring_store::memory();
        let enrolled = created(
            SyncMode::Server,
            "Kunde A",
            Some("https://admin@ah.example.com/?k=v"),
        );
        let unparsed = created(
            SyncMode::Server,
            "Alt",
            Some("https://admin:secret@ah example.com"),
        );
        install(
            base,
            &[
                ("w-0000000a", enrolled.clone()),
                ("w-0000000b", unparsed.clone()),
            ],
            false,
        );
        for ws in ["w-0000000a", "w-0000000b"] {
            store(&behind(&prefix_of(ws), &IDENTITY[..3]));
        }
        let edit = |ws: &str, url: Option<&str>| {
            save(
                base,
                &WorkspaceDraft {
                    id: Some(id(ws)),
                    kind: SyncMode::Server,
                    name: "Neu".to_string(),
                    color: PALETTE[0].to_string(),
                    url: url.map(String::from),
                },
            )
        };
        let refused = |result: Result<WorkspaceId, AppError>, ws: &str, case: &str| {
            assert!(
                matches!(&result, Err(AppError::Validation(msg))
                    if msg.contains(&format!("the workspace {ws} has a device identity"))),
                "{ws} {case}: {result:?}"
            );
        };

        // Another server, or none, with the masked query or without: refused, nothing written.
        for other in [
            Some("https://other.example.com/?k=***"),
            Some("https://ah.example.com:8443/?k=***"),
            None,
        ] {
            refused(
                edit("w-0000000a", other),
                "w-0000000a",
                &format!("{other:?}"),
            );
        }
        // A URL the parser reads names a server the one it does not read may not be.
        refused(
            edit("w-0000000b", Some("https://ah.example.com")),
            "w-0000000b",
            "parsed",
        );
        assert_eq!(Meta::load(&dir_of(base, "w-0000000a")).unwrap(), enrolled);
        assert_eq!(Meta::load(&dir_of(base, "w-0000000b")).unwrap(), unparsed);

        // Sent back as shown: the URL stays as kept.
        edit("w-0000000a", Some("https://***@ah.example.com/?k=***")).unwrap();
        edit("w-0000000b", None).unwrap();
        assert_eq!(
            Meta::load(&dir_of(base, "w-0000000a")).unwrap(),
            Meta {
                name: "Neu".to_string(),
                ..enrolled
            }
        );
        assert_eq!(
            Meta::load(&dir_of(base, "w-0000000b")).unwrap(),
            Meta {
                name: "Neu".to_string(),
                ..unparsed
            }
        );

        // The same server under another URL: taken, the user and the query go with the old one.
        edit("w-0000000a", Some("https://ah.example.com/x")).unwrap();
        assert_eq!(
            Meta::load(&dir_of(base, "w-0000000a"))
                .unwrap()
                .url
                .as_deref(),
            Some("https://ah.example.com/x")
        );
    }

    #[test]
    fn save_gives_every_new_workspace_an_id_of_its_own() {
        let scratch = Scratch::new("ids");
        let base = &scratch.0;
        install(
            base,
            &[("standard", meta(SyncMode::Local, "Standard", None))],
            false,
        );

        let made: Vec<WorkspaceId> = (0..20)
            .map(|i| save(base, &draft(SyncMode::Local, &format!("W{i}"), None)).unwrap())
            .collect();

        for (i, made_id) in made.iter().enumerate() {
            assert_new_id(made_id);
            assert!(!made[..i].contains(made_id), "{made_id} twice");
        }
        let mut expected = vec![id("standard")];
        expected.extend(made);
        let registered: Vec<WorkspaceId> = registry_of(base)
            .workspaces
            .into_iter()
            .map(|entry| entry.id)
            .collect();
        assert_eq!(registered, expected);
    }

    #[test]
    fn saves_and_listings_side_by_side_lose_no_workspace() {
        let scratch = Scratch::new("side-by-side");
        let base = scratch.0.clone();
        install(
            &base,
            &[("standard", meta(SyncMode::Local, "Standard", None))],
            true,
        );

        // The commands of one launcher: some make workspaces while others list, the first
        // listing clearing the note.
        let threads: Vec<_> = (0..8)
            .map(|t| {
                let base = base.clone();
                std::thread::spawn(move || {
                    let mut made = Vec::new();
                    for i in 0..5 {
                        if t % 2 == 0 {
                            let name = format!("W{t}-{i}");
                            made.push(save(&base, &draft(SyncMode::Local, &name, None)).unwrap());
                        } else {
                            list(&base).unwrap();
                        }
                    }
                    made
                })
            })
            .collect();
        let made: Vec<WorkspaceId> = threads
            .into_iter()
            .flat_map(|thread| thread.join().unwrap())
            .collect();

        let registry = registry_of(&base);
        assert_eq!(registry.workspaces.len(), 1 + made.len());
        for made_id in &made {
            assert!(
                registry.workspaces.iter().any(|entry| entry.id == *made_id),
                "{made_id} fell out of the registry"
            );
        }
        assert!(!registry.migrated_notice);
    }

    #[test]
    fn new_id_passes_over_the_ids_taken() {
        let seen = RefCell::new(Vec::new());

        let fresh = new_id(|candidate| {
            seen.borrow_mut().push(candidate.clone());
            Ok(seen.borrow().len() <= 3)
        })
        .unwrap();

        let seen = seen.into_inner();
        assert_eq!(seen.len(), 4);
        assert_eq!(seen[3], fresh);
        assert_new_id(&fresh);
        for (i, candidate) in seen.iter().enumerate() {
            assert!(!seen[..i].contains(candidate), "{candidate} twice");
        }
        // An error of the check ends the search.
        assert!(new_id(|_| Err(AppError::Validation("broken".to_string()))).is_err());
    }

    #[test]
    fn an_id_is_taken_by_the_registry_a_directory_or_a_partial_one() {
        let scratch = Scratch::new("taken");
        let base = &scratch.0;
        install(
            base,
            &[("w-0a1b2c3d", meta(SyncMode::Local, "Kunde A", None))],
            false,
        );
        let mut registry = registry_of(base);
        registry.workspaces.push(RegistryEntry {
            id: id("w-00000001"),
        });
        fs::create_dir_all(dir_of(base, "w-00000002")).unwrap();
        fs::create_dir_all(base.join("workspaces").join("w-00000003.partial")).unwrap();

        for (ws, taken) in [
            ("w-0a1b2c3d", true),
            ("w-00000001", true),
            ("w-00000002", true),
            ("w-00000003", true),
            ("w-00000004", false),
        ] {
            assert_eq!(is_taken(base, &registry, &id(ws)).unwrap(), taken, "{ws}");
        }
    }

    /// Makes the port map in `base` hold exactly `entries`, each (owner, visitor, local port).
    fn write_port_map(base: &Path, entries: &[(&str, &str, u16)]) {
        let entries: Vec<serde_json::Value> = entries
            .iter()
            .map(|&(owner, visitor, local_port)| {
                serde_json::json!({
                    "owner": owner,
                    "visitor": visitor,
                    "serverPort": 6000,
                    "localPort": local_port,
                })
            })
            .collect();
        fs::write(
            base.join(PORT_MAP),
            serde_json::to_vec(&serde_json::json!({ "entries": entries })).unwrap(),
        )
        .unwrap();
    }

    /// The owners in the port map in `base`, in its order.
    fn port_owners(base: &Path) -> Vec<String> {
        let map: serde_json::Value =
            serde_json::from_slice(&fs::read(base.join(PORT_MAP)).unwrap()).unwrap();
        map["entries"]
            .as_array()
            .unwrap()
            .iter()
            .map(|entry| entry["owner"].as_str().unwrap().to_string())
            .collect()
    }

    #[test]
    fn drop_orphan_ports_keeps_only_the_entries_of_workspaces_there_are() {
        let scratch = Scratch::new("orphans");
        let base = &scratch.0;
        install(
            base,
            &[
                ("standard", meta(SyncMode::Server, "Standard", None)),
                ("w-0a1b2c3d", meta(SyncMode::Server, "Kunde A", None)),
            ],
            false,
        );
        // Named by the registry, its directory gone: deleted.
        let mut registry = registry_of(base);
        registry.workspaces.push(RegistryEntry {
            id: id("w-deadbeef"),
        });
        registry.store(base).unwrap();
        // A directory the registry does not name: no workspace.
        meta(SyncMode::Server, "Stray", None)
            .store(&dir_of(base, "w-00000000"))
            .unwrap();
        write_port_map(
            base,
            &[
                ("standard", "ssh", 6000),
                ("w-deadbeef", "ssh", 23000),
                ("w-0a1b2c3d", "ssh", 23001),
                ("w-00000000", "ssh", 23002),
                ("default", "rdp", 6001),
                ("standard", "rdp", 23003),
            ],
        );

        drop_orphan_ports(base).unwrap();

        assert_eq!(port_owners(base), ["standard", "w-0a1b2c3d", "standard"]);
    }

    #[test]
    fn without_a_registry_nothing_is_listed_made_or_dropped() {
        let scratch = Scratch::new("no-registry");
        let base = &scratch.0;
        // Data from before the migration: the port map still has the old owner.
        fs::write(base.join("settings.json"), r#"{"mode":"server"}"#).unwrap();
        write_port_map(base, &[("default", "ssh", 6000)]);
        let port_map = fs::read(base.join(PORT_MAP)).unwrap();
        let mut edit = draft(SyncMode::Local, "Kunde A", None);
        edit.id = Some(id("standard"));

        assert!(list(base).is_err());
        assert!(save(base, &draft(SyncMode::Local, "Kunde A", None)).is_err());
        assert!(save(base, &edit).is_err());
        assert!(drop_orphan_ports(base).is_err());

        assert!(
            !base.join(REGISTRY_FILE).exists(),
            "the launcher made a registry"
        );
        assert!(!base.join("workspaces").exists());
        assert_eq!(fs::read(base.join(PORT_MAP)).unwrap(), port_map);
    }

    /// What a started program does while [`open`] waits for it, counted in the looks it gets.
    #[derive(Clone, Copy)]
    enum Course {
        /// Takes the lock of its workspace at this look and keeps it.
        TakesLockAt(u32),
        /// Ends at this look, the lock never held.
        EndsAt(u32),
        /// Ends at the first look with this exit code, as a purge does.
        ExitsWith(i32),
        /// Neither ends nor takes the lock.
        Hangs,
    }

    /// Starts no process: notes the arguments of every start and hands out a child that runs
    /// `course`; without a course, a start fails.
    struct FakeSpawner {
        base: PathBuf,
        course: Option<Course>,
        starts: RefCell<Vec<Vec<String>>>,
        /// The looks the child of the last start got.
        looks: Rc<Cell<u32>>,
    }

    impl FakeSpawner {
        fn new(base: &Path, course: Option<Course>) -> Self {
            Self {
                base: base.to_path_buf(),
                course,
                starts: RefCell::new(Vec::new()),
                looks: Rc::new(Cell::new(0)),
            }
        }

        fn starts(&self) -> Vec<Vec<String>> {
            self.starts.borrow().clone()
        }
    }

    struct FakeChild {
        /// The lock of the workspace it was started for; the launcher has none.
        lock: Option<PathBuf>,
        course: Course,
        looks: Rc<Cell<u32>>,
        held: Option<InstanceLock>,
    }

    impl Spawner for FakeSpawner {
        type Child = FakeChild;

        fn spawn(&self, args: &[&str]) -> io::Result<FakeChild> {
            self.starts
                .borrow_mut()
                .push(args.iter().map(|arg| arg.to_string()).collect());
            let course = self
                .course
                .ok_or_else(|| io::Error::from(io::ErrorKind::NotFound))?;
            // As the workspace process does: its lock follows from the id it was given.
            let lock = match args {
                ["--workspace", ws] => Some(lock_of(&self.base, ws)),
                _ => None,
            };
            self.looks.set(0);
            Ok(FakeChild {
                lock,
                course,
                looks: Rc::clone(&self.looks),
                held: None,
            })
        }
    }

    impl Spawned for FakeChild {
        fn try_wait(&mut self) -> io::Result<Option<ExitStatus>> {
            let look = self.looks.get() + 1;
            self.looks.set(look);
            match self.course {
                Course::TakesLockAt(at) if look >= at && self.held.is_none() => {
                    let lock = self.lock.as_ref().expect("started for a workspace");
                    self.held = Some(acquire(lock).unwrap().expect("the lock is free"));
                }
                Course::EndsAt(at) if look >= at => return Ok(Some(ExitStatus::default())),
                Course::ExitsWith(code) => return Ok(Some(exit_status(code))),
                _ => {}
            }
            Ok(None)
        }
    }

    /// How a program reads that ended with `code`.
    #[cfg(unix)]
    fn exit_status(code: i32) -> ExitStatus {
        std::os::unix::process::ExitStatusExt::from_raw(code << 8)
    }

    #[cfg(windows)]
    fn exit_status(code: i32) -> ExitStatus {
        std::os::windows::process::ExitStatusExt::from_raw(code as u32)
    }

    /// Short enough for a test, long enough to see each look.
    const PROBE: Duration = Duration::from_millis(10);

    /// `standard` (last used) and `w-0a1b2c3d`, both closed.
    fn install_two(base: &Path) {
        install(
            base,
            &[
                ("standard", meta(SyncMode::Local, "Standard", None)),
                (
                    "w-0a1b2c3d",
                    meta(SyncMode::Server, "Kunde A", Some("https://ah.example.com")),
                ),
            ],
            true,
        );
    }

    #[test]
    fn open_starts_the_workspace_and_returns_once_it_holds_its_lock() {
        let scratch = Scratch::new("open");
        let base = &scratch.0;
        install_two(base);
        let before = registry_of(base);
        let spawner = FakeSpawner::new(base, Some(Course::TakesLockAt(3)));

        open_within(
            base,
            &id("w-0a1b2c3d"),
            &spawner,
            Duration::from_secs(1),
            PROBE,
        )
        .unwrap();

        assert_eq!(spawner.starts(), [["--workspace", "w-0a1b2c3d"]]);
        // It looked until the lock was held, and no longer.
        assert_eq!(spawner.looks.get(), 3);
        assert_eq!(
            registry_of(base),
            Registry {
                last_used: Some(id("w-0a1b2c3d")),
                ..before
            }
        );
    }

    #[test]
    fn open_refuses_an_open_workspace_and_starts_nothing() {
        let scratch = Scratch::new("open-open");
        let base = &scratch.0;
        install_two(base);
        let registry = registry_bytes(base);
        let held = acquire(&lock_of(base, "w-0a1b2c3d")).unwrap().unwrap();
        let spawner = FakeSpawner::new(base, Some(Course::TakesLockAt(1)));

        assert_validation_error(open(base, &id("w-0a1b2c3d"), &spawner), "open");

        assert!(spawner.starts().is_empty(), "{:?}", spawner.starts());
        assert_eq!(registry_bytes(base), registry, "last used changed");
        assert!(is_open(&lock_of(base, "w-0a1b2c3d")).unwrap());
        drop(held);
    }

    #[test]
    fn open_starts_no_workspace_it_does_not_know_or_that_does_not_load() {
        let scratch = Scratch::new("open-unknown");
        let base = &scratch.0;
        install(
            base,
            &[
                ("standard", meta(SyncMode::Local, "Standard", None)),
                ("broken", meta(SyncMode::Server, "Broken", None)),
                ("bare", meta(SyncMode::Local, "Bare", None)),
            ],
            false,
        );
        fs::write(dir_of(base, "broken").join("workspace.json"), "{not json").unwrap();
        fs::remove_file(dir_of(base, "bare").join("workspace.json")).unwrap();
        // Named by the registry, its directory gone.
        let mut registry = registry_of(base);
        registry.workspaces.push(RegistryEntry { id: id("gone") });
        registry.store(base).unwrap();
        // A directory the registry does not name.
        meta(SyncMode::Local, "Stray", None)
            .store(&dir_of(base, "w-00000000"))
            .unwrap();
        let registry = registry_bytes(base);
        let spawner = FakeSpawner::new(base, Some(Course::TakesLockAt(1)));

        for ws in ["broken", "bare", "gone", "w-00000000", "w-11111111"] {
            assert_validation_error(open(base, &id(ws), &spawner), ws);
        }

        assert!(spawner.starts().is_empty(), "{:?}", spawner.starts());
        assert_eq!(registry_bytes(base), registry, "last used changed");
        assert!(!dir_of(base, "gone").exists());
        assert!(!dir_of(base, "w-11111111").exists());

        // Without a registry the data has not been moved into workspaces yet.
        let unmigrated = Scratch::new("open-unmigrated");
        assert!(open(&unmigrated.0, &id("standard"), &spawner).is_err());
        assert!(spawner.starts().is_empty(), "{:?}", spawner.starts());
        assert!(!unmigrated.0.join(REGISTRY_FILE).exists());
    }

    #[test]
    fn open_fails_at_once_when_the_workspace_ends_before_it_holds_its_lock() {
        let scratch = Scratch::new("open-ends");
        let base = &scratch.0;
        install_two(base);
        let spawner = FakeSpawner::new(base, Some(Course::EndsAt(1)));
        // Far above the scheduling jitter of a CI runner (1.4 s was seen against 900 ms), still
        // red when the wait runs into the deadline.
        let timeout = Duration::from_secs(10);
        let started = Instant::now();

        let result = open_within(base, &id("w-0a1b2c3d"), &spawner, timeout, PROBE);

        let waited = started.elapsed();
        match result {
            Err(AppError::Io(e)) => assert_ne!(e.kind(), io::ErrorKind::TimedOut, "{e}"),
            other => panic!("expected the end as an error, got {other:?}"),
        }
        assert!(waited < timeout, "waited {waited:?} for the deadline");
        assert_eq!(spawner.looks.get(), 1);
        assert_eq!(spawner.starts(), [["--workspace", "w-0a1b2c3d"]]);
        assert!(!is_open(&lock_of(base, "w-0a1b2c3d")).unwrap());
    }

    #[test]
    fn open_gives_up_on_a_workspace_that_holds_no_lock_in_time() {
        let scratch = Scratch::new("open-hangs");
        let base = &scratch.0;
        install_two(base);
        let spawner = FakeSpawner::new(base, Some(Course::Hangs));
        let timeout = Duration::from_millis(100);
        let started = Instant::now();

        let result = open_within(
            base,
            &id("w-0a1b2c3d"),
            &spawner,
            timeout,
            Duration::from_millis(20),
        );

        let waited = started.elapsed();
        assert!(
            matches!(&result, Err(AppError::Io(e)) if e.kind() == io::ErrorKind::TimedOut),
            "{result:?}"
        );
        assert!(waited >= timeout, "gave up after {waited:?}");
        assert!(
            waited < Duration::from_millis(900),
            "gave up after {waited:?}"
        );
        // It kept looking until the deadline.
        assert!(spawner.looks.get() >= 2, "{} looks", spawner.looks.get());
    }

    #[test]
    fn open_launcher_starts_this_program_without_arguments_and_waits_for_nothing() {
        let scratch = Scratch::new("open-launcher");
        let spawner = FakeSpawner::new(&scratch.0, Some(Course::Hangs));

        open_launcher(&spawner).unwrap();

        assert_eq!(spawner.starts(), [Vec::<String>::new()]);
        assert_eq!(spawner.looks.get(), 0, "it waited for the launcher");
    }

    #[test]
    fn a_start_that_fails_is_an_error() {
        let scratch = Scratch::new("open-fails");
        let base = &scratch.0;
        install_two(base);
        let spawner = FakeSpawner::new(base, None);

        assert!(matches!(
            open(base, &id("w-0a1b2c3d"), &spawner),
            Err(AppError::Io(_))
        ));
        assert!(matches!(open_launcher(&spawner), Err(AppError::Io(_))));
        assert_eq!(
            spawner.starts(),
            [vec!["--workspace", "w-0a1b2c3d"], Vec::<&str>::new()]
        );
    }

    // ── Delete: the launcher starts the purge and waits for its exit code ──

    const OUTCOMES: [ResetOutcome; 3] = [
        ResetOutcome::Revoked,
        ResetOutcome::LocalOnly,
        ResetOutcome::NotEnrolled,
    ];

    fn purge_args(ws: &str) -> Vec<String> {
        ["--workspace", ws, "--purge"].map(String::from).into()
    }

    #[test]
    fn purge_exit_codes_stand_apart_from_every_other_end_of_a_process() {
        let codes = OUTCOMES.map(purge_exit_code);
        for (i, outcome) in OUTCOMES.into_iter().enumerate() {
            assert_eq!(purge_outcome(codes[i]), Some(outcome));
            assert!(!codes[..i].contains(&codes[i]), "{outcome:?}");
        }
        // A start that fails, an app that ended as apps do, a panic.
        for code in [EXIT_FAILED, EXIT_UNKNOWN, EXIT_TAKEN, 0, 101, -1] {
            assert_eq!(purge_outcome(code), None, "{code}");
        }
    }

    #[test]
    fn delete_takes_the_workspace_out_of_the_registry_once_its_purge_says_how_it_went() {
        for outcome in OUTCOMES {
            let scratch = Scratch::new("delete");
            let base = &scratch.0;
            install_two(base);
            let before = registry_of(base);
            let spawner = FakeSpawner::new(base, Some(Course::ExitsWith(purge_exit_code(outcome))));

            assert_eq!(delete(base, &id("w-0a1b2c3d"), &spawner).unwrap(), outcome);

            assert_eq!(spawner.starts(), [purge_args("w-0a1b2c3d")]);
            assert_eq!(
                registry_of(base),
                Registry {
                    workspaces: vec![RegistryEntry { id: id("standard") }],
                    ..before.clone()
                },
                "{outcome:?}"
            );

            // The one used last: the picker selects none after it.
            assert_eq!(delete(base, &id("standard"), &spawner).unwrap(), outcome);
            assert_eq!(
                registry_of(base),
                Registry {
                    workspaces: Vec::new(),
                    last_used: None,
                    ..before
                },
                "{outcome:?}"
            );
        }
    }

    #[test]
    fn delete_keeps_the_workspace_when_its_purge_ends_without_an_outcome() {
        let scratch = Scratch::new("delete-fails");
        let base = &scratch.0;
        install_two(base);
        let registry = registry_bytes(base);

        for code in [EXIT_FAILED, EXIT_UNKNOWN, EXIT_TAKEN, 0, 101] {
            let spawner = FakeSpawner::new(base, Some(Course::ExitsWith(code)));

            let result = delete(base, &id("w-0a1b2c3d"), &spawner);

            assert!(matches!(result, Err(AppError::Io(_))), "{code}: {result:?}");
            assert_eq!(spawner.starts(), [purge_args("w-0a1b2c3d")], "{code}");
            assert_eq!(registry_bytes(base), registry, "{code}");
        }
        // Nor does a purge that does not start.
        let spawner = FakeSpawner::new(base, None);
        assert!(matches!(
            delete(base, &id("w-0a1b2c3d"), &spawner),
            Err(AppError::Io(_))
        ));
        assert_eq!(spawner.starts(), [purge_args("w-0a1b2c3d")]);
        assert_eq!(registry_bytes(base), registry);
    }

    #[test]
    fn delete_refuses_an_open_workspace_and_one_it_does_not_know_and_starts_nothing() {
        let scratch = Scratch::new("delete-refused");
        let base = &scratch.0;
        install_two(base);
        // A directory the registry does not name.
        meta(SyncMode::Local, "Stray", None)
            .store(&dir_of(base, "w-00000000"))
            .unwrap();
        let registry = registry_bytes(base);
        let held = acquire(&lock_of(base, "w-0a1b2c3d")).unwrap().unwrap();
        let spawner = FakeSpawner::new(
            base,
            Some(Course::ExitsWith(purge_exit_code(
                ResetOutcome::NotEnrolled,
            ))),
        );

        for ws in ["w-0a1b2c3d", "w-00000000", "w-11111111"] {
            assert_validation_error(delete(base, &id(ws), &spawner), ws);
        }

        assert!(spawner.starts().is_empty(), "{:?}", spawner.starts());
        assert_eq!(registry_bytes(base), registry);
        assert!(dir_of(base, "w-0a1b2c3d").exists());
        assert!(dir_of(base, "w-00000000").exists());
        assert!(is_open(&lock_of(base, "w-0a1b2c3d")).unwrap());
        drop(held);

        // Without a registry the data has not been moved into workspaces yet.
        let unmigrated = Scratch::new("delete-unmigrated");
        assert!(delete(&unmigrated.0, &id("standard"), &spawner).is_err());
        assert!(spawner.starts().is_empty(), "{:?}", spawner.starts());
        assert!(!unmigrated.0.join(REGISTRY_FILE).exists());
    }

    #[test]
    fn delete_goes_by_the_id_of_a_workspace_without_its_directory_or_workspace_json() {
        let scratch = Scratch::new("delete-broken");
        let base = &scratch.0;
        install(
            base,
            &[
                ("standard", meta(SyncMode::Local, "Standard", None)),
                ("broken", meta(SyncMode::Server, "Broken", None)),
                ("bare", meta(SyncMode::Local, "Bare", None)),
            ],
            false,
        );
        fs::write(dir_of(base, "broken").join("workspace.json"), "{not json").unwrap();
        fs::remove_file(dir_of(base, "bare").join("workspace.json")).unwrap();
        // Named by the registry, its directory gone.
        let mut registry = registry_of(base);
        registry.workspaces.push(RegistryEntry { id: id("gone") });
        registry.store(base).unwrap();

        for ws in ["broken", "bare", "gone"] {
            let spawner = FakeSpawner::new(
                base,
                Some(Course::ExitsWith(purge_exit_code(
                    ResetOutcome::NotEnrolled,
                ))),
            );
            assert_eq!(
                delete(base, &id(ws), &spawner).unwrap(),
                ResetOutcome::NotEnrolled,
                "{ws}"
            );
            assert_eq!(spawner.starts(), [purge_args(ws)], "{ws}");
        }

        assert_eq!(
            registry_of(base).workspaces,
            [RegistryEntry { id: id("standard") }]
        );
    }

    #[test]
    fn delete_gives_up_on_a_purge_that_does_not_end_in_time() {
        let scratch = Scratch::new("delete-hangs");
        let base = &scratch.0;
        install_two(base);
        let registry = registry_bytes(base);
        let spawner = FakeSpawner::new(base, Some(Course::Hangs));
        let timeout = Duration::from_millis(100);
        let started = Instant::now();

        let result = delete_within(
            base,
            &id("w-0a1b2c3d"),
            &spawner,
            timeout,
            Duration::from_millis(20),
        );

        let waited = started.elapsed();
        assert!(
            matches!(&result, Err(AppError::Io(e)) if e.kind() == io::ErrorKind::TimedOut),
            "{result:?}"
        );
        assert!(waited >= timeout, "gave up after {waited:?}");
        assert!(
            waited < Duration::from_millis(900),
            "gave up after {waited:?}"
        );
        assert!(spawner.looks.get() >= 2, "{} looks", spawner.looks.get());
        assert_eq!(registry_bytes(base), registry);
    }

    // ── Purge: what the child of a delete does, against the in-memory keyring ──

    /// The keyring prefix of the workspace `id` made after the migration, spelled out rather
    /// than taken from the code under test.
    fn prefix_of(id: &str) -> String {
        if cfg!(windows) {
            format!("com.admincave.adminhelper/ws:{id}|")
        } else {
            format!("ws:{id}|")
        }
    }

    const IDENTITY: [&str; 4] = ["enroll|key", "enroll|cert", "enroll|ca", "enroll|replaces"];
    const RDP: [&str; 2] = [
        "rdp|c1|host.example.com|3389|admin|",
        "rdp|c2|192.0.2.10|3390|admin|corp",
    ];

    /// Each of `entries` behind `prefix`.
    fn behind(prefix: &str, entries: &[&str]) -> Vec<String> {
        entries
            .iter()
            .map(|entry| format!("{prefix}{entry}"))
            .collect()
    }

    /// Stores a value under each of `keys`.
    fn store(keys: &[String]) {
        for key in keys {
            keyring_store::set(key, "secret").unwrap();
        }
    }

    /// Those of `keys` the keyring holds.
    fn held_keys(keys: &[String]) -> Vec<String> {
        keys.iter()
            .filter(|key| keyring_store::get(key).is_some())
            .cloned()
            .collect()
    }

    /// Makes the index of the RDP keys of the workspace `ws` in `base` name `keys`.
    fn index(base: &Path, ws: &str, keys: &[String]) {
        fs::write(
            dir_of(base, ws).join("secrets.json"),
            serde_json::to_vec(&serde_json::json!({ "keys": keys })).unwrap(),
        )
        .unwrap();
    }

    /// In the app data dir: the RDP keys without a prefix handed over to the last migrated
    /// workspace, spelled out.
    const HANDED_OVER: &str = "legacy-secrets.json";

    /// The names handed over in `base`; none without the file.
    fn handed_over(base: &Path) -> Vec<String> {
        let Ok(bytes) = fs::read(base.join(HANDED_OVER)) else {
            return Vec::new();
        };
        let index: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
        index["keys"]
            .as_array()
            .unwrap()
            .iter()
            .map(|key| key.as_str().unwrap().to_string())
            .collect()
    }

    /// Makes the names handed over in `base` `keys`, as an earlier purge left them.
    fn hand_over(base: &Path, keys: &[String]) {
        fs::write(
            base.join(HANDED_OVER),
            serde_json::to_vec(&serde_json::json!({ "keys": keys })).unwrap(),
        )
        .unwrap();
    }

    #[cfg(unix)]
    fn assert_private_file(path: &Path) {
        use std::os::unix::fs::PermissionsExt;
        let mode = fs::metadata(path).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o600, "{}", path.display());
    }

    #[cfg(not(unix))]
    fn assert_private_file(_path: &Path) {}

    /// A workspace made after the migration: its keys carry its id.
    fn created(kind: SyncMode, name: &str, url: Option<&str>) -> Meta {
        Meta {
            legacy_keys: false,
            ..meta(kind, name, url)
        }
    }

    /// What the purge child of a delete does (`main.rs`): its start, then the purge in its
    /// workspace, with the lock held throughout.
    fn purge_child(
        base: &Path,
        ws: &str,
        revoke: impl FnOnce(&str) -> ResetOutcome,
    ) -> Result<ResetOutcome, AppError> {
        let (held, meta) = match startup(workspace::Mode::Purge(id(ws)), base, acquire) {
            workspace::Plan::Purge(held, meta) => (held, meta),
            other => panic!("expected the purge of {ws}, got {other:?}"),
        };
        let _entered = workspace::enter(held.workspace.clone());
        purge(base, meta.as_ref(), |url| Ok(revoke(url)))
    }

    /// A `revoke` for a purge that must not ask a server.
    fn no_revoke(url: &str) -> ResetOutcome {
        panic!("asked the server at {url}")
    }

    #[test]
    fn purge_of_a_server_workspace_revokes_its_device_then_leaves_nothing_of_it() {
        let scratch = Scratch::new("purge-server");
        let base = &scratch.0;
        let _keyring = keyring_store::memory();
        install(
            base,
            &[
                (
                    "standard",
                    meta(
                        SyncMode::Server,
                        "Standard",
                        Some("https://old.example.com"),
                    ),
                ),
                (
                    "w-0a1b2c3d",
                    created(SyncMode::Server, "Kunde A", Some("https://ah.example.com")),
                ),
                (
                    "w-4e5f6a7b",
                    created(SyncMode::Server, "Kunde B", Some("https://b.example.com")),
                ),
            ],
            false,
        );
        let prefix = prefix_of("w-0a1b2c3d");
        let own = [behind(&prefix, &IDENTITY), behind(&prefix, &RDP)].concat();
        index(base, "w-0a1b2c3d", &behind(&prefix, &RDP));
        // The keys of the migrated workspace and of another one, and a pin, which is global.
        let others = [
            behind("", &IDENTITY),
            behind("", &RDP),
            behind(&prefix_of("w-4e5f6a7b"), &IDENTITY),
            behind(&prefix_of("w-4e5f6a7b"), &RDP),
            vec!["tofu|cert|ah.example.com:443".to_string()],
        ]
        .concat();
        store(&own);
        store(&others);
        write_port_map(
            base,
            &[
                ("standard", "ssh", 6000),
                ("w-0a1b2c3d", "ssh", 23000),
                ("w-4e5f6a7b", "ssh", 23001),
                ("w-0a1b2c3d", "rdp", 23002),
            ],
        );
        let registry = registry_bytes(base);
        let mut asked = Vec::new();

        let outcome = purge_child(base, "w-0a1b2c3d", |url| {
            // The certificate proves which device to revoke: it is still there, and no
            // process can open the workspace meanwhile.
            assert!(
                enrollment::is_enrolled(),
                "the identity went before the revoke"
            );
            assert!(is_open(&lock_of(base, "w-0a1b2c3d")).unwrap());
            asked.push(url.to_string());
            ResetOutcome::Revoked
        })
        .unwrap();

        assert_eq!(outcome, ResetOutcome::Revoked);
        assert_eq!(asked, ["https://ah.example.com"]);
        assert_eq!(held_keys(&own), Vec::<String>::new());
        assert_eq!(held_keys(&others), others);
        assert_eq!(port_owners(base), ["standard", "w-4e5f6a7b"]);
        assert_eq!(workspace_dirs(base), ["standard", "w-4e5f6a7b"]);
        // The launcher takes it out of the registry once the purge said how it went.
        assert_eq!(registry_bytes(base), registry);
    }

    #[test]
    fn purge_without_a_server_to_ask_deletes_an_identity_here_only() {
        for (case, made, enrolled, expected) in [
            (
                "local",
                created(SyncMode::Local, "Lokal", None),
                false,
                ResetOutcome::NotEnrolled,
            ),
            (
                "sync",
                created(
                    SyncMode::Sync,
                    "Sync",
                    Some("https://sync.example.com/c.json"),
                ),
                false,
                ResetOutcome::NotEnrolled,
            ),
            (
                "server without a URL",
                created(SyncMode::Server, "Kunde A", None),
                true,
                ResetOutcome::LocalOnly,
            ),
            (
                "local with an identity",
                created(SyncMode::Local, "Lokal", None),
                true,
                ResetOutcome::LocalOnly,
            ),
        ] {
            let scratch = Scratch::new("purge-no-server");
            let base = &scratch.0;
            let _keyring = keyring_store::memory();
            install(
                base,
                &[
                    (
                        "standard",
                        meta(
                            SyncMode::Server,
                            "Standard",
                            Some("https://old.example.com"),
                        ),
                    ),
                    ("w-0a1b2c3d", made),
                ],
                false,
            );
            let prefix = prefix_of("w-0a1b2c3d");
            let mut own = behind(&prefix, &RDP);
            index(base, "w-0a1b2c3d", &own);
            if enrolled {
                own.extend(behind(&prefix, &IDENTITY));
            }
            let others = [behind("", &IDENTITY), behind("", &RDP)].concat();
            store(&own);
            store(&others);
            write_port_map(
                base,
                &[("w-0a1b2c3d", "ssh", 23000), ("standard", "ssh", 6000)],
            );

            assert_eq!(
                purge_child(base, "w-0a1b2c3d", no_revoke).unwrap(),
                expected,
                "{case}"
            );

            assert_eq!(held_keys(&own), Vec::<String>::new(), "{case}");
            assert_eq!(held_keys(&others), others, "{case}");
            assert_eq!(port_owners(base), ["standard"], "{case}");
            assert_eq!(workspace_dirs(base), ["standard"], "{case}");
        }
    }

    #[test]
    fn purge_of_a_migrated_server_workspace_revokes_and_hands_its_rdp_keys_to_the_last_one() {
        let scratch = Scratch::new("purge-migrated");
        let base = &scratch.0;
        let _keyring = keyring_store::memory();
        install(
            base,
            &[
                (
                    "standard",
                    meta(SyncMode::Server, "Standard", Some("https://ah.example.com")),
                ),
                ("lokal", meta(SyncMode::Local, "Lokal", None)),
                (
                    "w-0a1b2c3d",
                    created(SyncMode::Server, "Kunde A", Some("https://b.example.com")),
                ),
            ],
            false,
        );
        // Without a prefix: the identity from before workspaces, and an RDP password each of
        // the two migrated workspaces saved.
        let identity = behind("", &IDENTITY);
        let [of_standard, of_lokal] = RDP.map(String::from);
        index(base, "standard", std::slice::from_ref(&of_standard));
        index(base, "lokal", std::slice::from_ref(&of_lokal));
        let prefix = prefix_of("w-0a1b2c3d");
        let of_created = [behind(&prefix, &IDENTITY), behind(&prefix, &RDP)].concat();
        store(&identity);
        store(&[of_standard.clone(), of_lokal.clone()]);
        store(&of_created);
        write_port_map(
            base,
            &[
                ("standard", "ssh", 6000),
                ("lokal", "ssh", 23000),
                ("w-0a1b2c3d", "ssh", 23001),
            ],
        );
        let mut asked = Vec::new();

        // `lokal` has no server, so the identity is the server workspace's alone; its RDP
        // password may be `lokal`'s too.
        let outcome = purge_child(base, "standard", |url| {
            asked.push(url.to_string());
            ResetOutcome::Revoked
        })
        .unwrap();

        assert_eq!(outcome, ResetOutcome::Revoked);
        assert_eq!(asked, ["https://ah.example.com"]);
        assert_eq!(held_keys(&identity), Vec::<String>::new());
        assert_eq!(
            held_keys(&[of_standard.clone(), of_lokal.clone()]),
            [of_standard.clone(), of_lokal.clone()]
        );
        assert_eq!(handed_over(base), std::slice::from_ref(&of_standard));
        assert_private_file(&base.join(HANDED_OVER));
        assert_eq!(held_keys(&of_created), of_created);
        assert_eq!(port_owners(base), ["lokal", "w-0a1b2c3d"]);
        assert_eq!(workspace_dirs(base), ["lokal", "w-0a1b2c3d"]);

        // The last migrated workspace deletes its RDP keys and those handed over to it.
        assert_eq!(
            purge_child(base, "lokal", no_revoke).unwrap(),
            ResetOutcome::NotEnrolled
        );
        assert_eq!(held_keys(&[of_standard, of_lokal]), Vec::<String>::new());
        assert!(!base.join(HANDED_OVER).exists());
        assert_eq!(held_keys(&of_created), of_created);
        assert_eq!(port_owners(base), ["w-0a1b2c3d"]);
        assert_eq!(workspace_dirs(base), ["w-0a1b2c3d"]);
    }

    #[test]
    fn purge_of_a_migrated_workspace_leaves_the_identity_to_another_one_of_its_installation() {
        let scratch = Scratch::new("purge-same-origin");
        let base = &scratch.0;
        let _keyring = keyring_store::memory();
        install(
            base,
            &[
                (
                    "standard",
                    meta(SyncMode::Server, "Standard", Some("https://ah.example.com")),
                ),
                (
                    "server",
                    meta(
                        SyncMode::Server,
                        "Server",
                        Some("https://AH.example.com:443/"),
                    ),
                ),
            ],
            false,
        );
        let identity = behind("", &IDENTITY);
        let rdp = behind("", &RDP);
        index(base, "standard", &rdp);
        store(&identity);
        store(&rdp);

        assert_eq!(
            purge_child(base, "standard", no_revoke).unwrap(),
            ResetOutcome::NotEnrolled
        );
        assert_eq!(held_keys(&identity), identity);
        assert_eq!(held_keys(&rdp), rdp);
        assert_eq!(handed_over(base), rdp);

        // The last one of the installation revokes the device.
        let mut asked = Vec::new();
        let outcome = purge_child(base, "server", |url| {
            asked.push(url.to_string());
            ResetOutcome::Revoked
        })
        .unwrap();

        assert_eq!(outcome, ResetOutcome::Revoked);
        assert_eq!(asked, ["https://AH.example.com:443/"]);
        assert_eq!(held_keys(&identity), Vec::<String>::new());
        assert_eq!(held_keys(&rdp), Vec::<String>::new());
        assert!(!base.join(HANDED_OVER).exists());
        assert_eq!(workspace_dirs(base), Vec::<String>::new());
    }

    #[test]
    fn an_identity_is_shared_by_a_migrated_server_workspace_of_the_same_installation() {
        let server = |url: &str| meta(SyncMode::Server, "Server", Some(url));
        let own = server_origin(&server("https://ah.example.com"));
        assert!(own.is_some());
        for (other, shared) in [
            (Some(server("https://AH.example.com:443/x")), true),
            (Some(server("https://ah.example.com:8443")), false),
            (Some(server("http://ah.example.com")), false),
            (Some(meta(SyncMode::Server, "Server", None)), false),
            (Some(meta(SyncMode::Local, "Lokal", None)), false),
            (
                Some(meta(
                    SyncMode::Sync,
                    "Sync",
                    Some("https://ah.example.com/c.json"),
                )),
                false,
            ),
            // Its workspace.json does not load: it may be the server workspace.
            (None, true),
        ] {
            assert_eq!(
                shares_identity(own.as_ref(), other.as_ref()),
                shared,
                "{other:?}"
            );
        }
        // Without a known server of its own, any migrated server workspace may hold it.
        assert!(shares_identity(
            None,
            Some(&server("https://other.example.com"))
        ));
        assert!(!shares_identity(
            None,
            Some(&meta(SyncMode::Local, "Lokal", None))
        ));
        assert_eq!(server_origin(&meta(SyncMode::Local, "Lokal", None)), None);
    }

    #[test]
    fn purge_of_the_last_migrated_workspace_revokes_and_deletes_the_keys_without_a_prefix() {
        let scratch = Scratch::new("purge-last-migrated");
        let base = &scratch.0;
        let _keyring = keyring_store::memory();
        install(
            base,
            &[
                (
                    "server",
                    meta(SyncMode::Server, "Server", Some("https://ah.example.com")),
                ),
                ("w-0a1b2c3d", created(SyncMode::Local, "Kunde A", None)),
            ],
            false,
        );
        // A migrated workspace whose purge removed its directory and did not reach the
        // registry: it shares nothing any more, and handed over an RDP key.
        let mut registry = registry_of(base);
        registry
            .workspaces
            .push(RegistryEntry { id: id("standard") });
        registry.store(base).unwrap();
        let of_standard = "rdp|c9|192.0.2.20|3389|admin|".to_string();
        hand_over(base, std::slice::from_ref(&of_standard));
        let own = [behind("", &IDENTITY), behind("", &RDP), vec![of_standard]].concat();
        index(base, "server", &behind("", &RDP));
        let prefix = prefix_of("w-0a1b2c3d");
        let others = [
            behind(&prefix, &IDENTITY),
            behind(&prefix, &RDP),
            vec!["tofu|cert|ah.example.com:443".to_string()],
        ]
        .concat();
        store(&own);
        store(&others);
        let mut asked = Vec::new();

        let outcome = purge_child(base, "server", |url| {
            asked.push(url.to_string());
            ResetOutcome::Revoked
        })
        .unwrap();

        assert_eq!(outcome, ResetOutcome::Revoked);
        assert_eq!(asked, ["https://ah.example.com"]);
        assert_eq!(held_keys(&own), Vec::<String>::new());
        assert!(!base.join(HANDED_OVER).exists());
        assert_eq!(held_keys(&others), others);
        assert_eq!(workspace_dirs(base), ["w-0a1b2c3d"]);
    }

    #[test]
    fn purge_counts_a_workspace_whose_workspace_json_does_not_load_as_migrated_by_its_id() {
        // `lokal`, made by the migration, may be the server workspace: it shares everything.
        let scratch = Scratch::new("purge-shared-broken");
        let base = &scratch.0;
        let _keyring = keyring_store::memory();
        install(
            base,
            &[
                (
                    "server",
                    meta(SyncMode::Server, "Server", Some("https://ah.example.com")),
                ),
                ("lokal", meta(SyncMode::Local, "Lokal", None)),
            ],
            false,
        );
        fs::write(dir_of(base, "lokal").join("workspace.json"), "{not json").unwrap();
        let identity = behind("", &IDENTITY);
        let rdp = behind("", &RDP);
        index(base, "server", &rdp);
        store(&identity);
        store(&rdp);

        assert_eq!(
            purge_child(base, "server", no_revoke).unwrap(),
            ResetOutcome::NotEnrolled
        );

        assert_eq!(held_keys(&identity), identity);
        assert_eq!(handed_over(base), rdp);
        assert_eq!(held_keys(&rdp), rdp);
        assert_eq!(workspace_dirs(base), ["lokal"]);

        // A workspace the launcher made shares nothing, whatever its workspace.json says.
        let scratch = Scratch::new("purge-unshared-broken");
        let base = &scratch.0;
        let _keyring = keyring_store::memory();
        install(
            base,
            &[
                (
                    "server",
                    meta(SyncMode::Server, "Server", Some("https://ah.example.com")),
                ),
                ("w-0a1b2c3d", meta(SyncMode::Server, "Kunde A", None)),
            ],
            false,
        );
        fs::write(
            dir_of(base, "w-0a1b2c3d").join("workspace.json"),
            "{not json",
        )
        .unwrap();
        index(base, "server", &rdp);
        store(&identity);
        store(&rdp);
        let mut asked = Vec::new();

        let outcome = purge_child(base, "server", |url| {
            asked.push(url.to_string());
            ResetOutcome::Revoked
        })
        .unwrap();

        assert_eq!(outcome, ResetOutcome::Revoked);
        assert_eq!(asked, ["https://ah.example.com"]);
        assert_eq!(held_keys(&identity), Vec::<String>::new());
        assert_eq!(held_keys(&rdp), Vec::<String>::new());
        assert_eq!(workspace_dirs(base), ["w-0a1b2c3d"]);
    }

    #[test]
    fn purge_of_a_migrated_workspace_whose_workspace_json_does_not_load_goes_by_its_id() {
        let identity = behind("", &IDENTITY);
        let rdp = behind("", &RDP);

        // `standard`, beside `lokal`: its RDP keys without a prefix are taken and handed over;
        // `lokal` has no server, so the identity goes, with no server known to ask.
        let scratch = Scratch::new("purge-migrated-broken");
        let base = &scratch.0;
        let _keyring = keyring_store::memory();
        install(
            base,
            &[
                (
                    "standard",
                    meta(SyncMode::Server, "Standard", Some("https://ah.example.com")),
                ),
                ("lokal", meta(SyncMode::Local, "Lokal", None)),
            ],
            false,
        );
        fs::write(dir_of(base, "standard").join("workspace.json"), "{not json").unwrap();
        index(base, "standard", &rdp);
        store(&identity);
        store(&rdp);

        assert_eq!(
            purge_child(base, "standard", no_revoke).unwrap(),
            ResetOutcome::LocalOnly
        );

        assert_eq!(held_keys(&identity), Vec::<String>::new());
        assert_eq!(handed_over(base), rdp);
        assert_eq!(workspace_dirs(base), ["lokal"]);

        // The last migrated workspace, its index empty: the identity is not left behind.
        let scratch = Scratch::new("purge-last-migrated-broken");
        let base = &scratch.0;
        let _keyring = keyring_store::memory();
        install(
            base,
            &[
                (
                    "server",
                    meta(SyncMode::Server, "Server", Some("https://ah.example.com")),
                ),
                ("w-0a1b2c3d", created(SyncMode::Local, "Kunde A", None)),
            ],
            false,
        );
        fs::remove_file(dir_of(base, "server").join("workspace.json")).unwrap();
        store(&identity);

        assert_eq!(
            purge_child(base, "server", no_revoke).unwrap(),
            ResetOutcome::LocalOnly
        );

        assert_eq!(held_keys(&identity), Vec::<String>::new());
        assert_eq!(workspace_dirs(base), ["w-0a1b2c3d"]);
    }

    #[test]
    fn purge_stops_before_it_changes_a_thing_on_a_name_that_is_no_rdp_key_of_its_own() {
        let created_rdp = format!("{}{}", prefix_of("w-0a1b2c3d"), RDP[0]);
        let created_key = format!("{}enroll|key", prefix_of("w-0a1b2c3d"));
        let other_rdp = format!("{}{}", prefix_of("w-4e5f6a7b"), RDP[0]);
        let keys = |names: &[&str]| serde_json::json!({ "keys": names }).to_string();
        // (workspace purged, the file in its data dir or the one in the app data dir, content)
        let cases = [
            (
                "w-0a1b2c3d",
                "secrets.json",
                keys(&[created_rdp.as_str(), other_rdp.as_str()]),
            ),
            (
                "w-0a1b2c3d",
                "secrets.json",
                keys(&[created_rdp.as_str(), RDP[1]]),
            ),
            (
                "w-0a1b2c3d",
                "secrets.json",
                keys(&[created_rdp.as_str(), created_key.as_str()]),
            ),
            (
                "w-0a1b2c3d",
                "secrets.json",
                keys(&["tofu|cert|ah.example.com:443"]),
            ),
            ("w-0a1b2c3d", "secrets.json", "{not json".to_string()),
            (
                "w-0a1b2c3d",
                "secrets.json",
                r#"{"keys": "geheim"}"#.to_string(),
            ),
            // The last migrated workspace: no prefix, but RDP keys only.
            (
                "server",
                "secrets.json",
                keys(&[RDP[0], other_rdp.as_str()]),
            ),
            ("server", "secrets.json", keys(&[RDP[0], "enroll|key"])),
            (
                "server",
                "secrets.json",
                keys(&["tofu|cert|ah.example.com:443"]),
            ),
            (
                "server",
                "secrets.json",
                r#"{"keys": "geheim"}"#.to_string(),
            ),
            // ... and so are those handed over to it.
            ("server", HANDED_OVER, keys(&[RDP[0], other_rdp.as_str()])),
            ("server", HANDED_OVER, keys(&["enroll|key"])),
            ("server", HANDED_OVER, "{not json".to_string()),
            (
                "server",
                HANDED_OVER,
                r#"{"keys": ["geheim", 7]}"#.to_string(),
            ),
        ];
        for (ws, file, content) in cases {
            let case = format!("{ws} {file} {content}");
            let scratch = Scratch::new("purge-foreign");
            let base = &scratch.0;
            let _keyring = keyring_store::memory();
            install(
                base,
                &[
                    (
                        "server",
                        meta(SyncMode::Server, "Server", Some("https://old.example.com")),
                    ),
                    (
                        "w-0a1b2c3d",
                        created(SyncMode::Server, "Kunde A", Some("https://ah.example.com")),
                    ),
                    (
                        "w-4e5f6a7b",
                        created(SyncMode::Server, "Kunde B", Some("https://b.example.com")),
                    ),
                ],
                false,
            );
            let path = if file == HANDED_OVER {
                base.join(file)
            } else {
                dir_of(base, ws).join(file)
            };
            fs::write(&path, &content).unwrap();
            let all = [
                behind("", &IDENTITY),
                behind("", &RDP),
                behind(&prefix_of("w-0a1b2c3d"), &IDENTITY),
                behind(&prefix_of("w-0a1b2c3d"), &RDP),
                behind(&prefix_of("w-4e5f6a7b"), &IDENTITY),
                behind(&prefix_of("w-4e5f6a7b"), &RDP),
                vec!["tofu|cert|ah.example.com:443".to_string()],
            ]
            .concat();
            store(&all);
            write_port_map(
                base,
                &[
                    ("server", "ssh", 6000),
                    ("w-0a1b2c3d", "ssh", 23000),
                    ("w-4e5f6a7b", "ssh", 23001),
                ],
            );
            let registry = registry_bytes(base);

            let error = purge_child(base, ws, no_revoke).unwrap_err().to_string();

            // The file and what is wrong with it, never a value from it.
            assert!(error.contains(file), "{case}: {error}");
            assert!(!error.contains("geheim"), "{case}: {error}");
            assert_eq!(held_keys(&all), all, "{case}");
            assert_eq!(
                port_owners(base),
                ["server", "w-0a1b2c3d", "w-4e5f6a7b"],
                "{case}"
            );
            assert_eq!(
                workspace_dirs(base),
                ["server", "w-0a1b2c3d", "w-4e5f6a7b"],
                "{case}"
            );
            assert_eq!(fs::read_to_string(&path).unwrap(), content, "{case}");
            assert_eq!(registry_bytes(base), registry, "{case}");
        }
    }

    #[test]
    fn purge_reads_the_keys_handed_over_before_it_revokes_and_only_with_keys_to_hand_over() {
        // `standard` revokes the identity alone (`lokal` has no server) and hands its RDP keys
        // to `lokal`; the file it hands them over to does not load.
        for with_keys in [true, false] {
            let case = format!("with keys to hand over: {with_keys}");
            let scratch = Scratch::new("purge-hand-over-unreadable");
            let base = &scratch.0;
            let _keyring = keyring_store::memory();
            install(
                base,
                &[
                    (
                        "standard",
                        meta(SyncMode::Server, "Standard", Some("https://ah.example.com")),
                    ),
                    ("lokal", meta(SyncMode::Local, "Lokal", None)),
                ],
                false,
            );
            let identity = behind("", &IDENTITY);
            let rdp = behind("", &RDP[..1]);
            if with_keys {
                index(base, "standard", &rdp);
            }
            store(&identity);
            store(&rdp);
            let broken = "{not json";
            fs::write(base.join(HANDED_OVER), broken).unwrap();
            write_port_map(base, &[("standard", "ssh", 6000), ("lokal", "ssh", 23000)]);
            let registry = registry_bytes(base);
            let mut asked = Vec::new();

            let purged = purge_child(base, "standard", |url| {
                asked.push(url.to_string());
                ResetOutcome::Revoked
            });

            if with_keys {
                let error = purged.unwrap_err().to_string();
                assert!(error.contains(HANDED_OVER), "{case}: {error}");
                assert_eq!(asked, Vec::<String>::new(), "{case}: revoked");
                assert_eq!(held_keys(&identity), identity, "{case}");
                assert!(
                    dir_of(base, "standard").join("secrets.json").exists(),
                    "{case}"
                );
                assert_eq!(port_owners(base), ["standard", "lokal"], "{case}");
                assert_eq!(workspace_dirs(base), ["lokal", "standard"], "{case}");
            } else {
                // Nothing to hand over: the file is not read, and the purge goes through.
                assert_eq!(purged.unwrap(), ResetOutcome::Revoked, "{case}");
                assert_eq!(asked, ["https://ah.example.com"], "{case}");
                assert_eq!(held_keys(&identity), Vec::<String>::new(), "{case}");
                assert_eq!(port_owners(base), ["lokal"], "{case}");
                assert_eq!(workspace_dirs(base), ["lokal"], "{case}");
            }
            // Never a key of another workspace: the RDP key may be `lokal`'s.
            assert_eq!(held_keys(&rdp), rdp, "{case}");
            assert_eq!(
                fs::read_to_string(base.join(HANDED_OVER)).unwrap(),
                broken,
                "{case}"
            );
            assert_eq!(registry_bytes(base), registry, "{case}");
        }
    }

    #[test]
    fn purge_goes_by_the_id_when_the_workspace_json_does_not_load() {
        for broken in [Some("{not json"), None] {
            let scratch = Scratch::new("purge-broken-meta");
            let base = &scratch.0;
            let _keyring = keyring_store::memory();
            install(
                base,
                &[
                    (
                        "standard",
                        meta(SyncMode::Server, "Standard", Some("https://ah.example.com")),
                    ),
                    (
                        "w-0a1b2c3d",
                        created(SyncMode::Server, "Kunde A", Some("https://ah.example.com")),
                    ),
                ],
                false,
            );
            let meta_path = dir_of(base, "w-0a1b2c3d").join("workspace.json");
            match broken {
                Some(broken) => fs::write(&meta_path, broken).unwrap(),
                None => fs::remove_file(&meta_path).unwrap(),
            }
            let prefix = prefix_of("w-0a1b2c3d");
            let own = [behind(&prefix, &IDENTITY), behind(&prefix, &RDP)].concat();
            index(base, "w-0a1b2c3d", &behind(&prefix, &RDP));
            // The launcher made it: keys without a prefix are never its own.
            let others = [behind("", &IDENTITY), behind("", &RDP)].concat();
            store(&own);
            store(&others);
            write_port_map(
                base,
                &[("standard", "ssh", 6000), ("w-0a1b2c3d", "ssh", 23000)],
            );

            // Its server is not known: the identity goes here only.
            assert_eq!(
                purge_child(base, "w-0a1b2c3d", no_revoke).unwrap(),
                ResetOutcome::LocalOnly,
                "{broken:?}"
            );

            assert_eq!(held_keys(&own), Vec::<String>::new(), "{broken:?}");
            assert_eq!(held_keys(&others), others, "{broken:?}");
            assert_eq!(port_owners(base), ["standard"], "{broken:?}");
            assert_eq!(workspace_dirs(base), ["standard"], "{broken:?}");
        }
    }

    #[test]
    fn a_purge_that_stops_on_the_way_runs_again() {
        let scratch = Scratch::new("purge-again");
        let base = &scratch.0;
        let _keyring = keyring_store::memory();
        install(
            base,
            &[(
                "w-0a1b2c3d",
                created(SyncMode::Server, "Kunde A", Some("https://ah.example.com")),
            )],
            false,
        );
        let prefix = prefix_of("w-0a1b2c3d");
        let own = [behind(&prefix, &IDENTITY), behind(&prefix, &RDP)].concat();
        index(base, "w-0a1b2c3d", &behind(&prefix, &RDP));
        store(&own);
        write_port_map(base, &[("w-0a1b2c3d", "ssh", 23000)]);
        // The port map cannot be locked: the purge stops after the keys.
        let blocker = base.join("port-registry.lock");
        fs::create_dir(&blocker).unwrap();

        let first = purge_child(base, "w-0a1b2c3d", |_| ResetOutcome::Revoked);

        assert!(first.is_err(), "{first:?}");
        assert_eq!(held_keys(&own), Vec::<String>::new());
        assert!(!dir_of(base, "w-0a1b2c3d").join("secrets.json").exists());
        assert!(dir_of(base, "w-0a1b2c3d").exists());

        fs::remove_dir(&blocker).unwrap();
        // Nothing is left to revoke now, as the real reset finds.
        let again = purge_child(base, "w-0a1b2c3d", |_| ResetOutcome::NotEnrolled);

        assert_eq!(again.unwrap(), ResetOutcome::NotEnrolled);
        assert_eq!(port_owners(base), Vec::<String>::new());
        assert_eq!(workspace_dirs(base), Vec::<String>::new());
    }

    #[test]
    fn purge_goes_by_the_id_when_the_directory_is_gone() {
        let scratch = Scratch::new("purge-no-dir");
        let base = &scratch.0;
        let _keyring = keyring_store::memory();
        install(
            base,
            &[("standard", meta(SyncMode::Local, "Standard", None))],
            false,
        );
        let mut registry = registry_of(base);
        registry.workspaces.push(RegistryEntry {
            id: id("w-0a1b2c3d"),
        });
        registry.store(base).unwrap();
        let own = behind(&prefix_of("w-0a1b2c3d"), &IDENTITY);
        let others = [behind("", &IDENTITY), behind("", &RDP)].concat();
        store(&own);
        store(&others);
        write_port_map(
            base,
            &[("standard", "ssh", 6000), ("w-0a1b2c3d", "ssh", 23000)],
        );

        assert_eq!(
            purge_child(base, "w-0a1b2c3d", no_revoke).unwrap(),
            ResetOutcome::LocalOnly
        );

        assert_eq!(held_keys(&own), Vec::<String>::new());
        assert_eq!(held_keys(&others), others);
        assert_eq!(port_owners(base), ["standard"]);
        assert_eq!(
            workspace_dirs(base),
            ["standard"],
            "a purge made a directory"
        );
    }

    // ── T37: the keys from before workspaces go with the last migrated workspace ──

    /// The connection `id` to `host:port` as `Admin` in `CORP`, as a connections file holds it.
    fn rdp_connection(id: &str, host: &str, port: u16) -> Connection {
        Connection {
            id: id.to_string(),
            name: id.to_string(),
            kind: ConnectionKind::Rdp,
            host: Some(host.to_string()),
            port: Some(port),
            username: Some("Admin".to_string()),
            domain: Some("CORP".to_string()),
            key_path: None,
            url: None,
            notes: None,
            tags: Vec::new(),
            trust_cert: false,
            last_used: None,
            server_id: None,
        }
    }

    /// Makes `file` in the data dir of the workspace `ws` in `base` hold `connections`.
    fn write_connections(base: &Path, ws: &str, file: &str, connections: &[Connection]) {
        fs::write(
            dir_of(base, ws).join(file),
            serde_json::to_vec(connections).unwrap(),
        )
        .unwrap();
    }

    /// The migrated workspace `ws`, as its process holds it.
    fn migrated(ws: &str) -> workspace::Workspace {
        workspace::Workspace {
            id: id(ws),
            name: ws.to_string(),
            legacy_keys: true,
        }
    }

    #[test]
    fn workspace_keys_a_key_a_migrated_workspace_takes_over_goes_with_the_last_one() {
        let scratch = Scratch::new("purge-taken-over");
        let base = &scratch.0;
        let _keyring = keyring_store::memory();
        install(
            base,
            &[
                (
                    "standard",
                    meta(SyncMode::Server, "Standard", Some("https://ah.example.com")),
                ),
                ("lokal", meta(SyncMode::Local, "Lokal", None)),
                ("w-0a1b2c3d", created(SyncMode::Local, "Kunde A", None)),
            ],
            false,
        );
        // Stored before connection ids; no connections file names the connection.
        let legacy = "rdp|192.0.2.10|3390|admin|corp".to_string();
        let taken = "rdp|c1|192.0.2.10|3390|admin|corp".to_string();
        let of_created = behind(&prefix_of("w-0a1b2c3d"), &RDP);
        store(std::slice::from_ref(&legacy));
        store(&of_created);
        {
            let _standard = workspace::enter(migrated("standard"));
            let loaded = load_password_keyring(base, &rdp_connection("c1", "192.0.2.10", 3390));
            assert_eq!(loaded.unwrap().as_deref(), Some("secret"));
        }
        assert_eq!(
            held_keys(&[legacy.clone(), taken.clone()]),
            std::slice::from_ref(&taken)
        );
        let index: serde_json::Value = serde_json::from_slice(
            &fs::read(dir_of(base, "standard").join("secrets.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(index, serde_json::json!({ "keys": [taken] }));

        // `lokal` may load it as well: the purge of `standard` hands it over.
        purge_child(base, "standard", |_| ResetOutcome::Revoked).unwrap();
        assert_eq!(
            held_keys(std::slice::from_ref(&taken)),
            std::slice::from_ref(&taken)
        );
        assert_eq!(handed_over(base), std::slice::from_ref(&taken));

        purge_child(base, "lokal", no_revoke).unwrap();
        assert_eq!(held_keys(&[taken]), Vec::<String>::new());
        assert_eq!(held_keys(&of_created), of_created);
        assert_eq!(workspace_dirs(base), ["w-0a1b2c3d"]);
    }

    #[test]
    fn workspace_keys_the_last_migrated_workspace_deletes_the_keys_its_connections_name() {
        for meta_loads in [true, false] {
            let case = format!("workspace.json loads: {meta_loads}");
            let scratch = Scratch::new("purge-unindexed");
            let base = &scratch.0;
            let _keyring = keyring_store::memory();
            install(
                base,
                &[
                    (
                        "server",
                        meta(SyncMode::Server, "Server", Some("https://ah.example.com")),
                    ),
                    ("w-0a1b2c3d", created(SyncMode::Local, "Kunde A", None)),
                ],
                false,
            );
            let to_elsewhere = rdp_connection("c1", "192.0.2.10", 3390);
            let to_here = rdp_connection("c2", "127.0.0.1", 3389);
            let ssh = Connection {
                kind: ConnectionKind::Ssh,
                ..rdp_connection("c3", "192.0.2.30", 22)
            };
            if meta_loads {
                write_connections(
                    base,
                    "server",
                    "connections.json",
                    &[to_elsewhere, to_here, ssh],
                );
            } else {
                // Its kind is not known: the connections in either file are its own.
                fs::write(dir_of(base, "server").join("workspace.json"), "{not json").unwrap();
                write_connections(base, "server", "connections.local.json", &[to_elsewhere]);
                write_connections(base, "server", "connections.json", &[to_here, ssh]);
            }
            // Stored before workspaces and never loaded since: no index names them.
            let unindexed = [
                "rdp|c1|192.0.2.10|3390|admin|corp",
                "rdp|192.0.2.10|3390|admin|corp",
                "rdp|c2|127.0.0.1|3389|admin|corp",
                // No load takes it over, as it may be any connection's to this machine; with
                // no migrated workspace left, it goes all the same.
                "rdp|127.0.0.1|3389|admin|corp",
            ]
            .map(String::from);
            let others = [
                // No RDP connection names them: another id, another target, an SSH one.
                "rdp|c9|192.0.2.10|3390|admin|corp".to_string(),
                "rdp|192.0.2.99|3389|admin|corp".to_string(),
                "rdp|c3|192.0.2.30|22|admin|corp".to_string(),
                "rdp|192.0.2.30|22|admin|corp".to_string(),
                // The same connection in a workspace made after the migration.
                format!(
                    "{}rdp|c1|192.0.2.10|3390|admin|corp",
                    prefix_of("w-0a1b2c3d")
                ),
                "tofu|cert|ah.example.com:443".to_string(),
            ];
            store(&unindexed);
            store(&others);

            purge_child(base, "server", |_| ResetOutcome::Revoked).unwrap();

            assert_eq!(held_keys(&unindexed), Vec::<String>::new(), "{case}");
            assert_eq!(held_keys(&others), others, "{case}");
            assert_eq!(workspace_dirs(base), ["w-0a1b2c3d"], "{case}");
        }
    }

    #[test]
    fn workspace_keys_a_migrated_workspace_beside_another_hands_over_the_keys_its_connections_name()
    {
        let scratch = Scratch::new("purge-unindexed-shared");
        let base = &scratch.0;
        let _keyring = keyring_store::memory();
        install(
            base,
            &[
                (
                    "standard",
                    meta(SyncMode::Server, "Standard", Some("https://ah.example.com")),
                ),
                ("lokal", meta(SyncMode::Local, "Lokal", None)),
            ],
            false,
        );
        let of_standard = rdp_connection("c1", "192.0.2.10", 3390);
        let of_lokal = rdp_connection("c5", "192.0.2.50", 3389);
        write_connections(
            base,
            "standard",
            "connections.json",
            std::slice::from_ref(&of_standard),
        );
        write_connections(
            base,
            "lokal",
            "connections.local.json",
            std::slice::from_ref(&of_lokal),
        );
        // Stored before workspaces and never loaded since: no index names them.
        let keys = [
            "rdp|192.0.2.10|3390|admin|corp",
            "rdp|c1|192.0.2.10|3390|admin|corp",
        ]
        .map(String::from);
        let own_of_lokal = "rdp|c5|192.0.2.50|3389|admin|corp".to_string();
        // No connection names it.
        let other = "rdp|192.0.2.99|3389|admin|corp".to_string();
        store(&keys);
        store(&[own_of_lokal.clone(), other.clone()]);

        purge_child(base, "standard", |_| ResetOutcome::Revoked).unwrap();

        assert_eq!(held_keys(&keys), keys);
        assert_eq!(handed_over(base), keys);
        {
            // They may be `lokal`'s: a connection there with the same id loads them.
            let _lokal = workspace::enter(migrated("lokal"));
            assert_eq!(
                load_password_keyring(base, &of_standard)
                    .unwrap()
                    .as_deref(),
                Some("secret")
            );
            assert_eq!(
                load_password_keyring(base, &of_lokal).unwrap().as_deref(),
                Some("secret")
            );
        }

        // The last migrated workspace deletes them with its own.
        purge_child(base, "lokal", no_revoke).unwrap();
        assert_eq!(
            held_keys(&[keys.as_slice(), &[own_of_lokal, other.clone()]].concat()),
            [other]
        );
        assert!(!base.join(HANDED_OVER).exists());
        assert_eq!(workspace_dirs(base), Vec::<String>::new());
    }

    #[test]
    fn workspace_keys_a_connections_file_that_does_not_load_stops_every_migrated_purge() {
        // (the content, whether another migrated workspace is there)
        let cases = [
            ("{not json", false),
            (
                r#"[{"id": "c1", "name": "geheim", "kind": "geheim"}]"#,
                false,
            ),
            ("{not json", true),
        ];
        for (content, beside) in cases {
            let case = format!("{content} beside another: {beside}");
            let scratch = Scratch::new("purge-connections-unreadable");
            let base = &scratch.0;
            let _keyring = keyring_store::memory();
            let mut workspaces = vec![(
                "server",
                meta(SyncMode::Server, "Server", Some("https://ah.example.com")),
            )];
            if beside {
                workspaces.push(("lokal", meta(SyncMode::Local, "Lokal", None)));
            }
            install(base, &workspaces, false);
            let mut dirs: Vec<&str> = workspaces.iter().map(|(ws, _)| *ws).collect();
            dirs.sort_unstable();
            let path = dir_of(base, "server").join("connections.json");
            fs::write(&path, content).unwrap();
            let all = [behind("", &IDENTITY), behind("", &RDP)].concat();
            index(base, "server", &behind("", &RDP));
            store(&all);
            write_port_map(base, &[("server", "ssh", 6000)]);
            let registry = registry_bytes(base);
            let mut asked = Vec::new();

            let error = purge_child(base, "server", |url| {
                asked.push(url.to_string());
                ResetOutcome::Revoked
            })
            .unwrap_err()
            .to_string();

            // The file and where it breaks, never a value from it; nothing changed.
            assert!(error.contains("connections.json"), "{case}: {error}");
            assert!(!error.contains("geheim"), "{case}: {error}");
            assert_eq!(asked, Vec::<String>::new(), "{case}");
            assert_eq!(held_keys(&all), all, "{case}");
            assert!(!base.join(HANDED_OVER).exists(), "{case}");
            assert_eq!(port_owners(base), ["server"], "{case}");
            assert_eq!(workspace_dirs(base), dirs, "{case}");
            assert_eq!(fs::read_to_string(&path).unwrap(), content, "{case}");
            assert_eq!(registry_bytes(base), registry, "{case}");
        }
    }

    /// (cert_pem, key_pem) of a self-signed leaf.
    fn leaf() -> (String, String) {
        use rcgen::{CertificateParams, KeyPair, PKCS_ECDSA_P256_SHA256};
        let key = KeyPair::generate_for(&PKCS_ECDSA_P256_SHA256).unwrap();
        let cert = CertificateParams::new(vec![])
            .unwrap()
            .self_signed(&key)
            .unwrap();
        (cert.pem(), key.serialize_pem())
    }

    #[test]
    fn purge_leaves_no_leaf_the_reset_remembers_for_an_enrollment_that_does_not_come() {
        let scratch = Scratch::new("purge-reset");
        let base = &scratch.0;
        let _keyring = keyring_store::memory();
        // Held, not freed: nobody listens on the port, and no parallel test's server can be
        // handed it.
        let (_reserved, port) = crate::test_tls::refused_port();
        let url = format!("http://127.0.0.1:{port}");
        install(
            base,
            &[(
                "w-0a1b2c3d",
                created(SyncMode::Server, "Kunde A", Some(&url)),
            )],
            false,
        );
        let prefix = prefix_of("w-0a1b2c3d");
        let (cert, key) = leaf();
        keyring_store::set(&format!("{prefix}enroll|key"), &key).unwrap();
        keyring_store::set(&format!("{prefix}enroll|cert"), &cert).unwrap();
        keyring_store::set(&format!("{prefix}enroll|ca"), &cert).unwrap();
        let replaces = format!("{prefix}enroll|replaces");

        // The real reset, on this thread: the keyring and the workspace are this thread's.
        let outcome = purge_child(base, "w-0a1b2c3d", |url| {
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .unwrap();
            let outcome = runtime.block_on(enrollment::reset_identity(url)).unwrap();
            assert!(
                keyring_store::get(&replaces).is_some(),
                "the server was out of reach, yet the reset remembered no leaf"
            );
            outcome
        })
        .unwrap();

        assert_eq!(outcome, ResetOutcome::LocalOnly);
        assert_eq!(held_keys(&behind(&prefix, &IDENTITY)), Vec::<String>::new());
        assert_eq!(workspace_dirs(base), Vec::<String>::new());
    }

    #[test]
    fn purge_in_the_launcher_deletes_nothing() {
        let scratch = Scratch::new("purge-launcher");
        let base = &scratch.0;
        let _keyring = keyring_store::memory();
        install(
            base,
            &[(
                "w-0a1b2c3d",
                created(SyncMode::Server, "Kunde A", Some("https://ah.example.com")),
            )],
            false,
        );
        let keys = [
            behind("", &IDENTITY),
            behind(&prefix_of("w-0a1b2c3d"), &IDENTITY),
        ]
        .concat();
        store(&keys);
        write_port_map(base, &[("w-0a1b2c3d", "ssh", 23000)]);
        let meta = Meta::load(&dir_of(base, "w-0a1b2c3d")).unwrap();

        let result = purge(base, Some(&meta), |url| Ok(no_revoke(url)));

        assert!(matches!(result, Err(AppError::Validation(_))), "{result:?}");
        assert_eq!(held_keys(&keys), keys);
        assert_eq!(port_owners(base), ["w-0a1b2c3d"]);
        assert_eq!(workspace_dirs(base), ["w-0a1b2c3d"]);
    }

    /// Waits for `child` to end, as long as a loaded runner may need, and gives how it ended;
    /// asked again, the child says the same.
    #[cfg(any(target_os = "linux", windows))]
    fn ended(child: &mut impl Spawned) -> ExitStatus {
        let deadline = Instant::now() + Duration::from_secs(10);
        let status = loop {
            if let Some(status) = child.try_wait().unwrap() {
                break status;
            }
            assert!(Instant::now() < deadline, "the program did not end");
            std::thread::sleep(PROBE);
        };
        assert_eq!(child.try_wait().unwrap(), Some(status), "asked again");
        status
    }

    /// The real start, a shell in place of this program: no app process starts in a test.
    #[cfg(target_os = "linux")]
    #[test]
    fn a_detached_program_leads_a_group_of_its_own_without_stdio_and_its_end_is_seen() {
        use super::AppSpawner;

        let scratch = Scratch::new("detached");
        let report = scratch.0.join("report");
        // The shell writes its /proc stat line and where its stdio goes, then ends with 3. The
        // links are read before any output goes to the report: dash redirects in the shell
        // itself while a command runs.
        let script = r#"stdio="$(readlink /proc/$$/fd/0 /proc/$$/fd/1 /proc/$$/fd/2)"
read -r stat < /proc/$$/stat
printf '%s\n%s\n' "$stat" "$stdio" > "$1"
exit 3"#;

        let spawner = AppSpawner {
            program: PathBuf::from("/bin/sh"),
        };

        let mut child = spawner
            .spawn(&["-c", script, "sh", report.to_str().unwrap()])
            .unwrap();

        assert_eq!(ended(&mut child).code(), Some(3));
        let report = fs::read_to_string(&report).unwrap();
        let mut lines = report.lines();
        // pid (comm) state ppid pgrp …
        let stat: Vec<&str> = lines.next().unwrap().split(' ').collect();
        assert_eq!(stat[4], stat[0], "not a group of its own: {stat:?}");
        assert_eq!(
            lines.collect::<Vec<_>>(),
            ["/dev/null", "/dev/null", "/dev/null"]
        );
    }

    /// The real start on Windows, `cmd.exe` in place of this program: CreateProcess takes the
    /// creation flags, and the end is seen. Runs only in the CI job rust-windows.
    #[cfg(windows)]
    #[test]
    fn a_detached_program_starts_with_the_creation_flags_and_its_end_is_seen() {
        use super::AppSpawner;

        let program = std::env::var_os("ComSpec")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                PathBuf::from(std::env::var_os("SystemRoot").expect("SystemRoot is set"))
                    .join("System32")
                    .join("cmd.exe")
            });
        let spawner = AppSpawner { program };

        let mut child = spawner.spawn(&["/c", "exit", "3"]).unwrap();

        assert_eq!(ended(&mut child).code(), Some(3));
    }
}
