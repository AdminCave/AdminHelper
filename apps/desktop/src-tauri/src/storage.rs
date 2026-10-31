// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::fs::{self, File};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard, PoisonError};
use std::time::{Duration, SystemTime};

use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use tauri::Manager;

use crate::enrollment;
use crate::error::AppError;
use crate::models::{
    Connection, RdpPerformanceProfile, RdpScalingMode, RdpWindowMode, Settings, SyncMode,
};
use crate::validation::{validate_https_url, validate_server_url_secure};
use crate::workspace::{self, Meta};

pub(crate) fn app_data_dir(app: &tauri::AppHandle) -> Result<PathBuf, AppError> {
    app.path()
        .app_data_dir()
        .map_err(|err: tauri::Error| AppError::Io(std::io::Error::other(err.to_string())))
}

/// The data dir of the workspace of this process in the app data dir `base`. The launcher has
/// none: an error, so nothing a workspace keeps lands in the app data dir.
fn workspace_dir(base: &Path) -> Result<PathBuf, AppError> {
    Ok(workspace::current()?.data_dir(base))
}

fn workspace_file(app: &tauri::AppHandle, file_name: &str) -> Result<PathBuf, AppError> {
    Ok(workspace_dir(&app_data_dir(app)?)?.join(file_name))
}

/// connections.json in the workspace dir — the transient cache of a server/sync workspace. It
/// is overwritten on every fetch/sync and is NOT the local store.
pub fn data_path(app: &tauri::AppHandle) -> Result<PathBuf, AppError> {
    workspace_file(app, "connections.json")
}

/// The connections file backing a given mode: local mode has its own store,
/// server and sync share the cache file.
pub(crate) fn connections_file_name(mode: &SyncMode) -> &'static str {
    match mode {
        SyncMode::Local => "connections.local.json",
        SyncMode::Server | SyncMode::Sync => "connections.json",
    }
}

/// The kind of the workspace of this process; the launcher has none.
fn current_mode(base: &Path) -> Result<SyncMode, AppError> {
    Ok(Meta::load(&workspace_dir(base)?)?.kind)
}

/// The connections file of the workspace of this process: the local store of a local
/// workspace, the server/sync cache otherwise.
fn connections_path(base: &Path) -> Result<PathBuf, AppError> {
    Ok(workspace_dir(base)?.join(connections_file_name(&current_mode(base)?)))
}

fn ensure_parent(path: &Path) -> Result<(), AppError> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    Ok(())
}

pub(crate) fn write_json_pretty<T: Serialize + ?Sized>(
    path: &Path,
    value: &T,
) -> Result<(), AppError> {
    ensure_parent(path)?;
    let serialized = serde_json::to_string_pretty(value)?;
    #[cfg(unix)]
    {
        // Atomic write: fill a temp file, harden it, then rename over the target. A crash mid-
        // write can never leave truncated JSON that then bricks load_settings — which nearly
        // every command calls — nor lose every local connection in connections.local.json (4.30);
        // and the target is never briefly world-readable. rename is atomic within the same
        // directory, and harden is a cheap chmod on Unix, so it runs on every write.
        let tmp = path.with_extension("json.tmp");
        fs::write(&tmp, &serialized)?;
        harden_permissions(&tmp);
        fs::rename(&tmp, path)?;
    }
    #[cfg(not(unix))]
    {
        // Windows keeps the in-place write: a temp+rename would drop the file's hardened ACLs
        // (std can't clone them across the rename) and re-hardening the temp would spawn an
        // icacls process on every sync (2.87). fs::write preserves the existing ACLs (it only
        // truncates content); harden only a freshly-created file. (Atomic write on Windows would
        // need the winapi to copy the ACLs onto the temp — a follow-up.)
        let existed = path.exists();
        fs::write(path, &serialized)?;
        if !existed {
            harden_permissions(path);
        }
    }
    Ok(())
}

/// Replaces the file at `path` at once on every platform: a reader sees the old file or the new
/// one, never part of either, and a crash leaves one of the two. The new one is on the disk
/// before it takes the name, so a power cut leaves no empty file either. For the files other
/// processes read while this one writes them (`prefs.json`, `workspaces.json`, a
/// `workspace.json` the launcher lists). Unlike [`write_json_pretty`] it hardens the temp on
/// Windows as well, an icacls run per call: for files written on a user's action, not on every
/// sync (2.87). The pid in the temp name keeps two processes off each other's temp.
pub(crate) fn write_json_atomic<T: Serialize + ?Sized>(
    path: &Path,
    value: &T,
) -> Result<(), AppError> {
    ensure_parent(path)?;
    remove_stale_temps(path);
    let serialized = serde_json::to_vec_pretty(value)?;
    let mut tmp = path.as_os_str().to_owned();
    tmp.push(format!(".{}.tmp", std::process::id()));
    let tmp = PathBuf::from(tmp);
    let replaced = fill_private(&tmp, &serialized).and_then(|()| {
        harden_permissions(&tmp);
        fs::rename(&tmp, path)
    });
    if replaced.is_err() {
        let _ = fs::remove_file(&tmp);
    }
    replaced.map_err(AppError::from)
}

/// How old the temp of an earlier [`write_json_atomic`] must be before the next write of the
/// same file removes it. A write takes milliseconds to seconds; a temp this old was left by a
/// process that ended between creating it and the rename.
const STALE_TEMP_AGE: Duration = Duration::from_secs(10 * 60);

/// Removes the temps earlier writes of `path` left (`<name>.<pid>.tmp` beside it) once they are
/// [`STALE_TEMP_AGE`] old. In doubt it keeps: a younger temp may be another process's write in
/// flight, and an unreadable or future modification time says nothing about its age. A failed
/// removal (on Windows a file another process holds open) is left for a later write.
fn remove_stale_temps(path: &Path) {
    let (Some(dir), Some(name)) = (
        path.parent(),
        path.file_name().and_then(|name| name.to_str()),
    ) else {
        return;
    };
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    let now = SystemTime::now();
    for entry in entries.flatten() {
        let file_name = entry.file_name();
        let is_temp = file_name
            .to_str()
            .and_then(|file_name| file_name.strip_prefix(name)?.strip_prefix('.'))
            .and_then(|rest| rest.strip_suffix(".tmp"))
            .is_some_and(|pid| !pid.is_empty() && pid.bytes().all(|byte| byte.is_ascii_digit()));
        if !is_temp {
            continue;
        }
        let stale = entry
            .metadata()
            .and_then(|meta| meta.modified())
            .ok()
            .and_then(|modified| now.duration_since(modified).ok())
            .is_some_and(|age| age >= STALE_TEMP_AGE);
        if stale {
            let _ = fs::remove_file(entry.path());
        }
    }
}

/// Writes `bytes` to a new or emptied file at `path`, created 0600 on Unix, and waits until they
/// are on the disk.
fn fill_private(path: &Path, bytes: &[u8]) -> io::Result<()> {
    let mut options = fs::OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)]
    std::os::unix::fs::OpenOptionsExt::mode(&mut options, 0o600);
    let mut file = options.open(path)?;
    file.write_all(bytes)?;
    file.sync_all()
}

fn read_json_or_default<T: DeserializeOwned + Default>(path: &Path) -> Result<T, AppError> {
    if !path.exists() {
        return Ok(T::default());
    }
    let data = fs::read_to_string(path)?;
    let value = serde_json::from_str(&data)?;
    Ok(value)
}

