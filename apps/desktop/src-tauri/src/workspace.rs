// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! The workspace of this process (R-0431): how the process was started (launcher, workspace,
//! purge), the id it was started with, and what follows from the workspace — its data dir,
//! keyring prefix, log and window names. A process serves one workspace for its whole life;
//! the launcher serves none. Also the lock that keeps a workspace in one process and the two
//! files that say which workspaces exist (`workspaces.json`) and what each one is
//! (`workspace.json`), what the start of a process comes to ([`startup`]), which process a
//! command is for ([`check_side`]), which server its window means ([`own_url`]), and where a
//! workspace signs in ([`sign_in_url`], [`check_sign_in_once`]).

use std::ffi::OsString;
use std::fmt;
use std::fs::{self, File};
use std::io;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::thread;
use std::time::{Duration, Instant};

use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use url::{Origin, Url};

use crate::error::AppError;
use crate::models::{SyncMode, WorkspaceContext, WorkspaceInfo};
use crate::storage::write_json_atomic;

/// Every character an id may hold (`^[a-z0-9-]{1,32}$`), spelled out rather than as ranges, so
/// no reader has to wonder whether a locale widens them.
const ID_CHARS: &[u8] = b"abcdefghijklmnopqrstuvwxyz0123456789-";
const ID_MAX_LEN: usize = 32;

const USAGE: &str = "usage: adminhelper [--workspace <id> [--purge]]";

/// Exit code of a process whose start failed: the migration, or a file or the lock of its
/// workspace.
pub const EXIT_FAILED: i32 = 1;
/// Exit code of a start for a workspace there is none of, or with arguments that name none.
pub const EXIT_UNKNOWN: i32 = 2;
/// Exit code of a start for a workspace another process holds.
pub const EXIT_TAKEN: i32 = 3;

/// Title of the launcher window; a workspace window puts its name in front.
pub const LAUNCHER_TITLE: &str = "AdminHelper";

/// Log file name (without extension) of the launcher; a workspace process appends `-<id>`.
const LAUNCHER_LOG_NAME: &str = "adminhelper";

/// How long [`acquire`] keeps trying. The picker probes the lock of every workspace it lists
/// ([`is_open`]); a process that starts during a probe must not give up on it.
const ACQUIRE_TIMEOUT: Duration = Duration::from_secs(2);
const ACQUIRE_RETRY: Duration = Duration::from_millis(50);

/// In the app data dir: which workspaces exist ([`Registry`]).
pub(crate) const REGISTRY_FILE: &str = "workspaces.json";
/// In the data dir of a workspace: what it is ([`Meta`]).
const META_FILE: &str = "workspace.json";

/// The colours a workspace can take, as CSS hex: mid tones that read on the dark and the light
/// theme alike. The UI keeps the same list.
pub const PALETTE: &[&str] = &[
    "#3b82f6", // blue
    "#22c55e", // green
    "#f59e0b", // amber
    "#ef4444", // red
    "#8b5cf6", // violet
    "#ec4899", // pink
    "#06b6d4", // cyan
    "#64748b", // slate
];

/// A workspace id that passed [`WorkspaceId::parse`], so it is safe as a path segment and inside
/// a keyring key. Read from a file, it passes the same check.
///
/// `pub(crate)`: a `pub` serde type would have to cross the bridge (`types.parity.test.ts`).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub(crate) struct WorkspaceId(String);

impl WorkspaceId {
    pub fn parse(id: &str) -> Result<Self, AppError> {
        if (1..=ID_MAX_LEN).contains(&id.len()) && id.bytes().all(|b| ID_CHARS.contains(&b)) {
            Ok(Self(id.to_string()))
        } else {
            Err(AppError::Validation(format!(
                "invalid workspace id {id:?}: 1 to {ID_MAX_LEN} characters of a-z, 0-9 and -"
            )))
        }
    }
}

impl fmt::Display for WorkspaceId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl TryFrom<String> for WorkspaceId {
    type Error = AppError;

    fn try_from(id: String) -> Result<Self, AppError> {
        Self::parse(&id)
    }
}

impl From<WorkspaceId> for String {
    fn from(id: WorkspaceId) -> Self {
        id.0
    }
}

fn workspace_log_name(id: &WorkspaceId) -> String {
    format!("{LAUNCHER_LOG_NAME}-{id}")
}

/// How this process was started.
#[derive(Debug, PartialEq, Eq)]
pub enum Mode {
    /// `adminhelper`: the picker, no workspace.
    Launcher,
    /// `adminhelper --workspace <id>`: the window of one workspace.
    Workspace(WorkspaceId),
    /// `adminhelper --workspace <id> --purge`: deletes the workspace without a window; only the
    /// launcher starts it.
    Purge(WorkspaceId),
}

impl Mode {
    /// The mode from the arguments after the program name. Anything but the two flags is an
    /// error with the usage line, so a mistyped start never opens the launcher instead.
    pub fn from_args(args: impl IntoIterator<Item = OsString>) -> Result<Self, AppError> {
        let mut id = None;
        let mut purge = false;
        let mut args = args.into_iter();
        while let Some(arg) = args.next() {
            match arg.to_str() {
                Some("--workspace") if id.is_none() => {
                    let value = args
                        .next()
                        .ok_or_else(|| usage_error("--workspace needs an id"))?;
                    let parsed = value
                        .to_str()
                        .ok_or_else(|| format!("invalid workspace id {value:?}"))
                        .and_then(|value| WorkspaceId::parse(value).map_err(|e| e.to_string()));
                    id = Some(parsed.map_err(|reason| usage_error(&reason))?);
                }
                Some("--purge") if !purge => purge = true,
                _ => return Err(usage_error(&format!("unexpected argument {arg:?}"))),
            }
        }
        match (id, purge) {
            (None, false) => Ok(Mode::Launcher),
            (Some(id), false) => Ok(Mode::Workspace(id)),
            (Some(id), true) => Ok(Mode::Purge(id)),
            (None, true) => Err(usage_error("--purge needs --workspace <id>")),
        }
    }

    /// Log file name (without extension) of a process in this mode. The purge child writes the
    /// log of its workspace: one log file never has two writing processes, as the workspace
    /// lock keeps each id in one process.
    pub fn log_name(&self) -> String {
        match self {
            Mode::Launcher => LAUNCHER_LOG_NAME.to_string(),
            Mode::Workspace(id) | Mode::Purge(id) => workspace_log_name(id),
        }
    }
}

fn usage_error(reason: &str) -> AppError {
    AppError::Validation(format!("{reason}; {USAGE}"))
}

/// The workspace a process serves.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Workspace {
    pub id: WorkspaceId,
    pub name: String,
    /// Keyring keys without a prefix, as before workspaces existed: every migrated workspace.
    pub legacy_keys: bool,
}

/// `<base>/workspaces`, `base` being the app data dir: the data dirs of all workspaces.
pub(crate) fn workspaces_dir(base: &Path) -> PathBuf {
    base.join("workspaces")
}

impl Workspace {
    /// `<base>/workspaces/<id>`, `base` being the app data dir.
    pub fn data_dir(&self, base: &Path) -> PathBuf {
        workspaces_dir(base).join(&self.id.0)
    }

    /// Runtime files of the tunnel, present only while it runs.
    pub fn run_dir(&self, base: &Path) -> PathBuf {
        self.data_dir(base).join("run")
    }

    /// The lock that keeps the workspace in one process.
    pub fn lock_path(&self, base: &Path) -> PathBuf {
        self.data_dir(base).join("instance.lock")
    }

    /// Put in front of every keyring key of the workspace. The `|` ends the id, so no key of one
    /// workspace starts with the prefix of another.
    pub fn keyring_prefix(&self) -> String {
        if self.legacy_keys {
            String::new()
        } else if cfg!(windows) {
            // A Windows credential has no service field: its target name is the whole key, in
            // one namespace with every other program of the user, so the app's name goes first.
            format!("{}/ws:{}|", crate::keyring_store::SERVICE, self.id)
        } else {
            format!("ws:{}|", self.id)
        }
    }

    pub fn log_name(&self) -> String {
        workspace_log_name(&self.id)
    }

    pub fn window_title(&self) -> String {
        format!("{} — {LAUNCHER_TITLE}", self.name)
    }
}

/// Keeps a workspace in this process until it drops. The lock sits on a file of its own, never
/// on a data file: on Windows it is `LockFileEx`, which can be mandatory and would bar every
/// other handle, the holder's own included, from the locked bytes.
#[derive(Debug)]
pub struct InstanceLock {
    file: File,
}

impl Drop for InstanceLock {
    fn drop(&mut self) {
        // Windows frees the lock of a closed handle when it gets round to it; the picker's next
        // probe and the next start need not wait for that.
        let _ = self.file.unlock();
    }
}

/// Takes the lock at `path` ([`Workspace::lock_path`]), trying for up to [`ACQUIRE_TIMEOUT`];
/// `None` if another holder keeps it that long. The directory must exist: a lock never brings
/// back a workspace whose directory is gone.
pub fn acquire(path: &Path) -> Result<Option<InstanceLock>, AppError> {
    acquire_within(path, ACQUIRE_TIMEOUT)
}

fn acquire_within(path: &Path, timeout: Duration) -> Result<Option<InstanceLock>, AppError> {
    let file = open_lock_file(path, true)?;
    let deadline = Instant::now() + timeout;
    loop {
        match file.try_lock() {
            Ok(()) => return Ok(Some(InstanceLock { file })),
            Err(fs::TryLockError::WouldBlock) if Instant::now() < deadline => {
                thread::sleep(ACQUIRE_RETRY)
            }
            Err(fs::TryLockError::WouldBlock) => return Ok(None),
            Err(fs::TryLockError::Error(e)) => return Err(e.into()),
        }
    }
}

