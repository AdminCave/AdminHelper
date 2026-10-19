// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! The workspace of this process (R-0431): how the process was started (launcher, workspace,
//! purge), the id it was started with, and what follows from the workspace — its data dir,
//! keyring prefix, log and window names. A process serves one workspace for its whole life;
//! the launcher serves none.

#![cfg_attr(
    not(test),
    expect(
        dead_code,
        reason = "no callers yet, the start of the workspace process takes it up (R-0431 T10)"
    )
)]

use std::ffi::OsString;
use std::fmt;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use crate::error::AppError;

/// Every character an id may hold (`^[a-z0-9-]{1,32}$`), spelled out rather than as ranges, so
/// no reader has to wonder whether a locale widens them.
const ID_CHARS: &[u8] = b"abcdefghijklmnopqrstuvwxyz0123456789-";
const ID_MAX_LEN: usize = 32;

const USAGE: &str = "usage: adminhelper [--workspace <id> [--purge]]";

/// Title of the launcher window; a workspace window puts its name in front.
pub const LAUNCHER_TITLE: &str = "AdminHelper";

/// Log file name (without extension) of the launcher; a workspace process appends `-<id>`.
const LAUNCHER_LOG_NAME: &str = "adminhelper";

/// A workspace id that passed [`WorkspaceId::parse`], so it is safe as a path segment and inside
/// a keyring key.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceId(String);

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
    use std::path::Path;

    use super::{
        current, enter, set_current, AppError, Mode, Workspace, WorkspaceId, LAUNCHER_TITLE, USAGE,
    };

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
}