/// Writes the server/sync cache (connections.json). Used by the JWT fetch and
/// the sync abruf — never for the local-mode store.
pub fn write_connections(
    app: &tauri::AppHandle,
    connections: &[Connection],
) -> Result<(), AppError> {
    let path = data_path(app)?;
    write_json_pretty(&path, connections)
}

/// Reads the connections of the workspace of this process: the local store of a local
/// workspace, the server/sync cache otherwise.
pub fn load_connections(app: &tauri::AppHandle) -> Result<Vec<Connection>, AppError> {
    load_connections_in(&app_data_dir(app)?)
}

fn load_connections_in(base: &Path) -> Result<Vec<Connection>, AppError> {
    read_json_or_default(&connections_path(base)?)
}

/// Persists connections to the file of the workspace of this process. In a server workspace
/// the connections are owned by the server (written through the API), so this is hit only for
/// a local workspace (the local store) and a sync workspace (the cache).
pub fn save_connections(
    app: &tauri::AppHandle,
    connections: &[Connection],
) -> Result<(), AppError> {
    save_connections_in(&app_data_dir(app)?, connections)
}

fn save_connections_in(base: &Path, connections: &[Connection]) -> Result<(), AppError> {
    write_json_pretty(&connections_path(base)?, connections)
}

// Copies the legacy store to the local store ONLY when: mode is Local, the local target does not yet
// exist (never overwrite user data), and the legacy source exists. A sign flip in any of the three
// guards would silently overwrite the single local connection store or skip the migration (6.34).
pub(crate) fn migrate_between(
    legacy: &Path,
    local: &Path,
    mode: &SyncMode,
) -> Result<(), AppError> {
    if !matches!(mode, SyncMode::Local) {
        return Ok(());
    }
    if local.exists() {
        return Ok(());
    }
    if !legacy.exists() {
        return Ok(());
    }
    let data = fs::read_to_string(legacy)?;
    ensure_parent(local)?;
    fs::write(local, data)?;
    harden_permissions(local);
    Ok(())
}

/// The [`Settings`] the webview knows, put together from the [`Prefs`] of the device and the
/// workspace of this process (`mode` is its kind); the launcher gets the prefs and the defaults.
/// For Rust's own reads: the webview never sees what this returns, so the base of its next save
/// stays as it is.
pub fn load_settings(app: &tauri::AppHandle) -> Result<Settings, AppError> {
    load_settings_in(&app_data_dir(app)?, None)
}

/// [`load_settings`] for the webview: what it returns is the base against which
/// [`save_settings`] tells what the webview changed.
pub fn load_settings_for_webview(app: &tauri::AppHandle) -> Result<Settings, AppError> {
    load_settings_in(&app_data_dir(app)?, Some(&SEEN_PREFS))
}

/// `webview`: the base this read sets, if it is for the webview.
fn load_settings_in(base: &Path, webview: Option<&SeenPrefs>) -> Result<Settings, AppError> {
    let meta = workspace::current()
        .ok()
        .map(|ws| Meta::load(&ws.data_dir(base)))
        .transpose()?;
    // Held across the read, so no save of this process comes between the read and its base.
    let mut seen = webview.map(SeenPrefs::lock);
    let prefs: Prefs = {
        let _lock = PrefsLock::shared(base)?;
        read_json_or_default(&base.join(PREFS_FILE))?
    };
    if let Some(seen) = seen.as_mut() {
        **seen = Some(prefs.clone());
    }
    Ok(settings_of(prefs, meta.as_ref()))
}

/// Saves what the webview changed: the fields of the workspace to its `workspace.json`, the
/// prefs to `prefs.json`. Never the kind of the workspace, nor a URL other than the one it has.
/// The launcher has no workspace and saves the prefs alone.
pub fn save_settings(app: &tauri::AppHandle, settings: &Settings) -> Result<(), AppError> {
    save_settings_in(&app_data_dir(app)?, &SEEN_PREFS, settings)
}

fn save_settings_in(base: &Path, seen: &SeenPrefs, settings: &Settings) -> Result<(), AppError> {
    if let Ok(ws) = workspace::current() {
        let _meta = meta_lock();
        let dir = ws.data_dir(base);
        let meta = Meta::load(&dir)?;
        let updated = meta_with(&meta, settings, || {
            enrollment::holds_identity(&ws.keyring_prefix())
        })?;
        if updated != meta {
            updated.store(&dir)?;
        }
    }
    let mut seen = seen.lock();
    let mine = Prefs::from(settings);
    {
        let _lock = PrefsLock::exclusive(base)?;
        let path = base.join(PREFS_FILE);
        let on_disk: Prefs = read_json_or_default(&path)?;
        let merged = on_disk.clone().merged(seen.as_ref(), &mine);
        if merged != on_disk {
            write_json_atomic(&path, &merged)?;
        }
    }
    *seen = Some(mine);
    Ok(())
}

/// [`save_settings_in`] in the app data dir `base`, for the tests of other modules.
#[cfg(test)]
pub(crate) fn save_settings_at(base: &Path, settings: &Settings) -> Result<(), AppError> {
    save_settings_in(base, &SeenPrefs::new(), settings)
}

/// Held while this process reads and rewrites the `workspace.json` of its workspace
/// ([`save_settings`], [`keep_enrolled_url`]): a save then either gives the workspace its first
/// URL before a registration keeps one, which the registration sees, or finds the URL kept.
static META_LOCK: Mutex<()> = Mutex::new(());

fn meta_lock() -> MutexGuard<'static, ()> {
    // Nothing lives under the guard; the file it guards is written whole (`write_json_atomic`).
    META_LOCK.lock().unwrap_or_else(PoisonError::into_inner)
}

/// Why [`keep_enrolled_url`] fails for a workspace that took another server meanwhile.
const URL_TAKEN: &str =
    "this workspace took the URL of another server while this device registered";

/// Makes `url`, where a registration of this device just succeeded, the URL of the workspace of
/// this process in the app data dir `base`, if it has none yet: the identity is that server's,
/// and the purge revokes it there. The sign-in that follows finds it kept ([`meta_with`] takes
/// no first URL beside an identity). The registration checked the URL as every call to a server
/// does (`http_client`). A workspace with a URL of that server keeps it: the registration went
/// there ([`workspace::sign_in_url`]). One that took another server meanwhile (a save of the
/// settings while the registration waited for the server) is an error: the identity would be
/// revoked at the wrong server, and the caller resets it.
pub(crate) fn keep_enrolled_url(base: &Path, url: &str) -> Result<(), AppError> {
    let _meta = meta_lock();
    let dir = workspace_dir(base)?;
    let meta = Meta::load(&dir)?;
    match &meta.url {
        None => Meta {
            url: Some(url.to_string()),
            ..meta
        }
        .store(&dir),
        Some(kept) if workspace::same_server(kept, url) => Ok(()),
        Some(_) => Err(AppError::Validation(URL_TAKEN.to_string())),
    }
}