/// Whether a process holds the lock at `path` right now. The probe takes the lock if it can and
/// gives it back at once; a workspace that never ran has no lock file, and the probe makes none.
pub fn is_open(path: &Path) -> Result<bool, AppError> {
    let file = match open_lock_file(path, false) {
        Ok(file) => file,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(false),
        Err(e) => return Err(e.into()),
    };
    match file.try_lock() {
        Ok(()) => {
            // Given back at once, not when Windows gets round to the closed handle: a start
            // right after the probe must find the lock free.
            let _ = file.unlock();
            Ok(false)
        }
        Err(fs::TryLockError::WouldBlock) => Ok(true),
        Err(fs::TryLockError::Error(e)) => Err(e.into()),
    }
}

/// Opens the lock file to read and write (`LockFileEx` wants a handle with either), created 0600
/// on Unix; on Windows the user's ACLs of the app data dir apply.
fn open_lock_file(path: &Path, create: bool) -> io::Result<File> {
    let mut options = fs::OpenOptions::new();
    options
        .read(true)
        .write(true)
        .create(create)
        .truncate(false);
    #[cfg(unix)]
    std::os::unix::fs::OpenOptionsExt::mode(&mut options, 0o600);
    options.open(path)
}

/// The JSON in `path`; `None` if there is no such file. A file that does not parse is an error,
/// never a default: whoever reads it would act on an empty list.
fn read_json<T: DeserializeOwned>(path: &Path) -> Result<Option<T>, AppError> {
    match fs::read(path) {
        Ok(bytes) => Ok(Some(serde_json::from_slice(&bytes)?)),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(e.into()),
    }
}

/// `workspaces.json` in the app data dir: which workspaces exist, which one the picker selects
/// first, and whether the picker still owes the notes on the migration. Written by the migration
/// and the launcher; its arrival ends the migration.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct Registry {
    pub workspaces: Vec<RegistryEntry>,
    pub last_used: Option<WorkspaceId>,
    pub migrated_notice: bool,
    /// The name (no path) the migration set an unreadable `settings.json` aside under, while the
    /// picker still owes the note on it.
    pub unreadable_settings: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub(crate) struct RegistryEntry {
    pub id: WorkspaceId,
}

impl Registry {
    /// The registry in the app data dir `base`; `None` while there is none (before the
    /// migration).
    pub fn load(base: &Path) -> Result<Option<Self>, AppError> {
        read_json(&base.join(REGISTRY_FILE))
    }

    /// At once on every platform: launchers and starting workspace processes read it while
    /// another process writes it, and a torn one would not load.
    pub fn store(&self, base: &Path) -> Result<(), AppError> {
        write_json_atomic(&base.join(REGISTRY_FILE), self)
    }
}

/// `workspace.json` in the data dir of a workspace: what it is and the settings it keeps for
/// itself. Written only by the holder of its lock, or by whoever builds it in a directory no
/// workspace uses yet.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct Meta {
    /// Fixed for the life of the workspace; it replaces the mode switch.
    pub kind: SyncMode,
    pub name: String,
    /// One of [`PALETTE`].
    pub color: String,
    /// The server of a server workspace, the source of a sync workspace; none for local.
    pub url: Option<String>,
    pub interval_minutes: u32,
    pub allow_self_signed_certs: bool,
    pub last_username: Option<String>,
    /// Keyring keys without a prefix ([`Workspace::keyring_prefix`]).
    pub legacy_keys: bool,
}

impl Meta {
    /// The meta in `dir`, the data dir of a workspace. A workspace without one is broken: an
    /// error, like a file that does not parse.
    pub fn load(dir: &Path) -> Result<Self, AppError> {
        read_json(&dir.join(META_FILE))?.ok_or_else(|| {
            AppError::Io(io::Error::new(
                io::ErrorKind::NotFound,
                format!("no {META_FILE} in {}", dir.display()),
            ))
        })
    }

    /// At once on every platform: the launcher lists it while the workspace saves its settings.
    pub fn store(&self, dir: &Path) -> Result<(), AppError> {
        write_json_atomic(&dir.join(META_FILE), self)
    }

    /// The workspace `id` this describes, as the picker lists it and its window knows itself;
    /// `open` whether a process holds its lock.
    pub fn info(self, id: WorkspaceId, open: bool) -> WorkspaceInfo {
        WorkspaceInfo {
            url: self.url.as_deref().and_then(shown_url),
            host: self.url.as_deref().and_then(host_of),
            id,
            name: self.name,
            color: self.color,
            kind: self.kind,
            open,
        }
    }
}

fn host_of(url: &str) -> Option<String> {
    Url::parse(url).ok()?.host_str().map(String::from)
}

/// `url` as the webview gets it: a user and a password masked as one (`***@`), each value of its
/// query and its fragment masked (`?token=***`, `#***`; the keys of the query stay), in the
/// parser's spelling; a URL with nothing to mask as kept. A part of the query without a value
/// may be a token itself and is masked whole (`?***`). None for a URL that does not parse: where
/// the parser finds no URL, it finds nothing to mask either, and the webview would get it all.
/// What it gives comes out of it again unchanged, so `launcher::edit` can tell a URL the webview
/// sends back as it got it.
pub(crate) fn shown_url(url: &str) -> Option<String> {
    let mut parsed = Url::parse(url).ok()?;
    let user = !parsed.username().is_empty() || parsed.password().is_some();
    let pairs: Vec<(String, String)> = parsed.query_pairs().into_owned().collect();
    let fragment = parsed
        .fragment()
        .is_some_and(|fragment| !fragment.is_empty());
    if !user && pairs.is_empty() && !fragment {
        return Some(url.to_string());
    }
    if user {
        parsed.set_username("***").ok()?;
        parsed.set_password(None).ok()?;
    }
    if !pairs.is_empty() {
        let mut query = parsed.query_pairs_mut();
        query.clear();
        for (key, value) in &pairs {
            if value.is_empty() {
                query.append_key_only("***");
            } else {
                query.append_pair(key, "***");
            }
        }
    }
    if fragment {
        parsed.set_fragment(Some("***"));
    }
    Some(parsed.into())
}

/// The origin of the server of a server workspace: scheme, host and port, the default port
/// filled in, so two URLs of one installation compare equal. None for a workspace without a
/// server, which never has an identity.
pub(crate) fn server_origin(meta: &Meta) -> Option<Origin> {
    if meta.kind != SyncMode::Server {
        return None;
    }
    Some(Url::parse(meta.url.as_deref()?).ok()?.origin())
}

