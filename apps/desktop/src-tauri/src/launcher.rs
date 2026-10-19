// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! The launcher (R-0431): the workspaces the picker lists, the making, editing and opening of a
//! workspace, the start of the launcher from a workspace, and the port map entries no workspace
//! owns any more. Once the migration made `workspaces.json`, only the launcher writes it, and it
//! never makes one: without it the migration has not run, and a registry made here would keep
//! the old data out of the workspaces for good.

use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{mpsc, Mutex, MutexGuard, PoisonError};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use sha2::{Digest, Sha256};
use url::Url;

use crate::error::AppError;
use crate::models::{Settings, SyncMode};
use crate::port_registry::PortRegistry;
use crate::validation::{validate_https_url, validate_server_url_secure};
use crate::workspace::{
    acquire, is_open, Meta, Registry, RegistryEntry, Workspace, WorkspaceId, PALETTE, REGISTRY_FILE,
};

/// The longest name of a workspace, in characters.
const NAME_MAX_CHARS: usize = 40;

/// How long [`open`] waits for the workspace it started to hold its lock, and how often it looks.
const OPEN_TIMEOUT: Duration = Duration::from_secs(10);
const OPEN_PROBE: Duration = Duration::from_millis(200);

/// A workspace as the picker lists it.
#[cfg_attr(
    not(test),
    expect(
        dead_code,
        reason = "the commands of the launcher (R-0431 T14) read it"
    )
)]
#[derive(Debug, Clone)]
pub struct WorkspaceInfo {
    pub id: WorkspaceId,
    pub name: String,
    pub color: String,
    pub kind: SyncMode,
    /// The host of its URL; none without a URL.
    pub host: Option<String>,
    /// A process holds its lock.
    pub open: bool,
}

/// What the picker shows.
#[cfg_attr(
    not(test),
    expect(
        dead_code,
        reason = "the commands of the launcher (R-0431 T14) read it"
    )
)]
#[derive(Debug, Clone)]
pub struct WorkspaceList {
    pub workspaces: Vec<WorkspaceInfo>,
    /// The workspace the picker selects first, if it is listed.
    pub last_used: Option<WorkspaceId>,
    /// The note on the migration is due: [`list`] says so once.
    pub migrated_notice: bool,
}

/// What the picker sends to make a workspace (`id` none) or to edit the one `id` names.
#[derive(Debug, Clone)]
pub struct WorkspaceDraft {
    pub id: Option<WorkspaceId>,
    pub kind: SyncMode,
    pub name: String,
    pub color: String,
    /// The URL the workspace keeps; in an edit, none (or a blank one) takes away the URL it has.
    /// The editor therefore always sends the whole URL.
    pub url: Option<String>,
}

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

/// The workspaces in the app data dir `base` with whether each is open, which one was used last,
/// and whether the note on the migration is due; that note comes once, and the listing clears
/// it. A registry entry whose directory is gone (a delete that did not reach the registry), or
/// whose `workspace.json` does not load, is left out with a log line: one broken workspace must
/// not leave the picker empty. The latter stays a workspace all the same (its id stays taken,
/// its ports stay).
#[cfg_attr(
    not(test),
    expect(
        dead_code,
        reason = "the commands of the launcher (R-0431 T14) call it"
    )
)]
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
        workspaces.push(WorkspaceInfo {
            id: entry.id.clone(),
            host: meta.url.as_deref().and_then(host_of),
            open: is_open(&ws.lock_path(base))?,
            name: meta.name,
            color: meta.color,
            kind: meta.kind,
        });
    }
    let migrated_notice = registry.migrated_notice;
    if migrated_notice {
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
    })
}

/// Makes the workspace `draft` describes, or edits the one it names, and gives its id. A new
/// workspace has keyring keys of its own (`legacyKeys: false`). An edit takes the name, colour
/// and URL, only while the workspace is closed, and never another kind. The draft is checked
/// here, without a network call.
#[cfg_attr(
    not(test),
    expect(
        dead_code,
        reason = "the commands of the launcher (R-0431 T14) call it"
    )
)]
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
#[cfg_attr(
    not(test),
    expect(dead_code, reason = "the start of the launcher (R-0431 T10) calls it")
)]
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
#[cfg_attr(
    not(test),
    expect(
        dead_code,
        reason = "the commands of the launcher (R-0431 T14) call it"
    )
)]
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

/// Starts the launcher, for "Workspaces…" in a workspace process: `spawner` starts this program
/// without arguments. If a launcher runs already, the new one hands over to it and ends (the
/// single-instance plugin), so nothing here waits for it.
#[cfg_attr(
    not(test),
    expect(
        dead_code,
        reason = "the commands of the launcher (R-0431 T14) call it"
    )
)]
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
    #[expect(
        dead_code,
        reason = "the commands of the launcher (R-0431 T14) start the workspaces and the launcher with it"
    )]
    pub fn new() -> io::Result<Self> {
        Ok(Self {
            program: std::env::current_exe()?,
        })
    }
}

/// The process creation flags `DETACHED_PROCESS` and `CREATE_NEW_PROCESS_GROUP`
/// (`Win32::System::Threading`), spelled out: the `windows` crate of this app leaves that module
/// out.
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

/// What went wrong with a file, and where, but nothing from inside it: serde quotes the values
/// it rejects.
fn failure(e: &AppError) -> String {
    match e {
        AppError::Json(e) => format!(
            "{:?} error at line {}, column {}",
            e.classify(),
            e.line(),
            e.column()
        ),
        AppError::Io(e) => format!("{:?}", e.kind()),
        _ => "error".to_string(),
    }
}

fn host_of(url: &str) -> Option<String> {
    Url::parse(url).ok()?.host_str().map(String::from)
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

/// Gives the workspace `id` the `name` and `url` checked from `draft`, and its colour. Its lock
/// is held until the edit is written: no process opens the workspace in between.
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
    let meta = Meta::load(&dir)?;
    if meta.kind != draft.kind {
        return Err(AppError::Validation(
            "the kind of a workspace stays as it was made".to_string(),
        ));
    }
    let edited = Meta {
        name,
        color: draft.color.clone(),
        url,
        ..meta.clone()
    };
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
        drop_orphan_ports, is_taken, list, new_id, open, open_launcher, open_within, save, Spawned,
        Spawner, WorkspaceDraft, WorkspaceId, WorkspaceList,
    };
    use crate::error::AppError;
    use crate::models::{Settings, SyncMode};
    use crate::workspace::{
        acquire, is_open, InstanceLock, Meta, Registry, RegistryEntry, PALETTE, REGISTRY_FILE,
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
                _ => {}
            }
            Ok(None)
        }
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
        let timeout = Duration::from_millis(900);
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