/// The [`Settings`] of `prefs` and, in a workspace, of its `meta`; the launcher has the
/// defaults for the fields of a workspace.
fn settings_of(prefs: Prefs, meta: Option<&Meta>) -> Settings {
    let defaults = Settings::default();
    let url_of = |kind: SyncMode| {
        meta.filter(|meta| meta.kind == kind)
            .and_then(|meta| meta.url.clone())
    };
    // Each field by name: a field added to either half does not compile until it is placed.
    let Prefs {
        language,
        store_passwords,
        rdp_scaling_mode,
        rdp_window_mode,
        rdp_custom_size,
        rdp_performance_profile,
        os_notifications,
    } = prefs;
    Settings {
        mode: meta.map_or(defaults.mode, |meta| meta.kind.clone()),
        sync_url: url_of(SyncMode::Sync),
        interval_minutes: meta.map_or(defaults.interval_minutes, |meta| meta.interval_minutes),
        language,
        store_passwords,
        rdp_scaling_mode,
        rdp_window_mode,
        rdp_custom_size,
        rdp_performance_profile,
        allow_self_signed_certs: meta.map_or(defaults.allow_self_signed_certs, |meta| {
            meta.allow_self_signed_certs
        }),
        server_url: url_of(SyncMode::Server),
        last_username: meta.and_then(|meta| meta.last_username.clone()),
        os_notifications,
    }
}

/// Why [`save_settings`] refuses a URL: the window of a workspace never changes it.
const URL_KEPT: &str =
    "this workspace keeps its URL; change it in the workspace list while the workspace is closed";

/// Why [`save_settings`] refuses the first URL of a server workspace that holds a device
/// identity.
const IDENTITY_WITHOUT_URL: &str = "this workspace holds a device identity but no URL of its \
     server; reset the device identity before it takes one";

/// `meta` with the fields of the workspace `settings` holds. The kind stays (`mode` is never
/// written), and so does a URL the workspace has: another one would be another installation
/// under the sign-in and device identity of this one. A server URL is the same one when it names
/// the same server ([`workspace::same_server`]), as the sign-in takes it, so the save after a
/// sign-in under another spelling goes through; a sync source is the same one only as it is
/// spelled, another path being another source. Until it has one, it takes the first, checked as
/// the workspace list checks it; the URL field of the other kind has no place in it.
///
/// A server workspace whose keyring holds a device identity (`holds_identity`, asked only then)
/// takes no first URL: the purge revokes the identity at the URL the workspace has, and only
/// the server that issued it may be that one. A registration gives a workspace without a URL
/// the one it went to at once ([`keep_enrolled_url`]).
fn meta_with(
    meta: &Meta,
    settings: &Settings,
    holds_identity: impl FnOnce() -> Result<bool, AppError>,
) -> Result<Meta, AppError> {
    let sent = match meta.kind {
        SyncMode::Server => settings.server_url.as_deref(),
        SyncMode::Sync => settings.sync_url.as_deref(),
        SyncMode::Local => None,
    }
    .map(str::trim)
    .filter(|url| !url.is_empty());
    let same = |kept: &str, url: &str| match meta.kind {
        SyncMode::Server => workspace::same_server(kept, url),
        SyncMode::Sync | SyncMode::Local => kept.trim() == url,
    };
    let url = match (&meta.url, sent) {
        (kept, None) => kept.clone(),
        (None, Some(first)) => {
            match meta.kind {
                SyncMode::Server => validate_server_url_secure(first)?,
                SyncMode::Sync | SyncMode::Local => validate_https_url(first)?,
            }
            if meta.kind == SyncMode::Server && holds_identity()? {
                return Err(AppError::Validation(IDENTITY_WITHOUT_URL.to_string()));
            }
            Some(first.to_string())
        }
        (Some(kept), Some(url)) if same(kept, url) => Some(kept.clone()),
        (Some(_), Some(_)) => return Err(AppError::Validation(URL_KEPT.to_string())),
    };
    Ok(Meta {
        url,
        interval_minutes: settings.interval_minutes,
        allow_self_signed_certs: settings.allow_self_signed_certs,
        last_username: settings.last_username.clone(),
        ..meta.clone()
    })
}

/// The prefs this process last handed the webview ([`load_settings_for_webview`]) or took from
/// it: the base against which [`save_settings`] tells which fields the webview changed. Another
/// process of the device may have saved the others since; they stay as it left them. Without a
/// base a save takes every pref.
struct SeenPrefs(Mutex<Option<Prefs>>);

impl SeenPrefs {
    const fn new() -> Self {
        Self(Mutex::new(None))
    }

    fn lock(&self) -> MutexGuard<'_, Option<Prefs>> {
        // A panic under the guard leaves a base that is at worst stale: the next save then
        // writes a field or two the webview did not change, as every save did before R-0431.
        self.0.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

/// The [`SeenPrefs`] of this process.
static SEEN_PREFS: SeenPrefs = SeenPrefs::new();

/// In the app data dir: the lock around every read and write of [`PREFS_FILE`], which every
/// process of the device writes. A file of its own: on Windows a lock can bar every other
/// handle from the bytes it covers.
const PREFS_LOCK: &str = "prefs.lock";

/// Holds [`PREFS_LOCK`] until it drops: shared to read the prefs, exclusive to replace them.
struct PrefsLock(File);

impl PrefsLock {
    fn shared(base: &Path) -> Result<Self, AppError> {
        let file = Self::open(base)?;
        file.lock_shared()?;
        Ok(Self(file))
    }

    fn exclusive(base: &Path) -> Result<Self, AppError> {
        let file = Self::open(base)?;
        file.lock()?;
        Ok(Self(file))
    }

    /// Opened to read and write: `LockFileEx` wants a handle with either.
    fn open(base: &Path) -> io::Result<File> {
        fs::create_dir_all(base)?;
        let mut options = fs::OpenOptions::new();
        options.read(true).write(true).create(true).truncate(false);
        #[cfg(unix)]
        std::os::unix::fs::OpenOptionsExt::mode(&mut options, 0o600);
        options.open(base.join(PREFS_LOCK))
    }
}

impl Drop for PrefsLock {
    fn drop(&mut self) {
        // Windows frees the lock of a closed handle when it gets round to it; the next reader
        // need not wait for that.
        let _ = self.0.unlock();
    }
}

/// In the app data dir: the [`Prefs`] of the device (R-0431).
pub(crate) const PREFS_FILE: &str = "prefs.json";

/// The part of [`Settings`] every workspace on the device shares; the rest belongs to a
/// workspace (`workspace::Meta`).
///
/// `pub(crate)`: a `pub` serde type would have to cross the bridge (`types.parity.test.ts`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct Prefs {
    pub language: Option<String>,
    pub store_passwords: bool,
    pub rdp_scaling_mode: RdpScalingMode,
    pub rdp_window_mode: RdpWindowMode,
    pub rdp_custom_size: Option<String>,
    pub rdp_performance_profile: RdpPerformanceProfile,
    pub os_notifications: bool,
}

impl From<&Settings> for Prefs {
    fn from(settings: &Settings) -> Self {
        Self {
            language: settings.language.clone(),
            store_passwords: settings.store_passwords,
            rdp_scaling_mode: settings.rdp_scaling_mode,
            rdp_window_mode: settings.rdp_window_mode,
            rdp_custom_size: settings.rdp_custom_size.clone(),
            rdp_performance_profile: settings.rdp_performance_profile,
            os_notifications: settings.os_notifications,
        }
    }
}

/// What a device without `prefs.json` has.
impl Default for Prefs {
    fn default() -> Self {
        Self::from(&Settings::default())
    }
}