/// What went wrong with a file, and where, but nothing from inside it: serde quotes the values
/// it rejects.
pub(crate) fn failure(e: &AppError) -> String {
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

/// [`Meta::load`] of the workspace `id` from its data dir `dir`, with an error the webview may
/// show: the file and where it breaks, never a value from it ([`failure`]).
pub(crate) fn load_meta(id: &WorkspaceId, dir: &Path) -> Result<Meta, AppError> {
    Meta::load(dir).map_err(|e| {
        AppError::Validation(format!(
            "the {META_FILE} of the workspace {id} does not load ({})",
            failure(&e)
        ))
    })
}

/// A workspace whose lock this process holds, for as long as this lives. Only [`startup`] makes
/// one, after the lock: no process takes a workspace ([`set_current`]) it does not hold. The one
/// exception has no lock to take: the purge of a workspace whose directory is gone.
#[derive(Debug)]
pub struct Held {
    pub workspace: Workspace,
    /// None only for that purge: no process starts a workspace without its directory, and there
    /// is no data dir to keep to oneself.
    lock: Option<InstanceLock>,
}

/// What the start of a process comes to ([`startup`]).
#[derive(Debug)]
pub enum Plan {
    /// The picker.
    Launcher,
    /// The window of the workspace held.
    Workspace(Held),
    /// The purge of the workspace held, without a window, with its `workspace.json`; none if
    /// that does not load or the directory is gone, and the purge goes by the id alone.
    Purge(Held, Option<Meta>),
    /// No start: the process says `line` and ends with `code`.
    Exit { code: i32, line: String },
}

impl Plan {
    /// The log file (without extension) the process of this plan writes; none for a process
    /// that does not start, whose line goes to stderr alone. Until it holds a workspace, the log
    /// of that workspace may be another process's, and the log plugin rotates the file it opens;
    /// so the purge of a workspace without a directory, which holds no lock, writes none either.
    /// The launcher's log is its own whatever its plan: the single-instance plugin lets one
    /// launcher run, so it opens that log before its start.
    pub fn log_name(&self) -> Option<String> {
        match self {
            Plan::Launcher => Some(Mode::Launcher.log_name()),
            Plan::Workspace(held) | Plan::Purge(held, _) => {
                held.lock.is_some().then(|| held.workspace.log_name())
            }
            Plan::Exit { .. } => None,
        }
    }
}

/// What the start of a process in `mode` comes to, in the app data dir `base`. First the data
/// from before workspaces moves into them ([`crate::migration::migrate`]); if that fails, no
/// process starts, as a launcher would later make a registry that keeps the old data out for
/// good. A workspace process then needs its workspace in the registry, with its directory, and
/// its lock, which `lock` takes ([`acquire`] at a real start); only once it holds the lock does
/// it read the workspace. A purge needs the workspace in the registry alone: it goes by the id
/// when the directory is gone or the `workspace.json` does not load, so a broken workspace can
/// still be deleted.
pub fn startup(
    mode: Mode,
    base: &Path,
    lock: impl FnOnce(&Path) -> Result<Option<InstanceLock>, AppError>,
) -> Plan {
    let exit = |code, line| Plan::Exit { code, line };
    if let Err(e) = crate::migration::migrate(base) {
        // Its errors name the file and where it breaks, never a value from it.
        return exit(
            EXIT_FAILED,
            format!("the data was not moved into workspaces: {e}"),
        );
    }
    let (id, purge) = match mode {
        Mode::Launcher => return Plan::Launcher,
        Mode::Workspace(id) => (id, false),
        Mode::Purge(id) => (id, true),
    };
    let registry = match Registry::load(base) {
        Ok(registry) => registry,
        Err(e) => {
            return exit(
                EXIT_FAILED,
                format!("{REGISTRY_FILE} does not load ({})", failure(&e)),
            )
        }
    };
    // Its paths hang on the id alone, and so does what a purge knows of it without its
    // workspace.json: the workspaces the migration made keep their keys without a prefix.
    let paths = Workspace {
        id: id.clone(),
        name: String::new(),
        legacy_keys: crate::migration::is_migration_id(&id),
    };
    let dir = paths.data_dir(base);
    let listed = registry.is_some_and(|registry| registry.workspaces.iter().any(|e| e.id == id));
    match dir.try_exists() {
        Ok(true) if listed => {}
        // A purge that removed the directory and did not reach the registry. Nothing to lock:
        // a start never brings back the directory of a workspace.
        Ok(false) if listed && purge => {
            let held = Held {
                workspace: paths,
                lock: None,
            };
            return Plan::Purge(held, None);
        }
        Ok(_) => return exit(EXIT_UNKNOWN, format!("there is no workspace {id}")),
        Err(e) => {
            return exit(
                EXIT_FAILED,
                format!(
                    "the directory of the workspace {id} is out of reach ({:?})",
                    e.kind()
                ),
            )
        }
    }
    let lock = match lock(&paths.lock_path(base)) {
        Ok(Some(lock)) => lock,
        Ok(None) => {
            return exit(
                EXIT_TAKEN,
                format!("the workspace {id} is open in another process"),
            )
        }
        Err(e) => {
            return exit(
                EXIT_FAILED,
                format!(
                    "the lock of the workspace {id} was not taken ({})",
                    failure(&e)
                ),
            )
        }
    };
    let meta = match Meta::load(&dir) {
        Ok(meta) => meta,
        // The purge goes by the id, its keyring prefix too ([`Workspace::keyring_prefix`]).
        Err(_) if purge => {
            let held = Held {
                workspace: paths,
                lock: Some(lock),
            };
            return Plan::Purge(held, None);
        }
        Err(e) => {
            return exit(
                EXIT_FAILED,
                format!(
                    "the {META_FILE} of the workspace {id} does not load ({})",
                    failure(&e)
                ),
            )
        }
    };
    let held = Held {
        workspace: Workspace {
            id,
            name: meta.name.clone(),
            legacy_keys: meta.legacy_keys,
        },
        lock: Some(lock),
    };
    if purge {
        Plan::Purge(held, Some(meta))
    } else {
        Plan::Workspace(held)
    }
}

/// The workspace of this process with its lock, set once at start; the launcher never sets it.
static CURRENT: OnceLock<Held> = OnceLock::new();

/// Make the workspace `held` the one of this process; its lock stays held as long as the process
/// runs. Only once: a process never changes its workspace, so nothing it keyed by one prefix or
/// path reaches another workspace. Only a workspace held gets here: what this process does in
/// its data dir assumes it is the only one there (the first reconciliation of the tunnel empties
/// `run/`, `frpc::reconcile`).
pub fn set_current(held: Held) -> Result<(), AppError> {
    CURRENT.set(held).map_err(|_| {
        AppError::Validation("the workspace of this process is already set".to_string())
    })
}

/// The workspace of this process. The launcher has none, and whatever hangs on a workspace (data
/// paths, keyring prefixes) fails closed on this error.
///
/// A test build reads only the guard of [`enter`] on its own thread, never the process-wide
/// workspace: without a guard a test is the launcher, and tests share nothing.
pub fn current() -> Result<Workspace, AppError> {
    #[cfg(test)]
    let workspace = test_context::get();
    #[cfg(not(test))]
    let workspace = CURRENT.get().map(|held| held.workspace.clone());
    workspace
        .ok_or_else(|| AppError::Validation("no workspace in this process (launcher)".to_string()))
}

/// What the webview learns of its process, `base` being the app data dir: the launcher, or the
/// workspace this process serves, open as this process holds it.
pub fn context(base: &Path) -> Result<WorkspaceContext, AppError> {
    let Ok(ws) = current() else {
        return Ok(WorkspaceContext {
            launcher: true,
            workspace: None,
        });
    };
    let meta = load_meta(&ws.id, &ws.data_dir(base))?;
    Ok(WorkspaceContext {
        launcher: false,
        workspace: Some(meta.info(ws.id, true)),
    })
}

/// The process a command is for.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Side {
    /// The picker: it lists, makes, edits, opens and deletes workspaces.
    Launcher,
    /// The window of one workspace.
    Workspace,
}

/// Whether a command for `side` runs in a process whose workspace is `current`, none in the
/// launcher. Every process has every command; this keeps the launcher out of a workspace, and
/// a workspace from managing the others.
pub fn check_side(side: Side, current: Option<&Workspace>) -> Result<(), AppError> {
    match (side, current) {
        (Side::Launcher, None) | (Side::Workspace, Some(_)) => Ok(()),
        (Side::Launcher, Some(ws)) => Err(AppError::Validation(format!(
            "only the launcher does this, not the process of the workspace {}",
            ws.id
        ))),
        (Side::Workspace, None) => Err(AppError::Validation(
            "only the process of a workspace does this, not the launcher".to_string(),
        )),
    }
}

/// Whether the URLs `a` and `b` name one server: the same origin (scheme, host regardless of
/// case, port with the default filled in, so `https://H` and `https://h:443/` are one). A URL
/// that does not parse names none.
pub(crate) fn same_server(a: &str, b: &str) -> bool {
    match (Url::parse(a), Url::parse(b)) {
        (Ok(a), Ok(b)) => a.origin() == b.origin(),
        _ => false,
    }
}

/// The server of `url` as an error names it: its origin, never the URL, which may carry a user
/// and a password.
fn named_server(url: &str) -> String {
    match Url::parse(url).map(|url| url.origin()) {
        Ok(origin) if origin.is_tuple() => origin.ascii_serialization(),
        _ => "its URL names".to_string(),
    }
}

/// The URL of the workspace `meta` that `sent`, the URL its window names, stands for: the one it
/// keeps, trimmed, of which `sent` must name the server ([`same_server`]); until it has one,
/// `sent`. Another server would be another installation under the sign-in, the device identity
/// or the pins of this workspace. A local workspace has no server.
pub fn own_url(meta: &Meta, sent: &str) -> Result<String, AppError> {
    if meta.kind == SyncMode::Local {
        return Err(AppError::Validation(
            "a local workspace has no server".to_string(),
        ));
    }
    let sent = sent.trim();
    match meta.url.as_deref().map(str::trim) {
        None => Ok(sent.to_string()),
        Some(kept) if same_server(kept, sent) => Ok(kept.to_string()),
        Some(kept) => Err(AppError::Validation(format!(
            "this workspace belongs to the server {}; another server is another workspace",
            named_server(kept)
        ))),
    }
}

/// The URL a sign-in, an enrollment or a reset of the device identity of the workspace `meta`
/// goes to, `sent` being the one the webview names ([`own_url`]); until the workspace has one,
/// `sent`, which a registration that succeeds there (`storage::keep_enrolled_url`), or else the
/// save after the sign-in (`storage::save_settings`), makes its own. Only a server workspace
/// signs in or has a device identity: a sync or local one has no server, and no purge would
/// revoke an identity it took.
pub fn sign_in_url(meta: &Meta, sent: &str) -> Result<String, AppError> {
    if meta.kind != SyncMode::Server {
        return Err(AppError::Validation(
            "only a server workspace signs in, registers this device or resets its identity"
                .to_string(),
        ));
    }
    own_url(meta, sent)
}

/// The source a sync of the workspace `meta` loads, `sent` being the one its window names: the
/// one it keeps, trimmed, which `sent`, trimmed, must spell the same. That is the rule by which
/// the save of the settings tells a sync source (`storage::meta_with`): another path or query
/// is another source, even of the same server. Only a sync workspace syncs, and only once it
/// has a source. An error names no URL: a sync source may carry credentials.
pub fn sync_url(meta: &Meta, sent: &str) -> Result<String, AppError> {
    if meta.kind != SyncMode::Sync {
        return Err(AppError::Validation(
            "only a sync workspace syncs".to_string(),
        ));
    }
    let Some(kept) = meta.url.as_deref().map(str::trim) else {
        return Err(AppError::Validation(
            "this sync workspace has no sync URL yet".to_string(),
        ));
    };
    if sent.trim() != kept {
        return Err(AppError::Validation(
            "this workspace syncs only from the sync URL it keeps".to_string(),
        ));
    }
    Ok(kept.to_string())
}

/// Refuses the sign-in of `username` at `url` in the workspace `own` while another of
/// `workspaces` (each with its `workspace.json`) signs in to the same server ([`server_origin`])
/// as the same user (its `lastUsername`, case aside): a user of an installation signs in in one
/// workspace. The error names that workspace.
pub fn check_sign_in_once(
    own: &WorkspaceId,
    url: &str,
    username: &str,
    workspaces: &[(WorkspaceId, Meta)],
) -> Result<(), AppError> {
    let origin = Url::parse(url)?.origin();
    let user = username.trim().to_lowercase();
    let taken = workspaces.iter().find(|(id, meta)| {
        id != own
            && meta
                .last_username
                .as_deref()
                .is_some_and(|theirs| theirs.trim().to_lowercase() == user)
            && server_origin(meta).is_some_and(|theirs| theirs == origin)
    });
    match taken {
        Some((_, meta)) => Err(AppError::Validation(format!(
            "the workspace \"{}\" signs in to this server as this user; one workspace per server and user",
            meta.name
        ))),
        None => Ok(()),
    }
}

