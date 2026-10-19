// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! The workspace of this process (R-0431): how the process was started (launcher, workspace,
//! purge), the id it was started with, and what follows from the workspace — its data dir,
//! keyring prefix, log and window names. A process serves one workspace for its whole life;
//! the launcher serves none. Also the lock that keeps a workspace in one process and the two
//! files that say which workspaces exist (`workspaces.json`) and what each one is
//! (`workspace.json`).

#![cfg_attr(
    not(test),
    expect(
        dead_code,
        reason = "no callers yet: the migration (R-0431 T4), the start of the workspace process \
                  (T10) and the launcher (T11) take it up"
    )
)]

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

use crate::error::AppError;
use crate::models::SyncMode;
use crate::storage::write_json_pretty;

/// Every character an id may hold (`^[a-z0-9-]{1,32}$`), spelled out rather than as ranges, so
/// no reader has to wonder whether a locale widens them.
const ID_CHARS: &[u8] = b"abcdefghijklmnopqrstuvwxyz0123456789-";
const ID_MAX_LEN: usize = 32;

const USAGE: &str = "usage: adminhelper [--workspace <id> [--purge]]";

/// Title of the launcher window; a workspace window puts its name in front.
pub const LAUNCHER_TITLE: &str = "AdminHelper";

/// Log file name (without extension) of the launcher; a workspace process appends `-<id>`.
const LAUNCHER_LOG_NAME: &str = "adminhelper";

/// How long [`acquire`] keeps trying. The picker probes the lock of every workspace it lists
/// ([`is_open`]); a process that starts during a probe must not give up on it.
const ACQUIRE_TIMEOUT: Duration = Duration::from_secs(2);
const ACQUIRE_RETRY: Duration = Duration::from_millis(50);

/// In the app data dir: which workspaces exist ([`Registry`]).
const REGISTRY_FILE: &str = "workspaces.json";
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

impl Workspace {
    /// `<base>/workspaces/<id>`, `base` being the app data dir.
    pub fn data_dir(&self, base: &Path) -> PathBuf {
        base.join("workspaces").join(&self.id.0)
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
    _file: File,
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
            Ok(()) => return Ok(Some(InstanceLock { _file: file })),
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
        Ok(()) => Ok(false),
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
/// first, and whether the picker still owes the note on the migration. Written by the migration
/// and the launcher; its arrival ends the migration.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct Registry {
    pub workspaces: Vec<RegistryEntry>,
    pub last_used: Option<WorkspaceId>,
    pub migrated_notice: bool,
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

    pub fn store(&self, base: &Path) -> Result<(), AppError> {
        write_json_pretty(&base.join(REGISTRY_FILE), self)
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

    pub fn store(&self, dir: &Path) -> Result<(), AppError> {
        write_json_pretty(&dir.join(META_FILE), self)
    }
}

/// The workspace of this process, set once at start; the launcher never sets it.
static CURRENT: OnceLock<Workspace> = OnceLock::new();

/// Make `workspace` the one of this process. Only once: a process never changes its workspace,
/// so nothing it keyed by one prefix or path reaches another workspace.
pub fn set_current(workspace: Workspace) -> Result<(), AppError> {
    CURRENT.set(workspace).map_err(|_| {
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
    let workspace = CURRENT.get().cloned();
    workspace
        .ok_or_else(|| AppError::Validation("no workspace in this process (launcher)".to_string()))
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

    use super::{
        acquire, acquire_within, current, enter, is_open, set_current, AppError, Meta, Mode,
        Registry, RegistryEntry, Workspace, WorkspaceId, ACQUIRE_TIMEOUT, LAUNCHER_TITLE,
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
        set_current(workspace("a", "A", false)).unwrap();
        assert!(set_current(workspace("b", "B", false)).is_err());
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
        assert!(acquire_within(&path, BRIEF).unwrap().is_some());
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
        // ... and holds nothing once it answered.
        assert!(acquire_within(&path, BRIEF).unwrap().is_some());
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
}