impl Prefs {
    /// `self`, the prefs on disk, with each field that `mine` changed against `seen` taken from
    /// `mine`; with nothing seen, all of `mine`. A field the webview left alone keeps what
    /// another process saved meanwhile.
    fn merged(mut self, seen: Option<&Prefs>, mine: &Prefs) -> Self {
        let Some(seen) = seen else {
            return mine.clone();
        };
        // Each field by name: a field added to Prefs does not compile until it is merged here.
        let Prefs {
            language,
            store_passwords,
            rdp_scaling_mode,
            rdp_window_mode,
            rdp_custom_size,
            rdp_performance_profile,
            os_notifications,
        } = mine;
        take_changed(&mut self.language, &seen.language, language);
        take_changed(
            &mut self.store_passwords,
            &seen.store_passwords,
            store_passwords,
        );
        take_changed(
            &mut self.rdp_scaling_mode,
            &seen.rdp_scaling_mode,
            rdp_scaling_mode,
        );
        take_changed(
            &mut self.rdp_window_mode,
            &seen.rdp_window_mode,
            rdp_window_mode,
        );
        take_changed(
            &mut self.rdp_custom_size,
            &seen.rdp_custom_size,
            rdp_custom_size,
        );
        take_changed(
            &mut self.rdp_performance_profile,
            &seen.rdp_performance_profile,
            rdp_performance_profile,
        );
        take_changed(
            &mut self.os_notifications,
            &seen.os_notifications,
            os_notifications,
        );
        self
    }
}

/// `mine` into `on_disk`, if it is not what was `seen`.
fn take_changed<T: PartialEq + Clone>(on_disk: &mut T, seen: &T, mine: &T) {
    if mine != seen {
        on_disk.clone_from(mine);
    }
}

/// Writes the exported browser PKCS12 (.p12) to the user-chosen destination
/// (from the frontend's save dialog) and returns the absolute path. The blob
/// holds a private key, so it is hardened to 0600 (Unix) even though it is also
/// password-encrypted.
pub fn write_browser_p12(dest_path: &str, der: &[u8]) -> Result<String, AppError> {
    let path = PathBuf::from(dest_path);
    ensure_parent(&path)?;
    fs::write(&path, der)?;
    harden_permissions(&path);
    Ok(path.to_string_lossy().to_string())
}

#[cfg(unix)]
pub fn harden_permissions(path: &Path) {
    use std::os::unix::fs::PermissionsExt;
    if let Ok(metadata) = fs::metadata(path) {
        let mut permissions = metadata.permissions();
        permissions.set_mode(0o600);
        let _ = fs::set_permissions(path, permissions);
    }
}

#[cfg(target_os = "windows")]
pub fn harden_permissions(path: &Path) {
    use std::process::Command;
    if let Ok(user) = std::env::var("USERNAME") {
        let path_str = path.to_string_lossy();
        // A silent failure here would leave the .p12 with inherited ACLs (broader
        // than the owner) — log it so it does not stay invisible. The blob is also
        // password-encrypted, so this stays best-effort, not fatal.
        match Command::new("icacls")
            .args([
                path_str.as_ref(),
                "/inheritance:r",
                "/grant:r",
                &format!("{user}:F"),
            ])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status()
        {
            Ok(status) if !status.success() => {
                log::warn!("icacls konnte {path_str} nicht haerten: Status {status}");
            }
            Err(e) => {
                log::warn!("icacls fuer {path_str} nicht ausfuehrbar: {e}");
            }
            Ok(_) => {}
        }
    }
}

#[cfg(not(any(unix, target_os = "windows")))]
pub fn harden_permissions(_path: &Path) {}

#[cfg(test)]
mod tests {
    use super::{connections_file_name, read_json_or_default, write_json_pretty};
    use crate::models::SyncMode;