/// Every workspace in the app data dir `base` with its `workspace.json`, for
/// [`check_sign_in_once`]. One whose directory is gone or whose `workspace.json` does not load is
/// left out: no process opens it ([`startup`]), so it signs in nowhere. A registry that is not
/// there or does not load is an error.
pub fn metas(base: &Path) -> Result<Vec<(WorkspaceId, Meta)>, AppError> {
    let registry = Registry::load(base)
        .map_err(|e| {
            AppError::Validation(format!("{REGISTRY_FILE} does not load ({})", failure(&e)))
        })?
        .ok_or_else(|| AppError::Validation(format!("there is no {REGISTRY_FILE}")))?;
    let mut metas = Vec::with_capacity(registry.workspaces.len());
    for entry in registry.workspaces {
        let ws = Workspace {
            id: entry.id,
            name: String::new(),
            legacy_keys: false,
        };
        if let Ok(meta) = Meta::load(&ws.data_dir(base)) {
            metas.push((ws.id, meta));
        }
    }
    Ok(metas)
}

/// While the guard lives, [`current`] on this thread answers `workspace`; dropping the guard
/// brings back what this thread had before.
#[cfg(test)]
pub fn enter(workspace: Workspace) -> EnteredWorkspace {
    EnteredWorkspace {
        previous: test_context::replace(Some(workspace)),
    }
}

/// The guard of [`enter`].
#[cfg(test)]
#[must_use = "the workspace lasts as long as its guard"]
pub struct EnteredWorkspace {
    previous: Option<Workspace>,
}

#[cfg(test)]
impl Drop for EnteredWorkspace {
    fn drop(&mut self) {
        test_context::replace(self.previous.take());
    }
}

#[cfg(test)]
mod test_context {
    use std::cell::RefCell;

    use super::Workspace;

    thread_local! {
        static CURRENT: RefCell<Option<Workspace>> = const { RefCell::new(None) };
    }

    pub(super) fn get() -> Option<Workspace> {
        CURRENT.with(|current| current.borrow().clone())
    }

    pub(super) fn replace(workspace: Option<Workspace>) -> Option<Workspace> {
        CURRENT.with(|current| current.replace(workspace))
    }
}

#[cfg(test)]
mod tests {
    use std::ffi::OsString;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::thread;
    use std::time::{Duration, Instant};

    use url::Url;

    use super::{
        acquire, acquire_within, check_side, check_sign_in_once, context, current, enter, is_open,
        metas, own_url, same_server, set_current, shown_url, sign_in_url, startup, sync_url,
        AppError, Held, InstanceLock, Meta, Mode, Plan, Registry, RegistryEntry, Side, Workspace,
        WorkspaceId, ACQUIRE_TIMEOUT, EXIT_FAILED, EXIT_TAKEN, EXIT_UNKNOWN, LAUNCHER_TITLE,
        META_FILE, PALETTE, REGISTRY_FILE, USAGE,
    };
    use crate::models::SyncMode;

    /// A directory of its own for one test case under the system temp dir, gone with the guard.
    struct Scratch(PathBuf);

    impl Scratch {
        fn new(case: &str) -> Self {
            let dir =
                std::env::temp_dir().join(format!("ah-workspace-{case}-{}", std::process::id()));
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

    /// Short enough for a test that expects the lock to stay taken.
    const BRIEF: Duration = Duration::from_millis(100);

    #[cfg(unix)]
    fn assert_private(path: &Path) {
        use std::os::unix::fs::PermissionsExt;
        let mode = fs::metadata(path).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o600, "{}", path.display());
    }

    #[cfg(not(unix))]
    fn assert_private(_path: &Path) {}

    /// The names in `dir`, sorted.
    fn names_in(dir: &Path) -> Vec<String> {
        let mut names: Vec<String> = fs::read_dir(dir)
            .unwrap()
            .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
            .collect();
        names.sort();
        names
    }

    fn parse(args: &[&str]) -> Result<Mode, AppError> {
        Mode::from_args(args.iter().map(OsString::from))
    }

    fn id(id: &str) -> WorkspaceId {
        WorkspaceId::parse(id).unwrap()
    }

    fn workspace(id_: &str, name: &str, legacy_keys: bool) -> Workspace {
        Workspace {
            id: id(id_),
            name: name.to_string(),
            legacy_keys,
        }
    }

    /// `workspace` as a start holds it: with the lock in its data dir in `base`.
    fn held(base: &Path, workspace: Workspace) -> Held {
        let lock = workspace.lock_path(base);
        fs::create_dir_all(lock.parent().unwrap()).unwrap();
        Held {
            lock: Some(acquire(&lock).unwrap().expect("a fresh lock is free")),
            workspace,
        }
    }

    fn assert_usage_error(result: Result<Mode, AppError>, case: &str) {
        match result {
            Err(AppError::Validation(msg)) => {
                assert!(msg.contains(USAGE), "{case}: no usage line in {msg:?}")
            }
            other => panic!("{case}: expected a usage error, got {other:?}"),
        }
    }

    #[test]
    fn no_arguments_start_the_launcher() {
        assert_eq!(parse(&[]).unwrap(), Mode::Launcher);
    }

    #[test]
    fn the_workspace_flag_starts_that_workspace() {
        assert_eq!(
            parse(&["--workspace", "standard"]).unwrap(),
            Mode::Workspace(id("standard"))
        );
        assert_eq!(
            parse(&["--workspace", "w-0a1b2c3d"]).unwrap(),
            Mode::Workspace(id("w-0a1b2c3d"))
        );
    }

    #[test]
    fn the_purge_flag_in_either_order_purges_the_workspace() {
        assert_eq!(
            parse(&["--workspace", "w-0a1b2c3d", "--purge"]).unwrap(),
            Mode::Purge(id("w-0a1b2c3d"))
        );
        assert_eq!(
            parse(&["--purge", "--workspace", "w-0a1b2c3d"]).unwrap(),
            Mode::Purge(id("w-0a1b2c3d"))
        );
    }

    #[test]
    fn an_id_of_32_characters_is_the_longest() {
        let longest = "a".repeat(32);
        assert_eq!(
            parse(&["--workspace", &longest]).unwrap(),
            Mode::Workspace(id(&longest))
        );
        assert_usage_error(parse(&["--workspace", &"a".repeat(33)]), "33 characters");
    }

    #[test]
    fn bad_ids_are_usage_errors() {
        for bad in [
            "", "../x", "a/b", "Standard", "STANDARD", "über", "a b", "a_b", "a.b", "a|b", "\u{0}",
        ] {
            assert_usage_error(parse(&["--workspace", bad]), &format!("id {bad:?}"));
        }
    }

    #[test]
    fn missing_ids_and_unknown_arguments_are_usage_errors() {
        for bad in [
            &["--workspace"][..],
            &["--purge"],
            &["--workspace", "a", "--workspace", "b"],
            &["--workspace", "a", "--purge", "--purge"],
            &["--workspace=a"],
            &["--verbose"],
            &["-w", "a"],
            &["standard"],
            &["--workspace", "a", "extra"],
        ] {
            assert_usage_error(parse(bad), &format!("{bad:?}"));
        }
    }

    #[cfg(unix)]
    #[test]
    fn an_id_that_is_no_utf8_is_a_usage_error() {
        use std::os::unix::ffi::OsStringExt;
        let args = [
            OsString::from("--workspace"),
            OsString::from_vec(vec![b'a', 0xff]),
        ];
        assert_usage_error(Mode::from_args(args), "non-UTF-8 id");
    }

    #[test]
    fn the_paths_lie_in_the_workspace_dir() {
        let ws = workspace("w-0a1b2c3d", "Kunde A", false);
        let base = Path::new("/data");
        let dir = base.join("workspaces").join("w-0a1b2c3d");
        assert_eq!(ws.data_dir(base), dir);
        assert_eq!(ws.run_dir(base), dir.join("run"));
        assert_eq!(ws.lock_path(base), dir.join("instance.lock"));
    }

    #[test]
    fn legacy_keys_carry_no_prefix() {
        assert_eq!(workspace("standard", "Standard", true).keyring_prefix(), "");
    }

    #[test]
    fn new_keys_carry_the_workspace_id() {
        let expected = if cfg!(windows) {
            "com.admincave.adminhelper/ws:w-0a1b2c3d|"
        } else {
            "ws:w-0a1b2c3d|"
        };
        assert_eq!(
            workspace("w-0a1b2c3d", "Kunde A", false).keyring_prefix(),
            expected
        );
        // The separator ends the id: no key of workspace "ab" starts with the prefix of "a".
        let key_of_ab = format!(
            "{}enroll|key",
            workspace("ab", "AB", false).keyring_prefix()
        );
        assert!(!key_of_ab.starts_with(&workspace("a", "A", false).keyring_prefix()));
    }

    #[test]
    fn the_window_title_names_the_workspace() {
        assert_eq!(
            workspace("w-0a1b2c3d", "Kunde A", false).window_title(),
            "Kunde A — AdminHelper"
        );
        assert_eq!(LAUNCHER_TITLE, "AdminHelper");
    }

    #[test]
    fn the_log_name_names_the_workspace() {
        assert_eq!(
            workspace("w-0a1b2c3d", "Kunde A", false).log_name(),
            "adminhelper-w-0a1b2c3d"
        );
        assert_eq!(Mode::Launcher.log_name(), "adminhelper");
        assert_eq!(
            Mode::Workspace(id("w-0a1b2c3d")).log_name(),
            "adminhelper-w-0a1b2c3d"
        );
        // The purge child writes its own workspace's log, never the launcher's.
        assert_eq!(
            Mode::Purge(id("w-0a1b2c3d")).log_name(),
            "adminhelper-w-0a1b2c3d"
        );
    }

    #[test]
    fn current_without_a_workspace_is_an_error() {
        assert!(matches!(current(), Err(AppError::Validation(_))));
    }

    #[test]
    fn current_answers_the_entered_workspace_while_its_guard_lives() {
        let a = workspace("a", "A", false);
        let b = workspace("b", "B", true);
        {
            let _a = enter(a.clone());
            assert_eq!(current().unwrap(), a);
            {
                let _b = enter(b.clone());
                assert_eq!(current().unwrap(), b);
            }
            assert_eq!(current().unwrap(), a);
            // One thread, one workspace: another thread has none.
            std::thread::spawn(|| assert!(current().is_err()))
                .join()
                .unwrap();
        }
        assert!(current().is_err());
    }

