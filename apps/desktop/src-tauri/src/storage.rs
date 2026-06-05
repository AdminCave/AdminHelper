// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::fs;
use std::path::{Path, PathBuf};

use serde::de::DeserializeOwned;
use serde::Serialize;
use tauri::Manager;

use crate::error::AppError;
use crate::models::{Connection, Settings};

fn app_data_file(app: &tauri::AppHandle, file_name: &str) -> Result<PathBuf, AppError> {
    let base_dir = app
        .path()
        .app_data_dir()
        .map_err(|err: tauri::Error| AppError::Io(std::io::Error::other(err.to_string())))?;
    Ok(base_dir.join(file_name))
}

pub fn data_path(app: &tauri::AppHandle) -> Result<PathBuf, AppError> {
    app_data_file(app, "connections.json")
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

pub fn write_connections(
    app: &tauri::AppHandle,
    connections: &[Connection],
) -> Result<(), AppError> {
    let path = data_path(app)?;
    write_json_pretty(&path, connections)
}

pub fn load_connections(app: &tauri::AppHandle) -> Result<Vec<Connection>, AppError> {
    let path = data_path(app)?;
    read_json_or_default(&path)
}

pub fn save_connections(
    app: &tauri::AppHandle,
    connections: &[Connection],
) -> Result<(), AppError> {
    write_connections(app, connections)
}

pub fn load_settings(app: &tauri::AppHandle) -> Result<Settings, AppError> {
    let path = settings_path(app)?;
    read_json_or_default(&path)
}

pub fn save_settings(app: &tauri::AppHandle, settings: &Settings) -> Result<(), AppError> {
    let path = settings_path(app)?;
    write_json_pretty(&path, settings)
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