    #[test]
    fn write_json_pretty_round_trips_without_orphan_temp() {
        // 4.30: the write must round-trip, leave no .tmp orphan behind, and (Unix) land a 0600
        // target — the atomic temp+rename path.
        // Per-process dir so two concurrent `cargo test` runs don't share it and the teardown
        // can't delete the other run's data.
        let dir =
            std::env::temp_dir().join(format!("ah-write-json-pretty-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("settings.json");
        write_json_pretty(&path, &serde_json::json!({"a": 1})).unwrap();

        assert!(path.exists());
        assert!(
            !path.with_extension("json.tmp").exists(),
            "no orphan temp file"
        );
        let v: serde_json::Value = read_json_or_default(&path).unwrap();
        assert_eq!(v["a"], 1);
        // Overwrite an existing file — still round-trips, still no orphan.
        write_json_pretty(&path, &serde_json::json!({"a": 2})).unwrap();
        let v: serde_json::Value = read_json_or_default(&path).unwrap();
        assert_eq!(v["a"], 2);
        assert!(!path.with_extension("json.tmp").exists());
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = std::fs::metadata(&path).unwrap().permissions().mode() & 0o777;
            assert_eq!(mode, 0o600, "target hardened to 0600");
        }
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn local_mode_has_its_own_connections_file() {
        let local = connections_file_name(&SyncMode::Local);
        // The split's invariant: local mode must NOT share a file with the
        // server/sync cache, or a fetch/sync would overwrite the local store.
        assert_eq!(local, "connections.local.json");
        assert_eq!(connections_file_name(&SyncMode::Server), "connections.json");
        assert_eq!(connections_file_name(&SyncMode::Sync), "connections.json");
        assert_ne!(local, connections_file_name(&SyncMode::Server));
        assert_ne!(local, connections_file_name(&SyncMode::Sync));
    }
}

#[cfg(test)]
mod migration_tests {
    use super::{migrate_between, read_json_or_default};
    use crate::models::SyncMode;

    fn scratch(tag: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!("ah-{tag}-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn migration_never_overwrites_an_existing_local_store() {
        let dir = scratch("mig-overwrite");
        let (legacy, local) = (
            dir.join("connections.json"),
            dir.join("connections.local.json"),
        );
        std::fs::write(&legacy, "[]").unwrap();
        std::fs::write(&local, r#"[{"id":"keep"}]"#).unwrap();

        migrate_between(&legacy, &local, &SyncMode::Local).unwrap();

        // The existing local store must be untouched — the guard exists to prevent data loss.
        assert_eq!(
            std::fs::read_to_string(&local).unwrap(),
            r#"[{"id":"keep"}]"#
        );
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn migration_copies_legacy_when_local_absent() {
        let dir = scratch("mig-copy");
        let (legacy, local) = (
            dir.join("connections.json"),
            dir.join("connections.local.json"),
        );
        std::fs::write(&legacy, r#"[{"id":"old"}]"#).unwrap();

        migrate_between(&legacy, &local, &SyncMode::Local).unwrap();

        assert_eq!(
            std::fs::read_to_string(&local).unwrap(),
            r#"[{"id":"old"}]"#
        );
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn migration_skipped_when_not_local_mode() {
        let dir = scratch("mig-mode");
        let (legacy, local) = (
            dir.join("connections.json"),
            dir.join("connections.local.json"),
        );
        std::fs::write(&legacy, "[]").unwrap();

        migrate_between(&legacy, &local, &SyncMode::Server).unwrap();

        assert!(!local.exists(), "non-Local mode must not migrate");
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn migration_skipped_without_legacy_source() {
        let dir = scratch("mig-nolegacy");
        let (legacy, local) = (
            dir.join("connections.json"),
            dir.join("connections.local.json"),
        );

        migrate_between(&legacy, &local, &SyncMode::Local).unwrap();

        assert!(!local.exists(), "no legacy source -> nothing to migrate");
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn read_json_or_default_handles_missing_valid_and_corrupt() {
        let dir = scratch("readjson");

        // Missing -> default.
        let missing: Vec<i32> = read_json_or_default(&dir.join("missing.json")).unwrap();
        assert_eq!(missing, Vec::<i32>::new());

        // Valid -> parsed.
        let valid_path = dir.join("valid.json");
        std::fs::write(&valid_path, "[1,2,3]").unwrap();
        let valid: Vec<i32> = read_json_or_default(&valid_path).unwrap();
        assert_eq!(valid, vec![1, 2, 3]);

        // Corrupt -> Err, so the caller surfaces the error instead of a silent default.
        let corrupt_path = dir.join("corrupt.json");
        std::fs::write(&corrupt_path, "{not json").unwrap();
        let corrupt: Result<Vec<i32>, _> = read_json_or_default(&corrupt_path);
        assert!(corrupt.is_err(), "corrupt JSON must be an error");

        std::fs::remove_dir_all(&dir).ok();
    }
}

#[cfg(test)]
mod settings_tests {
    use std::fs::{self, File};
    use std::io::{Read, Write};
    use std::path::{Path, PathBuf};
    use std::thread;
    use std::time::{Duration, SystemTime};

    use serde_json::{json, Value};

    use super::{
        keep_enrolled_url, load_connections_in, load_settings_in, save_connections_in,
        save_settings_in, write_json_atomic, write_json_pretty, Prefs, PrefsLock, SeenPrefs,
        IDENTITY_WITHOUT_URL, PREFS_FILE, SEEN_PREFS, URL_KEPT, URL_TAKEN,
    };
    use crate::error::AppError;
    use crate::keyring_store;
    use crate::models::{Connection, RdpScalingMode, Settings, SyncMode};
    use crate::workspace::{self, EnteredWorkspace, Meta, Workspace, WorkspaceId, PALETTE};

    /// A directory of its own for one test case under the system temp dir, gone with the guard.
    struct Scratch(PathBuf);

    impl Scratch {
        fn new(case: &str) -> Self {
            let dir =
                std::env::temp_dir().join(format!("ah-storage-{case}-{}", std::process::id()));
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

    const SERVER_URL: &str = "https://ah.example.com";
    const SYNC_URL: &str = "https://sync.example.com/connections.json";
    /// What the one workspace before R-0431 left in the app data dir.
    const LEGACY_CONNECTIONS: &str = r#"[{"id":"old","name":"old","kind":"ssh"}]"#;

    fn workspace(id: &str) -> Workspace {
        Workspace {
            id: WorkspaceId::parse(id).unwrap(),
            name: id.to_string(),
            legacy_keys: false,
        }
    }

    fn meta(kind: SyncMode, url: Option<&str>) -> Meta {
        Meta {
            kind,
            name: "Kunde A".to_string(),
            color: PALETTE[0].to_string(),
            url: url.map(String::from),
            interval_minutes: 5,
            allow_self_signed_certs: false,
            last_username: None,
            legacy_keys: false,
        }
    }

    /// Builds the workspace `id` in `base`, as the launcher would.
    fn make(base: &Path, id: &str, meta: &Meta) {
        meta.store(&workspace(id).data_dir(base)).unwrap();
    }

    /// While the guard lives, this thread is the process of the workspace `id`.
    fn enter(id: &str) -> EnteredWorkspace {
        workspace::enter(workspace(id))
    }

    fn meta_in(base: &Path, id: &str) -> Meta {
        Meta::load(&workspace(id).data_dir(base)).unwrap()
    }

    fn json_of(path: &Path) -> Value {
        serde_json::from_slice(&fs::read(path).unwrap()).unwrap()
    }

    /// Settings as the webview gets them; `Settings` has no `PartialEq`.
    fn wire(settings: &Settings) -> Value {
        serde_json::to_value(settings).unwrap()
    }

    fn connections(ids: &[&str]) -> Vec<Connection> {
        ids.iter()
            .map(|id| serde_json::from_value(json!({"id": id, "name": id, "kind": "ssh"})).unwrap())
            .collect()
    }

    fn ids(connections: &[Connection]) -> Vec<String> {
        connections.iter().map(|c| c.id.clone()).collect()
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

    #[test]
    fn settings_round_trip_through_the_prefs_and_the_workspace() {
        let scratch = Scratch::new("settings-round-trip");
        let base = &scratch.0;
        make(base, "a", &meta(SyncMode::Server, None));
        let _a = enter("a");
        let process = SeenPrefs::new();

        let mut settings = load_settings_in(base, Some(&process)).unwrap();
        assert_eq!(settings.mode, SyncMode::Server, "the kind is the mode");
        settings.language = Some("en".to_string());
        settings.store_passwords = true;
        settings.rdp_scaling_mode = RdpScalingMode::Hdpi;
        settings.rdp_custom_size = Some("1600x900".to_string());
        settings.os_notifications = true;
        settings.server_url = Some(SERVER_URL.to_string());
        settings.interval_minutes = 9;
        settings.allow_self_signed_certs = true;
        settings.last_username = Some("admin".to_string());
        save_settings_in(base, &process, &settings).unwrap();

        // The next process of the workspace reads what this one saved.
        assert_eq!(
            wire(&load_settings_in(base, None).unwrap()),
            wire(&settings)
        );
        // The device's half in prefs.json, the workspace's in its workspace.json.
        assert_eq!(
            json_of(&base.join(PREFS_FILE)),
            json!({
                "language": "en",
                "storePasswords": true,
                "rdpScalingMode": "hdpi",
                "rdpWindowMode": "fit",
                "rdpCustomSize": "1600x900",
                "rdpPerformanceProfile": "auto",
                "osNotifications": true,
            })
        );
        assert_eq!(
            meta_in(base, "a"),
            Meta {
                url: Some(SERVER_URL.to_string()),
                interval_minutes: 9,
                allow_self_signed_certs: true,
                last_username: Some("admin".to_string()),
                ..meta(SyncMode::Server, None)
            }
        );
        // The settings file of the one workspace before R-0431 is neither read nor written.
        assert!(!base.join("settings.json").exists());
    }

    #[test]
    fn two_processes_keep_each_others_change_of_the_prefs() {
        let scratch = Scratch::new("settings-two-processes");
        let base = &scratch.0;
        make(base, "a", &meta(SyncMode::Local, None));
        make(base, "b", &meta(SyncMode::Server, Some(SERVER_URL)));
        let (first, second) = (SeenPrefs::new(), SeenPrefs::new());
        // Both windows open on the prefs as they were.
        let mut in_a = {
            let _a = enter("a");
            load_settings_in(base, Some(&first)).unwrap()
        };
        let mut in_b = {
            let _b = enter("b");
            load_settings_in(base, Some(&second)).unwrap()
        };

        in_a.language = Some("en".to_string());
        {
            let _a = enter("a");
            save_settings_in(base, &first, &in_a).unwrap();
        }
        // The second window still shows the old language and changes another field.
        in_b.store_passwords = true;
        {
            let _b = enter("b");
            save_settings_in(base, &second, &in_b).unwrap();
        }

        for id in ["a", "b"] {
            let _ws = enter(id);
            let settings = load_settings_in(base, None).unwrap();
            assert_eq!(
                settings.language.as_deref(),
                Some("en"),
                "{id}: first change lost"
            );
            assert!(settings.store_passwords, "{id}: second change lost");
        }
        // Saved again from its old view, the second window still leaves the language be.
        {
            let _b = enter("b");
            save_settings_in(base, &second, &in_b).unwrap();
        }
        assert_eq!(json_of(&base.join(PREFS_FILE))["language"], "en");
    }

    #[test]
    fn a_read_for_rust_leaves_the_base_of_the_webview_alone() {
        let scratch = Scratch::new("settings-rust-read");
        let base = &scratch.0;
        make(base, "a", &meta(SyncMode::Local, None));
        make(base, "b", &meta(SyncMode::Local, None));
        // The only test on the base of this process (`SEEN_PREFS`, which `load_settings` and
        // the commands share); every other test takes one of its own.
        let mut in_a = {
            let _a = enter("a");
            load_settings_in(base, Some(&SEEN_PREFS)).unwrap()
        };
        // Another window changes the language.
        {
            let _b = enter("b");
            let other = SeenPrefs::new();
            let mut in_b = load_settings_in(base, Some(&other)).unwrap();
            in_b.language = Some("en".to_string());
            save_settings_in(base, &other, &in_b).unwrap();
        }
        {
            let _a = enter("a");
            // Rust reads the settings for itself: a sync tick, a connection being opened ...
            let read = load_settings_in(base, None).unwrap();
            assert_eq!(read.language.as_deref(), Some("en"));
            // ... while the webview still shows the old language and changes another field.
            in_a.store_passwords = true;
            save_settings_in(base, &SEEN_PREFS, &in_a).unwrap();
        }

        let saved = load_settings_in(base, None).unwrap();
        assert_eq!(
            saved.language.as_deref(),
            Some("en"),
            "the other window's change is gone"
        );
        assert!(saved.store_passwords);
    }

    #[test]
    fn a_save_without_a_base_takes_every_pref() {
        let scratch = Scratch::new("settings-no-base");
        let base = &scratch.0;
        make(base, "a", &meta(SyncMode::Local, None));
        make(base, "b", &meta(SyncMode::Local, None));
        // Another window changes the language.
        {
            let _b = enter("b");
            let other = SeenPrefs::new();
            let mut in_b = load_settings_in(base, Some(&other)).unwrap();
            in_b.language = Some("en".to_string());
            save_settings_in(base, &other, &in_b).unwrap();
        }

        // A process whose webview never loaded through the base (until R-0431 T14 every one)
        // saves all of the prefs it sends, as every save did before the split.
        let _a = enter("a");
        let mine = Settings {
            language: None,
            store_passwords: true,
            ..load_settings_in(base, None).unwrap()
        };
        save_settings_in(base, &SeenPrefs::new(), &mine).unwrap();

        assert_eq!(
            json_of(&base.join(PREFS_FILE)),
            serde_json::to_value(Prefs::from(&mine)).unwrap()
        );
    }

    #[test]
    fn saving_never_changes_the_kind_of_a_workspace() {
        let scratch = Scratch::new("settings-kind");
        let base = &scratch.0;
        make(base, "a", &meta(SyncMode::Server, Some(SERVER_URL)));
        let _a = enter("a");
        let process = SeenPrefs::new();

        let mut settings = load_settings_in(base, Some(&process)).unwrap();
        settings.mode = SyncMode::Local;
        save_settings_in(base, &process, &settings).unwrap();

        assert_eq!(meta_in(base, "a").kind, SyncMode::Server);
        assert_eq!(load_settings_in(base, None).unwrap().mode, SyncMode::Server);
    }

    #[test]
    fn a_workspace_takes_its_first_url_and_refuses_another() {
        let scratch = Scratch::new("settings-url");
        let base = &scratch.0;
        make(base, "a", &meta(SyncMode::Server, None));
        let _a = enter("a");
        let process = SeenPrefs::new();
        let mut settings = load_settings_in(base, Some(&process)).unwrap();
        assert_eq!(settings.server_url, None);

        // The first login brings the URL.
        settings.server_url = Some(SERVER_URL.to_string());
        save_settings_in(base, &process, &settings).unwrap();
        assert_eq!(meta_in(base, "a").url.as_deref(), Some(SERVER_URL));

        // The same URL with blanks around it, an empty field or none keep it.
        for same in [Some(format!(" {SERVER_URL} ")), Some(String::new()), None] {
            settings.server_url = same.clone();
            save_settings_in(base, &process, &settings).unwrap();
            assert_eq!(
                meta_in(base, "a").url.as_deref(),
                Some(SERVER_URL),
                "{same:?}"
            );
        }

        // Another one is another installation: refused, and nothing of that save lands.
        let prefs_before = fs::read(base.join(PREFS_FILE)).ok();
        let other = Settings {
            server_url: Some("https://other.example.com".to_string()),
            interval_minutes: 30,
            language: Some("en".to_string()),
            ..settings.clone()
        };
        assert!(matches!(
            save_settings_in(base, &process, &other),
            Err(AppError::Validation(_))
        ));
        assert_eq!(
            meta_in(base, "a"),
            Meta {
                url: Some(SERVER_URL.to_string()),
                ..meta(SyncMode::Server, None)
            }
        );
        assert_eq!(fs::read(base.join(PREFS_FILE)).ok(), prefs_before);
        assert_eq!(
            load_settings_in(base, None).unwrap().server_url.as_deref(),
            Some(SERVER_URL)
        );
    }

    #[test]
    fn a_sync_workspace_keeps_its_source_in_the_url_field() {
        let scratch = Scratch::new("settings-sync");
        let base = &scratch.0;
        make(base, "s", &meta(SyncMode::Sync, Some(SYNC_URL)));
        let _s = enter("s");
        let process = SeenPrefs::new();

        let mut settings = load_settings_in(base, Some(&process)).unwrap();
        assert_eq!(settings.mode, SyncMode::Sync);
        assert_eq!(settings.sync_url.as_deref(), Some(SYNC_URL));
        assert_eq!(settings.server_url, None);

        // A server URL has no place in a sync workspace.
        settings.server_url = Some(SERVER_URL.to_string());
        save_settings_in(base, &process, &settings).unwrap();
        assert_eq!(meta_in(base, "s").url.as_deref(), Some(SYNC_URL));
        assert_eq!(load_settings_in(base, None).unwrap().server_url, None);

        // Another source is another workspace.
        settings.sync_url = Some("https://elsewhere.example.com/connections.json".to_string());
        assert!(matches!(
            save_settings_in(base, &process, &settings),
            Err(AppError::Validation(_))
        ));
        assert_eq!(meta_in(base, "s").url.as_deref(), Some(SYNC_URL));
    }

    #[test]
    fn login_binding_the_save_after_a_sign_in_keeps_the_server_url_however_it_is_spelled() {
        let scratch = Scratch::new("settings-spelling");
        let base = &scratch.0;
        let kept = "https://ops:geheim@ah.example.com/base";
        make(base, "a", &meta(SyncMode::Server, Some(kept)));
        make(base, "s", &meta(SyncMode::Sync, Some(SYNC_URL)));
        let process = SeenPrefs::new();
        {
            let _a = enter("a");
            let mut settings = load_settings_in(base, Some(&process)).unwrap();
            // What the session saves after a sign-in at the same server, spelled otherwise.
            settings.server_url = Some(" https://AH.example.com:443/ ".to_string());
            settings.last_username = Some("admin".to_string());
            save_settings_in(base, &process, &settings).unwrap();
            assert_eq!(
                meta_in(base, "a"),
                Meta {
                    url: Some(kept.to_string()),
                    last_username: Some("admin".to_string()),
                    ..meta(SyncMode::Server, None)
                }
            );

            // Another server stays refused, and the error names no part of the URL kept.
            for other in [
                "https://ah.example.com:8443",
                "http://ah.example.com",
                "https://other.example.com/base",
            ] {
                settings.server_url = Some(other.to_string());
                settings.last_username = Some("ops".to_string());
                let refused = save_settings_in(base, &process, &settings).unwrap_err();
                assert!(
                    matches!(&refused, AppError::Validation(msg) if msg.as_str() == URL_KEPT),
                    "{other}: {refused:?}"
                );
                assert_eq!(meta_in(base, "a").url.as_deref(), Some(kept), "{other}");
                assert_eq!(
                    meta_in(base, "a").last_username.as_deref(),
                    Some("admin"),
                    "{other}"
                );
            }
        }
        // A sync source is the same one only as it is spelled: another path is another source.
        let _s = enter("s");
        let mut settings = load_settings_in(base, Some(&process)).unwrap();
        settings.sync_url = Some("https://sync.example.com/other.json".to_string());
        assert!(matches!(
            save_settings_in(base, &process, &settings),
            Err(AppError::Validation(_))
        ));
        assert_eq!(meta_in(base, "s").url.as_deref(), Some(SYNC_URL));
    }

    #[test]
    fn login_binding_a_workspace_takes_only_a_valid_first_url() {
        let scratch = Scratch::new("settings-first-url");
        let base = &scratch.0;
        make(base, "a", &meta(SyncMode::Server, None));
        make(base, "s", &meta(SyncMode::Sync, None));
        let process = SeenPrefs::new();
        {
            let _a = enter("a");
            let mut settings = load_settings_in(base, Some(&process)).unwrap();
            for bad in [
                "http://ah.example.com",
                "ftp://ah.example.com",
                "ah.example.com",
            ] {
                settings.server_url = Some(bad.to_string());
                assert!(
                    matches!(
                        save_settings_in(base, &process, &settings),
                        Err(AppError::Validation(_))
                    ),
                    "{bad}"
                );
                assert_eq!(meta_in(base, "a").url, None, "{bad}");
            }
            // As the workspace list and the sign-in take it: http only on loopback.
            settings.server_url = Some("http://127.0.0.1:8000".to_string());
            save_settings_in(base, &process, &settings).unwrap();
            assert_eq!(
                meta_in(base, "a").url.as_deref(),
                Some("http://127.0.0.1:8000")
            );
        }
        let _s = enter("s");
        let mut settings = load_settings_in(base, Some(&process)).unwrap();
        for bad in [
            "http://sync.example.com/connections.json",
            "http://127.0.0.1/connections.json",
        ] {
            settings.sync_url = Some(bad.to_string());
            assert!(
                save_settings_in(base, &process, &settings).is_err(),
                "{bad}"
            );
            assert_eq!(meta_in(base, "s").url, None, "{bad}");
        }
        settings.sync_url = Some(SYNC_URL.to_string());
        save_settings_in(base, &process, &settings).unwrap();
        assert_eq!(meta_in(base, "s").url.as_deref(), Some(SYNC_URL));
    }

    /// A device identity behind the keyring prefix of the workspace `id`, as far as
    /// `enrollment::holds_identity` looks: one entry of it is one.
    fn hold_identity(id: &str) {
        let key = format!("{}enroll|cert", workspace(id).keyring_prefix());
        keyring_store::set(&key, "pem").unwrap();
    }

    #[test]
    fn login_binding_a_server_workspace_with_a_device_identity_takes_no_first_url() {
        let _keyring = keyring_store::memory();
        let scratch = Scratch::new("settings-identity");
        let base = &scratch.0;
        make(base, "a", &meta(SyncMode::Server, None));
        make(base, "b", &meta(SyncMode::Server, Some(SERVER_URL)));
        make(base, "s", &meta(SyncMode::Sync, None));
        for id in ["a", "b", "s"] {
            hold_identity(id);
        }
        let process = SeenPrefs::new();
        {
            // No first URL beside an identity: the purge would revoke it there.
            let _a = enter("a");
            let mut settings = load_settings_in(base, Some(&process)).unwrap();
            settings.server_url = Some(SERVER_URL.to_string());
            settings.last_username = Some("admin".to_string());
            let refused = save_settings_in(base, &process, &settings).unwrap_err();
            assert!(
                matches!(&refused, AppError::Validation(msg) if msg.as_str() == IDENTITY_WITHOUT_URL),
                "{refused:?}"
            );
            assert_eq!(meta_in(base, "a"), meta(SyncMode::Server, None));
        }
        {
            // Nor another server for one that has a URL; its own, however spelled, goes.
            let _b = enter("b");
            let mut settings = load_settings_in(base, Some(&process)).unwrap();
            settings.server_url = Some("https://other.example.com".to_string());
            let refused = save_settings_in(base, &process, &settings).unwrap_err();
            assert!(
                matches!(&refused, AppError::Validation(msg) if msg.as_str() == URL_KEPT),
                "{refused:?}"
            );
            assert_eq!(meta_in(base, "b").url.as_deref(), Some(SERVER_URL));
            settings.server_url = Some("https://AH.example.com/".to_string());
            settings.last_username = Some("admin".to_string());
            save_settings_in(base, &process, &settings).unwrap();
            assert_eq!(meta_in(base, "b").url.as_deref(), Some(SERVER_URL));
            assert_eq!(meta_in(base, "b").last_username.as_deref(), Some("admin"));
        }
        // A sync workspace has no identity of its own (a migrated one sees the one of the
        // server workspace): its first source goes.
        let _s = enter("s");
        let mut settings = load_settings_in(base, Some(&process)).unwrap();
        settings.sync_url = Some(SYNC_URL.to_string());
        save_settings_in(base, &process, &settings).unwrap();
        assert_eq!(meta_in(base, "s").url.as_deref(), Some(SYNC_URL));
    }

    #[test]
    fn login_binding_a_registration_keeps_its_url_for_the_sign_in_that_follows() {
        let _keyring = keyring_store::memory();
        let scratch = Scratch::new("settings-enrolled-url");
        let base = &scratch.0;
        make(base, "a", &meta(SyncMode::Server, None));
        make(base, "b", &meta(SyncMode::Server, Some(SERVER_URL)));

        // The launcher keeps no URL.
        let no_workspace = workspace::current().unwrap_err().to_string();
        let refused = keep_enrolled_url(base, SERVER_URL).unwrap_err();
        assert_eq!(refused.to_string(), no_workspace);
        {
            // The registration of a workspace without a URL makes its URL the workspace's.
            let _a = enter("a");
            keep_enrolled_url(base, SERVER_URL).unwrap();
            hold_identity("a");
            assert_eq!(
                meta_in(base, "a"),
                Meta {
                    url: Some(SERVER_URL.to_string()),
                    ..meta(SyncMode::Server, None)
                }
            );
            // The sign-in after it saves as ever, under another spelling of that server too.
            let process = SeenPrefs::new();
            let mut settings = load_settings_in(base, Some(&process)).unwrap();
            settings.server_url = Some("https://AH.example.com:443/".to_string());
            settings.last_username = Some("admin".to_string());
            save_settings_in(base, &process, &settings).unwrap();
            assert_eq!(meta_in(base, "a").url.as_deref(), Some(SERVER_URL));
            assert_eq!(meta_in(base, "a").last_username.as_deref(), Some("admin"));
        }
        // A workspace with a URL keeps it: as it is for a registration at that server, as an
        // error for one at another (the caller resets that identity).
        let _b = enter("b");
        keep_enrolled_url(base, "https://AH.example.com:443/").unwrap();
        let refused = keep_enrolled_url(base, "https://other.example.com").unwrap_err();
        assert!(
            matches!(&refused, AppError::Validation(msg) if msg.as_str() == URL_TAKEN),
            "{refused:?}"
        );
        assert_eq!(meta_in(base, "b"), meta(SyncMode::Server, Some(SERVER_URL)));
    }

    #[test]
    fn the_launcher_has_the_prefs_and_no_connections() {
        let scratch = Scratch::new("settings-launcher");
        let base = &scratch.0;
        write_json_pretty(
            &base.join(PREFS_FILE),
            &Prefs {
                language: Some("en".to_string()),
                store_passwords: true,
                ..Prefs::default()
            },
        )
        .unwrap();
        fs::write(base.join("connections.local.json"), LEGACY_CONNECTIONS).unwrap();

        // No workspace on this thread: the launcher.
        let settings = load_settings_in(base, None).unwrap();
        assert_eq!(
            wire(&settings),
            wire(&Settings {
                language: Some("en".to_string()),
                store_passwords: true,
                ..Settings::default()
            })
        );

        assert!(matches!(
            load_connections_in(base),
            Err(AppError::Validation(_))
        ));
        assert!(matches!(
            save_connections_in(base, &connections(&["new"])),
            Err(AppError::Validation(_))
        ));
        assert_eq!(
            fs::read_to_string(base.join("connections.local.json")).unwrap(),
            LEGACY_CONNECTIONS
        );
    }

    #[test]
    fn the_connections_lie_in_the_workspace_dir_in_the_file_of_its_kind() {
        let scratch = Scratch::new("settings-connections");
        let base = &scratch.0;
        for legacy in ["connections.json", "connections.local.json"] {
            fs::write(base.join(legacy), LEGACY_CONNECTIONS).unwrap();
        }
        make(base, "l", &meta(SyncMode::Local, None));
        make(base, "s", &meta(SyncMode::Server, Some(SERVER_URL)));

        for (id, file, saved) in [
            ("l", "connections.local.json", "mine"),
            ("s", "connections.json", "theirs"),
        ] {
            let _ws = enter(id);
            assert!(
                load_connections_in(base).unwrap().is_empty(),
                "{id} read the old connections"
            );
            save_connections_in(base, &connections(&[saved])).unwrap();
            assert_eq!(ids(&load_connections_in(base).unwrap()), [saved]);
            assert_eq!(
                names_in(&workspace(id).data_dir(base)),
                [file, "workspace.json"]
            );
        }
        for legacy in ["connections.json", "connections.local.json"] {
            assert_eq!(
                fs::read_to_string(base.join(legacy)).unwrap(),
                LEGACY_CONNECTIONS
            );
        }
    }

    #[test]
    fn a_workspace_without_its_meta_fails_closed() {
        let scratch = Scratch::new("settings-no-meta");
        let base = &scratch.0;
        fs::create_dir_all(workspace("a").data_dir(base)).unwrap();
        let _a = enter("a");
        let changed = Settings {
            language: Some("en".to_string()),
            ..Settings::default()
        };

        assert!(load_settings_in(base, None).is_err());
        assert!(save_settings_in(base, &SeenPrefs::new(), &changed).is_err());
        assert!(load_connections_in(base).is_err());
        assert!(!base.join(PREFS_FILE).exists(), "a failed save wrote prefs");
    }

    #[test]
    fn the_prefs_are_read_and_written_under_their_lock() {
        let scratch = Scratch::new("settings-lock");
        let base = scratch.0.clone();
        let held = PrefsLock::exclusive(&base).unwrap();

        // No workspace on the spawned threads: the launcher, which has the prefs all the same.
        let reading = {
            let base = base.clone();
            thread::spawn(move || load_settings_in(&base, None).map(|_| ()))
        };
        let saving = {
            let base = base.clone();
            let changed = Settings {
                language: Some("en".to_string()),
                ..Settings::default()
            };
            thread::spawn(move || save_settings_in(&base, &SeenPrefs::new(), &changed))
        };
        thread::sleep(Duration::from_millis(200));
        assert!(!reading.is_finished(), "read past the held lock");
        assert!(!saving.is_finished(), "wrote past the held lock");

        drop(held);
        reading.join().unwrap().unwrap();
        saving.join().unwrap().unwrap();
        assert_eq!(json_of(&base.join(PREFS_FILE))["language"], "en");
    }

    #[test]
    fn write_json_atomic_replaces_the_file_whole_and_leaves_no_temp() {
        let scratch = Scratch::new("write-atomic");
        let path = scratch.0.join(PREFS_FILE);
        write_json_atomic(&path, &json!({"a": 1})).unwrap();
        // A reader that has the file open while it is replaced (the launcher reading a
        // workspace.json) neither stops the write nor sees half of it.
        let mut reader = File::open(&path).unwrap();

        write_json_atomic(&path, &json!({"a": 2})).unwrap();

        let mut seen = String::new();
        reader.read_to_string(&mut seen).unwrap();
        let seen: Value = serde_json::from_str(&seen).unwrap();
        assert!(seen == json!({"a": 1}) || seen == json!({"a": 2}), "{seen}");
        assert_eq!(json_of(&path), json!({"a": 2}));
        assert_eq!(names_in(&scratch.0), [PREFS_FILE]);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = fs::metadata(&path).unwrap().permissions().mode() & 0o777;
            assert_eq!(mode, 0o600);
        }
    }

    #[test]
    fn write_json_atomic_removes_only_the_stale_temps_of_the_same_file() {
        let scratch = Scratch::new("write-atomic-stale");
        let path = scratch.0.join(PREFS_FILE);
        let hour = Duration::from_secs(60 * 60);
        let now = SystemTime::now();
        let leave = |name: &str, modified: SystemTime| {
            let mut file = File::create(scratch.0.join(name)).unwrap();
            file.write_all(b"{torn").unwrap();
            file.set_modified(modified).unwrap();
        };
        // The numbers are above u32::MAX, so none is a PID: a fixture named after the test
        // process's PID would be the write's own temp file and gone after it.
        // What a process that ended between creating its temp and the rename left an hour ago.
        leave("prefs.json.4294967296.tmp", now - hour);
        // Another process writing prefs.json right now.
        leave("prefs.json.4294967297.tmp", now);
        // A clock that went back: in doubt, kept.
        leave("prefs.json.4294967298.tmp", now + hour);
        // Not a temp of a write of prefs.json.
        leave("other.json.4294967296.tmp", now - hour);
        leave("prefs.json.x4294967296.tmp", now - hour);
        // The fixed name the migration clears.
        leave("prefs.json.tmp", now - hour);

        write_json_atomic(&path, &json!({"a": 1})).unwrap();

        assert_eq!(json_of(&path), json!({"a": 1}));
        assert_eq!(
            names_in(&scratch.0),
            [
                "other.json.4294967296.tmp",
                PREFS_FILE,
                "prefs.json.4294967297.tmp",
                "prefs.json.4294967298.tmp",
                "prefs.json.tmp",
                "prefs.json.x4294967296.tmp",
            ]
        );
    }
}