    #[test]
    fn a_process_takes_its_workspace_once() {
        // The only test that touches the process-wide workspace; the others read their guard.
        let scratch = Scratch::new("set-current");
        set_current(held(&scratch.0, workspace("a", "A", false))).unwrap();
        assert!(set_current(held(&scratch.0, workspace("b", "B", false))).is_err());
        assert!(
            current().is_err(),
            "a test build never reads the process-wide workspace"
        );
    }

    #[test]
    fn a_second_acquire_finds_the_lock_taken_until_the_first_drops() {
        let scratch = Scratch::new("lock-twice");
        let path = workspace("a", "A", false).lock_path(&scratch.0);
        fs::create_dir_all(path.parent().unwrap()).unwrap();

        let first = acquire(&path).unwrap().expect("a fresh lock is free");
        assert_private(&path);
        let started = Instant::now();
        assert!(acquire(&path).unwrap().is_none(), "taken twice");
        assert!(
            started.elapsed() >= ACQUIRE_TIMEOUT,
            "gave up after {:?}",
            started.elapsed()
        );

        drop(first);
        // At once, not when Windows gets round to the closed handle.
        assert!(acquire_within(&path, Duration::ZERO).unwrap().is_some());
    }

    #[test]
    fn acquire_never_creates_the_directory_of_a_workspace() {
        let scratch = Scratch::new("lock-nodir");
        let path = workspace("gone", "Gone", false).lock_path(&scratch.0);

        assert!(acquire(&path).is_err());
        assert!(!path.parent().unwrap().exists());
    }

    #[test]
    fn is_open_answers_whether_the_lock_is_held_and_leaves_it_be() {
        let scratch = Scratch::new("lock-probe");
        let path = scratch.0.join("instance.lock");

        // A workspace that never ran has no lock file, and the probe leaves none behind.
        assert!(!is_open(&path).unwrap());
        assert!(!path.exists());
        assert!(!is_open(&scratch.0.join("missing").join("instance.lock")).unwrap());

        let held = acquire(&path).unwrap().unwrap();
        assert!(is_open(&path).unwrap());
        // The probe took nothing from the holder.
        assert!(acquire_within(&path, BRIEF).unwrap().is_none());

        drop(held);
        assert!(!is_open(&path).unwrap());
        // ... and holds nothing once it answered, not even until Windows gets round to its
        // closed handle.
        assert!(acquire_within(&path, Duration::ZERO).unwrap().is_some());
    }

    #[test]
    fn acquire_outlasts_a_probe_that_holds_the_lock_as_it_starts() {
        let scratch = Scratch::new("lock-race");
        let path = scratch.0.join("instance.lock");
        // The picker probes just as the workspace process starts: the probe has the lock first.
        let probe = acquire(&path).unwrap().unwrap();

        let starting = {
            let path = path.clone();
            thread::spawn(move || acquire(&path))
        };
        thread::sleep(Duration::from_millis(200));
        assert!(
            !starting.is_finished(),
            "acquire gave up on the probe's lock"
        );

        drop(probe);
        let held = starting.join().unwrap().unwrap();
        assert!(held.is_some(), "the starting process lost its lock");
        assert!(is_open(&path).unwrap());
    }

    fn registry() -> Registry {
        Registry {
            workspaces: vec![
                RegistryEntry { id: id("standard") },
                RegistryEntry {
                    id: id("w-0a1b2c3d"),
                },
            ],
            last_used: Some(id("standard")),
            migrated_notice: true,
            unreadable_settings: Some("settings.json.unreadable-20261021T080000Z".to_string()),
        }
    }

    fn meta() -> Meta {
        Meta {
            kind: SyncMode::Server,
            name: "Kunde A".to_string(),
            color: PALETTE[1].to_string(),
            url: Some("https://ah.example.com".to_string()),
            interval_minutes: 5,
            allow_self_signed_certs: true,
            last_username: Some("admin".to_string()),
            legacy_keys: false,
        }
    }

    #[test]
    fn the_registry_round_trips_under_its_wire_names() {
        let scratch = Scratch::new("registry");
        assert_eq!(Registry::load(&scratch.0).unwrap(), None, "no registry yet");

        registry().store(&scratch.0).unwrap();

        assert_eq!(Registry::load(&scratch.0).unwrap(), Some(registry()));
        let path = scratch.0.join(REGISTRY_FILE);
        let written: serde_json::Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        assert_eq!(
            written,
            serde_json::json!({
                "workspaces": [{"id": "standard"}, {"id": "w-0a1b2c3d"}],
                "lastUsed": "standard",
                "migratedNotice": true,
                "unreadableSettings": "settings.json.unreadable-20261021T080000Z",
            })
        );
        assert_eq!(names_in(&scratch.0), [REGISTRY_FILE]);
        assert_private(&path);
    }

    #[test]
    fn the_meta_round_trips_under_its_wire_names() {
        let scratch = Scratch::new("meta");
        let dir = workspace("w-0a1b2c3d", "Kunde A", false).data_dir(&scratch.0);

        meta().store(&dir).unwrap();

        assert_eq!(Meta::load(&dir).unwrap(), meta());
        let local = Meta {
            kind: SyncMode::Local,
            url: None,
            last_username: None,
            legacy_keys: true,
            ..meta()
        };
        local.store(&dir).unwrap();
        assert_eq!(Meta::load(&dir).unwrap(), local);

        let path = dir.join(META_FILE);
        let written: serde_json::Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        assert_eq!(
            written,
            serde_json::json!({
                "kind": "local",
                "name": "Kunde A",
                "color": PALETTE[1],
                "url": null,
                "intervalMinutes": 5,
                "allowSelfSignedCerts": true,
                "lastUsername": null,
                "legacyKeys": true,
            })
        );
        assert_eq!(names_in(&dir), [META_FILE]);
        assert_private(&path);
    }

    #[test]
    fn a_broken_registry_is_an_error_and_stays_as_it_is() {
        let scratch = Scratch::new("registry-broken");
        let path = scratch.0.join(REGISTRY_FILE);
        for broken in [
            "{not json",
            "",
            r#"{"workspaces": [{"id": "../x"}], "lastUsed": null, "migratedNotice": false}"#,
            r#"{"workspaces": [{"id": "a"}], "lastUsed": "Standard", "migratedNotice": false}"#,
            r#"{"workspaces": [{"name": "a"}], "lastUsed": null, "migratedNotice": false}"#,
            r#"{"lastUsed": null, "migratedNotice": false}"#,
        ] {
            fs::write(&path, broken).unwrap();
            assert!(Registry::load(&scratch.0).is_err(), "{broken:?} loaded");
            assert_eq!(fs::read_to_string(&path).unwrap(), broken);
        }
    }

    #[test]
    fn a_missing_or_broken_meta_is_an_error() {
        let scratch = Scratch::new("meta-broken");
        assert!(Meta::load(&scratch.0).is_err(), "no workspace.json");

        let mut cloud = serde_json::to_value(meta()).unwrap();
        cloud["kind"] = "cloud".into();
        let mut nameless = serde_json::to_value(meta()).unwrap();
        nameless.as_object_mut().unwrap().remove("name");
        for broken in [
            "{not json".to_string(),
            cloud.to_string(),
            nameless.to_string(),
        ] {
            fs::write(scratch.0.join(META_FILE), &broken).unwrap();
            assert!(Meta::load(&scratch.0).is_err(), "{broken:?} loaded");
        }
    }

    #[test]
    fn the_palette_holds_distinct_css_hex_colours() {
        assert!(PALETTE.len() >= 6);
        for (i, colour) in PALETTE.iter().enumerate() {
            let hex = colour
                .strip_prefix('#')
                .unwrap_or_else(|| panic!("{colour}"));
            assert!(
                hex.len() == 6 && hex.bytes().all(|b| b"0123456789abcdef".contains(&b)),
                "{colour}"
            );
            assert!(!PALETTE[..i].contains(colour), "{colour} twice");
        }
    }

    #[test]
    fn the_context_is_the_launcher_or_the_workspace_of_this_process_under_its_wire_names() {
        let scratch = Scratch::new("context");
        let ws = workspace("w-0a1b2c3d", "Kunde A", false);
        meta().store(&ws.data_dir(&scratch.0)).unwrap();

        let launcher = context(&scratch.0).unwrap();
        assert_eq!(
            serde_json::to_value(launcher).unwrap(),
            serde_json::json!({ "launcher": true, "workspace": null })
        );

        let _entered = enter(ws.clone());
        let own = context(&scratch.0).unwrap();
        assert_eq!(
            serde_json::to_value(own).unwrap(),
            serde_json::json!({
                "launcher": false,
                "workspace": {
                    "id": "w-0a1b2c3d",
                    "name": "Kunde A",
                    "color": PALETTE[1],
                    "kind": "server",
                    "url": "https://ah.example.com",
                    "host": "ah.example.com",
                    "open": true,
                },
            })
        );

        // A workspace without a URL has neither a URL nor a host.
        let local = Meta {
            kind: SyncMode::Local,
            url: None,
            ..meta()
        };
        local.store(&ws.data_dir(&scratch.0)).unwrap();
        let own = context(&scratch.0).unwrap().workspace.expect("a workspace");
        assert_eq!(own.url, None);
        assert_eq!(own.host, None);
        assert_eq!(own.kind, SyncMode::Local);
    }

