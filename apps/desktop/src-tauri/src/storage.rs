// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::fs;
use std::path::{Path, PathBuf};

use serde::de::DeserializeOwned;
use serde::Serialize;
use tauri::Manager;

use crate::error::AppError;
use crate::models::{Connection, Settings, SyncMode};

fn app_data_file(app: &tauri::AppHandle, file_name: &str) -> Result<PathBuf, AppError> {
    let base_dir = app
        .path()
        .app_data_dir()
        .map_err(|err: tauri::Error| AppError::Io(std::io::Error::other(err.to_string())))?;
    Ok(base_dir.join(file_name))
}

/// connections.json — the transient cache for server/sync mode. It is
/// overwritten on every fetch/sync and is NOT the local-mode store.
pub fn data_path(app: &tauri::AppHandle) -> Result<PathBuf, AppError> {
    app_data_file(app, "connections.json")
}

/// connections.local.json — the persistent store for local mode, kept separate
/// from the server/sync cache so a server/sync fetch can never overwrite the
/// user's locally managed connections.
pub fn local_data_path(app: &tauri::AppHandle) -> Result<PathBuf, AppError> {
    app_data_file(app, connections_file_name(&SyncMode::Local))
}

/// The connections file backing a given mode: local mode has its own store,
/// server and sync share the cache file.
fn connections_file_name(mode: &SyncMode) -> &'static str {
    match mode {
        SyncMode::Local => "connections.local.json",
        SyncMode::Server | SyncMode::Sync => "connections.json",
    }
}

fn connections_path_for(app: &tauri::AppHandle, mode: &SyncMode) -> Result<PathBuf, AppError> {
    app_data_file(app, connections_file_name(mode))
}

fn current_mode(app: &tauri::AppHandle) -> SyncMode {
    load_settings(app)
        .map(|s| s.mode)
        .unwrap_or(SyncMode::Local)
}

pub fn settings_path(app: &tauri::AppHandle) -> Result<PathBuf, AppError> {
    app_data_file(app, "settings.json")
}

fn ensure_parent(path: &Path) -> Result<(), AppError> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    Ok(())
}

fn write_json_pretty<T: Serialize + ?Sized>(path: &Path, value: &T) -> Result<(), AppError> {
    ensure_parent(path)?;
    let serialized = serde_json::to_string_pretty(value)?;
    fs::write(path, serialized)?;
    harden_permissions(path);
    Ok(())
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

/// Reads the connections backing the active mode: the local store in local
/// mode, the server/sync cache otherwise.
pub fn load_connections(app: &tauri::AppHandle) -> Result<Vec<Connection>, AppError> {
    let path = connections_path_for(app, &current_mode(app))?;
    read_json_or_default(&path)
}

/// Persists connections to the file backing the active mode. In server mode the
/// connections are owned by the server (written through the API), so this is hit
/// only for local mode (the local store) and sync mode (the cache).
pub fn save_connections(
    app: &tauri::AppHandle,
    connections: &[Connection],
) -> Result<(), AppError> {
    let path = connections_path_for(app, &current_mode(app))?;
    write_json_pretty(&path, connections)
}

/// One-time migration of the pre-split local store. Before connections.local.json
/// existed, local mode kept its connections in connections.json (shared with the
/// server/sync cache). Run once at startup and guarded by the boot-time mode:
/// only in local mode does connections.json hold the user's local data (in
/// server/sync mode it is a cache). Running at startup — before any server fetch
/// can overwrite connections.json — guarantees the real local data is adopted.
pub fn migrate_legacy_local_store(app: &tauri::AppHandle) -> Result<(), AppError> {
    if !matches!(current_mode(app), SyncMode::Local) {
        return Ok(());
    }
    let local = local_data_path(app)?;
    if local.exists() {
        return Ok(());
    }
    let legacy = data_path(app)?;
    if !legacy.exists() {
        return Ok(());
    }
    let data = fs::read_to_string(&legacy)?;
    ensure_parent(&local)?;
    fs::write(&local, data)?;
    harden_permissions(&local);
    Ok(())
}

pub fn load_settings(app: &tauri::AppHandle) -> Result<Settings, AppError> {
    let path = settings_path(app)?;
    read_json_or_default(&path)
}

pub fn save_settings(app: &tauri::AppHandle, settings: &Settings) -> Result<(), AppError> {
    let path = settings_path(app)?;
    write_json_pretty(&path, settings)
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
        let _ = Command::new("icacls")
            .args([
                path_str.as_ref(),
                "/inheritance:r",
                "/grant:r",
                &format!("{user}:F"),
            ])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status();
    }
}

#[cfg(not(any(unix, target_os = "windows")))]
pub fn harden_permissions(_path: &Path) {}

#[cfg(test)]
mod tests {
    use super::connections_file_name;
    use crate::models::SyncMode;

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