    #[test]
    fn the_info_names_the_workspace_url_with_the_user_masked_and_otherwise_as_kept() {
        let info = |url: Option<&str>| {
            Meta {
                url: url.map(String::from),
                ..meta()
            }
            .info(id("w-0a1b2c3d"), false)
        };

        // Without a user, a query and a fragment, the URL as kept, however it is spelled.
        for kept in [
            "https://ah.example.com",
            "https://AH.example.com:8443/base/",
            "https://sync.example.com/connections.json",
        ] {
            assert_eq!(info(Some(kept)).url.as_deref(), Some(kept));
        }

        // A user, a password or both are one `***@`, the parser spells the rest; the host stays.
        for (kept, shown, host) in [
            (
                "https://admin:secret@ah.example.com",
                "https://***@ah.example.com/",
                "ah.example.com",
            ),
            (
                "https://admin@ah.example.com:8443/base",
                "https://***@ah.example.com:8443/base",
                "ah.example.com",
            ),
            (
                "https://:secret@ah.example.com/x",
                "https://***@ah.example.com/x",
                "ah.example.com",
            ),
            (
                "https://user:pw@sync.example.com/connections.json?a=b",
                "https://***@sync.example.com/connections.json?a=***",
                "sync.example.com",
            ),
        ] {
            let info = info(Some(kept));
            assert_eq!(info.url.as_deref(), Some(shown), "{kept}");
            assert_eq!(info.host.as_deref(), Some(host), "{kept}");
        }

        // No URL is none, and so is one that does not parse: nothing of it reaches the webview.
        assert_eq!(info(None).url, None);
        let unparsed = info(Some("https://admin:secret@ah example.com"));
        assert_eq!(unparsed.url, None);
        assert_eq!(unparsed.host, None);
    }

    #[test]
    fn the_shown_workspace_url_masks_the_query_values_and_the_fragment_and_stays_so() {
        for (kept, shown) in [
            // Each value of the query, a key twice as well; the keys stay, in the parser's
            // spelling.
            (
                "https://sync.example.com/c.json?token=abc&user=me&token=def&a%20b=x%26y",
                "https://sync.example.com/c.json?token=***&user=***&token=***&a+b=***",
            ),
            // A part without a value may be the token itself; one with an empty value goes too.
            (
                "https://sync.example.com/c.json?s3cr3t&token=&a=1",
                "https://sync.example.com/c.json?***&***&a=***",
            ),
            // The fragment, whatever it holds.
            (
                "https://ah.example.com/#access_token=abc",
                "https://ah.example.com/#***",
            ),
            (
                "https://ah.example.com/app#/route?x=1",
                "https://ah.example.com/app#***",
            ),
            // A user and a password, the query and the fragment at once.
            (
                "https://admin:secret@sync.example.com:8443/c.json?token=abc#frag",
                "https://***@sync.example.com:8443/c.json?token=***#***",
            ),
            (
                "https://admin@AH.example.com/?k=v",
                "https://***@ah.example.com/?k=***",
            ),
            // An empty query and an empty fragment hide nothing: as kept.
            ("https://ah.example.com/?#", "https://ah.example.com/?#"),
        ] {
            assert_eq!(shown_url(kept).as_deref(), Some(shown), "{kept}");
            // Masking what it shows changes nothing: the launcher tells an unchanged URL by it.
            assert_eq!(shown_url(shown).as_deref(), Some(shown), "{shown}");
        }

        assert_eq!(shown_url("https://ah example.com/?token=abc"), None);
    }

    #[test]
    fn the_shown_workspace_url_masks_the_user_and_the_password_as_one_and_stays_so() {
        for (kept, shown, gone) in [
            // A user and a password, a user alone, a password alone: one `***@`.
            (
                "https://admin:secret@ah.example.com/base",
                "https://***@ah.example.com/base",
                &["admin", "secret"][..],
            ),
            (
                "https://admin@ah.example.com/base",
                "https://***@ah.example.com/base",
                &["admin"][..],
            ),
            (
                "https://:secret@ah.example.com/base",
                "https://***@ah.example.com/base",
                &["secret"][..],
            ),
            // Percent-encoded as kept, or by the parser: neither spelling is left.
            (
                "https://ad%40min:se%3Acr%C3%A9t@ah.example.com",
                "https://***@ah.example.com/",
                &["ad%40min", "ad@min", "se%3Acr%C3%A9t", "se:crét", "%"][..],
            ),
            (
                "https://ad min:sé@ah.example.com",
                "https://***@ah.example.com/",
                &["ad min", "ad%20min", "sé", "s%C3%A9", "%"][..],
            ),
            // An `@` in the user: the last one ends the user info, all of it goes.
            (
                "https://admin@corp:secret@ah.example.com/",
                "https://***@ah.example.com/",
                &["admin", "corp", "secret", "%40"][..],
            ),
            // A user masked before keeps the mask, a password goes; the port and the host stay.
            (
                "https://***:secret@[::1]:8443/",
                "https://***@[::1]:8443/",
                &["secret"][..],
            ),
        ] {
            let masked = shown_url(kept).unwrap_or_else(|| panic!("{kept} does not parse"));
            assert_eq!(masked, shown, "{kept}");
            for part in gone {
                assert!(!masked.contains(part), "{part} of {kept} in {masked}");
            }
            let parsed = Url::parse(&masked).unwrap();
            assert_eq!(
                (parsed.username(), parsed.password()),
                ("***", None),
                "{masked}"
            );
            // Masking what it shows changes nothing: the launcher tells an unchanged URL by it.
            assert_eq!(shown_url(shown).as_deref(), Some(shown), "{shown}");
        }
    }

    #[test]
    fn the_context_of_a_workspace_whose_workspace_json_does_not_load_is_an_error() {
        let scratch = Scratch::new("context-broken");
        let ws = workspace("w-0a1b2c3d", "Kunde A", false);
        let dir = ws.data_dir(&scratch.0);
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join(META_FILE), "{not json").unwrap();
        let _entered = enter(ws);
        assert!(context(&scratch.0).is_err());
    }

    #[test]
    fn a_command_runs_only_in_the_process_it_is_for() {
        let ws = workspace("w-0a1b2c3d", "Kunde A", false);
        assert!(check_side(Side::Launcher, None).is_ok());
        assert!(check_side(Side::Workspace, Some(&ws)).is_ok());

        let in_a_workspace = check_side(Side::Launcher, Some(&ws)).unwrap_err();
        assert!(
            matches!(&in_a_workspace, AppError::Validation(msg)
                if msg.contains("only the launcher") && msg.contains("w-0a1b2c3d")),
            "{in_a_workspace:?}"
        );
        let in_the_launcher = check_side(Side::Workspace, None).unwrap_err();
        assert!(
            matches!(&in_the_launcher, AppError::Validation(msg)
                if msg.contains("only the process of a workspace")),
            "{in_the_launcher:?}"
        );
    }

    // ── Where a workspace signs in, and that a user of a server signs in in one workspace ──

    /// [`meta`] as a server workspace with `url`.
    fn server(url: Option<&str>) -> Meta {
        Meta {
            kind: SyncMode::Server,
            url: url.map(String::from),
            ..meta()
        }
    }

    /// The workspace `id_` named `name` at the server `url`, last signed in as `user`.
    fn signed_in(id_: &str, name: &str, url: &str, user: &str) -> (WorkspaceId, Meta) {
        let meta = Meta {
            name: name.to_string(),
            last_username: Some(user.to_string()),
            ..server(Some(url))
        };
        (id(id_), meta)
    }

    fn assert_refused<T: std::fmt::Debug>(result: Result<T, AppError>, says: &str, case: &str) {
        assert!(
            matches!(&result, Err(AppError::Validation(msg)) if msg.contains(says)),
            "{case}: {result:?}"
        );
    }

    #[test]
    fn login_binding_takes_the_url_of_the_workspace_and_refuses_another_server() {
        let kept = server(Some("https://ah.example.com"));
        // The server of the workspace, however the URL names it: the sign-in goes to the URL of
        // the workspace.
        for same in [
            "https://ah.example.com",
            " https://ah.example.com/ ",
            "https://AH.example.com:443",
            "https://ah.example.com/somewhere",
        ] {
            assert_eq!(
                sign_in_url(&kept, same).unwrap(),
                "https://ah.example.com",
                "{same:?}"
            );
        }
        for other in [
            "https://other.example.com",
            "https://ah.example.com:8443",
            "http://ah.example.com",
            "https://ah.example.com.other.example",
            "https://user@other.example.com",
            "ah.example.com",
            "",
        ] {
            assert_refused(
                sign_in_url(&kept, other),
                "this workspace belongs to the server https://ah.example.com",
                other,
            );
        }
        // A URL of the workspace that does not parse names no server to match.
        assert_refused(
            sign_in_url(&server(Some("not a url")), "not a url"),
            "this workspace belongs to the server",
            "unparsed",
        );
    }

    #[test]
    fn login_binding_without_a_url_of_the_workspace_takes_the_one_sent() {
        assert_eq!(
            sign_in_url(&server(None), " https://ah.example.com/ ").unwrap(),
            "https://ah.example.com/"
        );
    }

    #[test]
    fn login_binding_https_h_and_https_h_443_are_one_server() {
        assert_eq!(
            sign_in_url(&server(Some("https://H")), "https://h:443/").unwrap(),
            "https://H"
        );
        assert_eq!(
            sign_in_url(&server(Some("https://h:443/")), "https://H").unwrap(),
            "https://h:443/"
        );
        let other = signed_in("w-0000000a", "Kunde A", "https://H", "admin");
        assert_refused(
            check_sign_in_once(&id("w-0000000b"), "https://h:443/", "admin", &[other]),
            "\"Kunde A\"",
            "one server",
        );
    }

    #[test]
    fn login_binding_only_a_server_workspace_signs_in_or_registers() {
        for kind in [SyncMode::Sync, SyncMode::Local] {
            for url in [Some("https://ah.example.com"), None] {
                let meta = Meta {
                    kind: kind.clone(),
                    url: url.map(String::from),
                    ..meta()
                };
                assert_refused(
                    sign_in_url(&meta, "https://ah.example.com"),
                    "only a server workspace",
                    &format!("{kind:?} {url:?}"),
                );
            }
        }
    }

    #[test]
    fn login_binding_the_url_of_the_workspace_comes_trimmed_and_an_error_names_its_origin_only() {
        let kept = server(Some(
            " https://ops:geheim@AH.example.com:443/base?token=t1 ",
        ));
        assert_eq!(
            sign_in_url(&kept, "https://ah.example.com").unwrap(),
            "https://ops:geheim@AH.example.com:443/base?token=t1"
        );
        assert_eq!(
            sign_in_url(&kept, "https://other.example.com")
                .unwrap_err()
                .to_string(),
            "this workspace belongs to the server https://ah.example.com; another server is \
             another workspace"
        );
        // A URL of the workspace that does not parse, or names no server, names no server
        // either, nor itself.
        for broken in ["ops:geheim@not a url", "https://ops:geheim@", "geheim"] {
            let refused = sign_in_url(&server(Some(broken)), "https://ah.example.com")
                .unwrap_err()
                .to_string();
            assert!(
                refused.starts_with("this workspace belongs to the server its URL names;"),
                "{broken}: {refused}"
            );
            assert!(!refused.contains("geheim"), "{broken}: {refused}");
        }
    }

    #[test]
    fn login_binding_the_window_of_a_workspace_means_the_server_it_keeps() {
        // A sync workspace keeps the server of its source.
        let sync = Meta {
            kind: SyncMode::Sync,
            url: Some("https://sync.example.com/connections.json".to_string()),
            ..meta()
        };
        assert_eq!(
            own_url(&sync, " https://SYNC.example.com:443/ ").unwrap(),
            "https://sync.example.com/connections.json"
        );
        assert_refused(
            own_url(&sync, "https://ah.example.com"),
            "this workspace belongs to the server https://sync.example.com;",
            "sync",
        );
        // Until it has one, the one sent.
        let fresh = Meta { url: None, ..sync };
        assert_eq!(
            own_url(&fresh, " https://ah.example.com ").unwrap(),
            "https://ah.example.com"
        );
        // A local workspace has no server to mean.
        for url in [Some("https://ah.example.com"), None] {
            let local = Meta {
                kind: SyncMode::Local,
                url: url.map(String::from),
                ..meta()
            };
            assert_refused(
                own_url(&local, "https://ah.example.com"),
                "a local workspace has no server",
                &format!("{url:?}"),
            );
        }
        // One server however a URL spells it; none for a URL that does not parse.
        assert!(same_server("https://H", "https://h:443/path?q"));
        assert!(same_server("http://127.0.0.1", "http://127.0.0.1:80/"));
        assert!(!same_server("https://h", "http://h"));
        assert!(!same_server("https://h", "https://h:8443"));
        assert!(!same_server("not a url", "not a url"));
    }

    // ── Where the sync of a workspace loads from ──

    const SOURCE: &str = "https://sync.example/c.json?api_key=k1";

    /// [`meta`] as a sync workspace with `url`.
    fn sync_meta(url: Option<&str>) -> Meta {
        Meta {
            kind: SyncMode::Sync,
            url: url.map(String::from),
            ..meta()
        }
    }

    #[test]
    fn sync_binding_a_sync_workspace_loads_the_source_it_keeps() {
        for sent in [SOURCE, " https://sync.example/c.json?api_key=k1\n"] {
            assert_eq!(
                sync_url(&sync_meta(Some(SOURCE)), sent).unwrap(),
                SOURCE,
                "{sent:?}"
            );
        }
        // The source as it keeps it, trimmed.
        assert_eq!(
            sync_url(
                &sync_meta(Some(" https://sync.example/c.json?api_key=k1 ")),
                SOURCE
            )
            .unwrap(),
            SOURCE
        );
    }

    #[test]
    fn sync_binding_another_source_is_refused_and_the_error_names_no_url() {
        for other in [
            "https://sync.example/d.json?api_key=k1",
            "https://sync.example/c.json?api_key=k2",
            "https://sync.example/c.json",
            "https://SYNC.example/c.json?api_key=k1",
            "https://sync.example:443/c.json?api_key=k1",
            "https://other.example/c.json?api_key=k1",
            "",
        ] {
            let refused = sync_url(&sync_meta(Some(SOURCE)), other).unwrap_err();
            assert!(
                matches!(&refused, AppError::Validation(msg)
                    if msg == "this workspace syncs only from the sync URL it keeps"),
                "{other:?}: {refused:?}"
            );
        }
    }

    #[test]
    fn sync_binding_a_sync_workspace_without_a_source_syncs_nothing() {
        assert_refused(
            sync_url(&sync_meta(None), SOURCE),
            "this sync workspace has no sync URL yet",
            "no source",
        );
    }

    #[test]
    fn sync_binding_only_a_sync_workspace_syncs() {
        for kind in [SyncMode::Server, SyncMode::Local] {
            for url in [Some(SOURCE), Some("https://ah.example"), None] {
                let meta = Meta {
                    kind: kind.clone(),
                    url: url.map(String::from),
                    ..meta()
                };
                assert_refused(
                    sync_url(&meta, url.unwrap_or(SOURCE)),
                    "only a sync workspace syncs",
                    &format!("{kind:?} {url:?}"),
                );
            }
        }
    }

    #[test]
    fn login_binding_refuses_the_same_user_at_the_same_server_in_another_workspace() {
        let own = id("w-0000000b");
        let url = "https://ah.example.com";
        let workspaces = [
            signed_in("w-0000000a", "Kunde A", "https://ah.example.com", "Admin"),
            signed_in("w-0000000b", "Kunde B", url, "ops-admin"),
        ];

        for user in ["admin", " ADMIN "] {
            assert_refused(
                check_sign_in_once(&own, url, user, &workspaces),
                "the workspace \"Kunde A\" signs in to this server as this user",
                user,
            );
        }
        // Another user of the same server, the one the workspace itself last signed in as too.
        check_sign_in_once(&own, url, "ops-admin", &workspaces).unwrap();
        check_sign_in_once(&own, url, "ops", &workspaces).unwrap();
        // The same user of another server.
        for other in [
            "https://other.example.com",
            "https://ah.example.com:8443",
            "http://localhost",
        ] {
            check_sign_in_once(&own, other, "admin", &workspaces).unwrap();
        }
        // The workspace that last signed in as that user signs in again.
        check_sign_in_once(&id("w-0000000a"), url, "admin", &workspaces).unwrap();
        // Nor does a workspace without a server count, nor one that never signed in.
        let sync = Meta {
            kind: SyncMode::Sync,
            ..signed_in("w-0000000c", "Sync", url, "admin").1
        };
        let never = Meta {
            last_username: None,
            ..server(Some(url))
        };
        let others = [(id("w-0000000c"), sync), (id("w-0000000d"), never)];
        check_sign_in_once(&own, url, "admin", &others).unwrap();
        // A URL that does not parse names no server to sign in to.
        assert!(check_sign_in_once(&own, "not a url", "admin", &others).is_err());
    }

    #[test]
    fn login_binding_reads_every_workspace_that_opens() {
        let scratch = Scratch::new("metas");
        let base = &scratch.0;
        assert_refused(metas(base), "there is no workspaces.json", "no registry");

        let kept = signed_in("w-0000000a", "Kunde A", "https://ah.example.com", "admin");
        kept.1
            .store(&workspace("w-0000000a", "", false).data_dir(base))
            .unwrap();
        let broken = workspace("w-0000000b", "", false).data_dir(base);
        fs::create_dir_all(&broken).unwrap();
        fs::write(broken.join(META_FILE), r#"{"kind": "geheim"}"#).unwrap();
        Registry {
            workspaces: ["w-0000000a", "w-0000000b", "w-dir-gone"]
                .map(|ws| RegistryEntry { id: id(ws) })
                .into(),
            last_used: None,
            migrated_notice: false,
            unreadable_settings: None,
        }
        .store(base)
        .unwrap();

        assert_eq!(metas(base).unwrap(), [kept]);

        fs::write(
            base.join(REGISTRY_FILE),
            r#"{"workspaces": [{"id": "../geheim"}]}"#,
        )
        .unwrap();
        let refused = metas(base).unwrap_err().to_string();
        assert!(
            refused.starts_with("workspaces.json does not load"),
            "{refused}"
        );
        assert!(!refused.contains("geheim"), "{refused}");
    }

    #[test]
    fn login_binding_a_workspace_json_that_does_not_load_names_the_file_and_no_value() {
        let scratch = Scratch::new("context-value");
        let ws = workspace("w-0a1b2c3d", "Kunde A", false);
        let dir = ws.data_dir(&scratch.0);
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join(META_FILE), r#"{"kind": "geheim"}"#).unwrap();
        let _entered = enter(ws);

        let refused = context(&scratch.0).unwrap_err().to_string();
        assert!(
            refused.starts_with("the workspace.json of the workspace w-0a1b2c3d does not load")
                && refused.contains("line 1"),
            "{refused}"
        );
        assert!(!refused.contains("geheim"), "{refused}");
    }

    /// A `lock` for [`startup`] that must not be called: the start ends before the lock.
    fn no_lock(path: &Path) -> Result<Option<InstanceLock>, AppError> {
        panic!("took the lock at {}", path.display())
    }

    fn standard() -> Workspace {
        workspace("standard", "Standard", true)
    }

    /// The code and line of a start that ends; a panic for one that does not.
    fn exit_of(plan: Plan) -> (i32, String) {
        match plan {
            Plan::Exit { code, line } => (code, line),
            other => panic!("expected an exit, got {other:?}"),
        }
    }

    #[test]
    fn startup_of_the_launcher_moves_the_data_and_opens_the_picker() {
        let scratch = Scratch::new("startup-launcher");

        let plan = startup(Mode::Launcher, &scratch.0, no_lock);

        assert!(matches!(plan, Plan::Launcher), "{plan:?}");
        assert_eq!(plan.log_name().as_deref(), Some("adminhelper"));
        let registry = Registry::load(&scratch.0)
            .unwrap()
            .expect("the migration ran");
        assert_eq!(registry.workspaces, [RegistryEntry { id: id("standard") }]);
    }

    #[test]
    fn startup_of_a_known_workspace_holds_its_lock_before_it_names_it() {
        let scratch = Scratch::new("startup-known");
        let base = &scratch.0;
        let lock_path = standard().lock_path(base);
        let dir = standard().data_dir(base);

        // A first start straight into the workspace: the migration makes it.
        let mut asked = None;
        let plan = startup(Mode::Workspace(id("standard")), base, |path| {
            asked = Some(path.to_path_buf());
            let lock = acquire(path);
            // The picker renamed the workspace under its lock until just now: the start reads
            // the workspace once it holds the lock, so it finds the new name.
            let renamed = Meta {
                name: "Kunde A".to_string(),
                ..Meta::load(&dir).unwrap()
            };
            renamed.store(&dir).unwrap();
            lock
        });

        assert_eq!(asked.as_deref(), Some(lock_path.as_path()));
        let Plan::Workspace(held) = &plan else {
            panic!("expected the workspace, got {plan:?}");
        };
        assert_eq!(held.workspace, workspace("standard", "Kunde A", true));
        assert_eq!(held.workspace.window_title(), "Kunde A — AdminHelper");
        assert_eq!(plan.log_name().as_deref(), Some("adminhelper-standard"));
        assert!(is_open(&lock_path).unwrap(), "the plan holds the lock");
        drop(plan);
        assert!(!is_open(&lock_path).unwrap(), "gone with the plan");
    }

    #[test]
    fn startup_of_a_purge_holds_its_workspace_too() {
        let scratch = Scratch::new("startup-purge");
        let base = &scratch.0;

        let plan = startup(Mode::Purge(id("standard")), base, acquire);

        let Plan::Purge(held, meta) = &plan else {
            panic!("expected the purge, got {plan:?}");
        };
        assert_eq!(held.workspace, standard());
        assert_eq!(
            meta.as_ref(),
            Some(&Meta::load(&standard().data_dir(base)).unwrap())
        );
        assert!(is_open(&standard().lock_path(base)).unwrap());
        assert_eq!(plan.log_name().as_deref(), Some("adminhelper-standard"));
    }

    #[test]
    fn startup_of_a_purge_goes_by_the_id_when_the_workspace_json_does_not_load() {
        let scratch = Scratch::new("startup-purge-meta");
        let base = &scratch.0;
        startup(Mode::Launcher, base, no_lock);
        let made = workspace("w-0a1b2c3d", "", false);
        meta().store(&made.data_dir(base)).unwrap();
        let mut registry = Registry::load(base).unwrap().unwrap();
        registry.workspaces.push(RegistryEntry {
            id: made.id.clone(),
        });
        registry.store(base).unwrap();

        // Whether it keeps its keys without a prefix follows from its id: the migration made
        // `standard`, the launcher the other one.
        for expected in [workspace("standard", "", true), made] {
            let meta_path = expected.data_dir(base).join(META_FILE);
            let lock_path = expected.lock_path(base);
            for broken in [Some(r#"{"kind": "geheim"}"#), None] {
                let case = format!("{} {broken:?}", expected.id);
                match broken {
                    Some(broken) => fs::write(&meta_path, broken).unwrap(),
                    None => fs::remove_file(&meta_path).unwrap(),
                }

                let plan = startup(Mode::Purge(expected.id.clone()), base, acquire);

                let Plan::Purge(held, meta) = &plan else {
                    panic!("{case}: expected the purge, got {plan:?}");
                };
                assert_eq!(meta, &None, "{case}");
                assert_eq!(held.workspace, expected, "{case}");
                assert!(is_open(&lock_path).unwrap(), "{case}");
                assert_eq!(plan.log_name(), Some(expected.log_name()), "{case}");
                drop(plan);
                assert!(!is_open(&lock_path).unwrap(), "{case}");
            }
        }
    }

    #[test]
    fn startup_of_a_purge_goes_by_the_id_when_the_directory_is_gone() {
        let scratch = Scratch::new("startup-purge-nodir");
        let base = &scratch.0;
        startup(Mode::Launcher, base, no_lock);
        let mut registry = Registry::load(base).unwrap().unwrap();
        for gone in ["w-dir-gone", "server"] {
            registry.workspaces.push(RegistryEntry { id: id(gone) });
        }
        registry.store(base).unwrap();

        for expected in [
            workspace("w-dir-gone", "", false),
            workspace("server", "", true),
        ] {
            let plan = startup(Mode::Purge(expected.id.clone()), base, no_lock);

            let Plan::Purge(held, meta) = &plan else {
                panic!("expected the purge, got {plan:?}");
            };
            assert_eq!(meta, &None);
            assert_eq!(held.workspace, expected);
            // It holds no lock, so the log of the workspace is not its own.
            assert_eq!(plan.log_name(), None);
            assert!(!expected.data_dir(base).exists());
        }
    }

    #[test]
    fn startup_of_an_unknown_workspace_ends_with_2_before_its_lock() {
        let scratch = Scratch::new("startup-unknown");
        let base = &scratch.0;
        startup(Mode::Launcher, base, no_lock);
        // Named by the registry without a directory, a directory the registry does not name.
        let mut registry = Registry::load(base).unwrap().unwrap();
        registry.workspaces.push(RegistryEntry {
            id: id("w-dir-gone"),
        });
        registry.store(base).unwrap();
        let unlisted = workspace("w-unlisted", "Unlisted", false).data_dir(base);
        meta().store(&unlisted).unwrap();

        for unknown in ["w-0a1b2c3d", "w-dir-gone", "w-unlisted"] {
            for mode in [Mode::Workspace(id(unknown)), Mode::Purge(id(unknown))] {
                if unknown == "w-dir-gone" && matches!(mode, Mode::Purge(_)) {
                    // A purge needs no more than the registry entry
                    // (`startup_of_a_purge_goes_by_the_id_when_the_directory_is_gone`).
                    continue;
                }
                let case = format!("{mode:?}");
                let plan = startup(mode, base, no_lock);
                assert_eq!(plan.log_name(), None, "{case}");
                let (code, line) = exit_of(plan);
                assert_eq!(code, EXIT_UNKNOWN, "{case}");
                assert_eq!(line, format!("there is no workspace {unknown}"), "{case}");
            }
        }
        // A start never brings back the directory of a workspace.
        assert!(!workspace("w-dir-gone", "", false).data_dir(base).exists());
        assert!(!workspace("w-0a1b2c3d", "", false).data_dir(base).exists());
    }

    #[test]
    fn startup_with_a_taken_lock_ends_with_3_and_writes_no_log_file() {
        let scratch = Scratch::new("startup-taken");
        let base = &scratch.0;
        let holder = startup(Mode::Workspace(id("standard")), base, acquire);
        assert!(matches!(holder, Plan::Workspace(_)), "{holder:?}");

        for mode in [Mode::Workspace(id("standard")), Mode::Purge(id("standard"))] {
            let case = format!("{mode:?}");
            let second = startup(mode, base, |path| acquire_within(path, BRIEF));
            // Not the holder's log, which the log plugin would open and may rotate: the line of
            // a process that does not start goes to stderr alone.
            assert_eq!(second.log_name(), None, "{case}");
            // No workspace held, so none to set (`set_current` takes a `Held`): what this
            // process would do in the data dir, emptying `run/` first of all, stays with the
            // holder.
            let (code, line) = exit_of(second);
            assert_eq!(code, EXIT_TAKEN, "{case}");
            assert_eq!(line, "the workspace standard is open in another process");
        }
        assert!(is_open(&standard().lock_path(base)).unwrap(), "still held");
        drop(holder);
    }

    #[test]
    fn startup_after_a_failed_migration_starts_no_process() {
        let scratch = Scratch::new("startup-migration");
        let base = &scratch.0;
        // A file where the workspaces go stops the migration, before it sets aside the settings
        // that do not parse.
        let broken = r#"{"mode": "geheim"}"#;
        fs::write(base.join("workspaces"), "").unwrap();
        fs::write(base.join("settings.json"), broken).unwrap();

        for mode in [Mode::Launcher, Mode::Workspace(id("standard"))] {
            let case = format!("{mode:?}");
            let (code, line) = exit_of(startup(mode, base, no_lock));
            assert_eq!(code, EXIT_FAILED, "{case}");
            assert!(
                line.contains("workspaces is a symlink, a junction or a file"),
                "{line}"
            );
            assert_eq!(Registry::load(base).unwrap(), None, "{case}");
            assert_eq!(
                fs::read_to_string(base.join("settings.json")).unwrap(),
                broken,
                "{case}"
            );
        }
    }

    #[test]
    fn startup_after_a_migration_that_set_the_settings_aside_opens_standard() {
        // Settings that do not parse end no start: the app started with them before R-0431.
        let scratch = Scratch::new("startup-set-aside");
        let base = &scratch.0;
        fs::write(base.join("settings.json"), r#"{"mode": "geheim"}"#).unwrap();

        let plan = startup(Mode::Launcher, base, no_lock);

        assert!(matches!(plan, Plan::Launcher), "{plan:?}");
        let registry = Registry::load(base).unwrap().expect("the migration ran");
        assert!(registry.unreadable_settings.is_some(), "{registry:?}");
        let plan = startup(Mode::Workspace(id("standard")), base, acquire);
        let Plan::Workspace(held) = &plan else {
            panic!("expected the workspace, got {plan:?}");
        };
        assert_eq!(held.workspace, standard());
        assert_eq!(
            Meta::load(&standard().data_dir(base)).unwrap().kind,
            SyncMode::Local
        );
    }

    #[test]
    fn startup_with_a_workspace_json_that_does_not_load_ends_with_1() {
        let scratch = Scratch::new("startup-meta");
        let base = &scratch.0;
        startup(Mode::Launcher, base, no_lock);
        let dir = standard().data_dir(base);
        fs::write(dir.join(META_FILE), r#"{"kind": "geheim"}"#).unwrap();

        let (code, line) = exit_of(startup(Mode::Workspace(id("standard")), base, acquire));

        assert_eq!(code, EXIT_FAILED);
        assert!(
            line.starts_with("the workspace.json of the workspace standard"),
            "{line}"
        );
        assert!(!line.contains("geheim"), "{line}");
        assert!(!is_open(&standard().lock_path(base)).unwrap(), "given back");
    }
}
