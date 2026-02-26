use std::fs;
use std::path::{Path, PathBuf};

use tauri::Manager;

use crate::error::AppError;
use crate::models::{Connection, Settings};

pub fn data_path(app: &tauri::AppHandle) -> Result<PathBuf, AppError> {
    let base_dir = app
        .path()
        .app_data_dir()
        .map_err(|err: tauri::Error| AppError::Io(std::io::Error::other(err.to_string())))?;
    Ok(base_dir.join("connections.json"))
}

pub fn settings_path(app: &tauri::AppHandle) -> Result<PathBuf, AppError> {
    let base_dir = app
        .path()
        .app_data_dir()
        .map_err(|err: tauri::Error| AppError::Io(std::io::Error::other(err.to_string())))?;
    Ok(base_dir.join("settings.json"))
}

pub fn write_connections(
    app: &tauri::AppHandle,
    connections: &Vec<Connection>,
) -> Result<(), AppError> {
    let path = data_path(app)?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let serialized = serde_json::to_string_pretty(connections)?;
    fs::write(&path, serialized)?;
    harden_permissions(&path);
    Ok(())
}

pub fn load_connections(app: &tauri::AppHandle) -> Result<Vec<Connection>, AppError> {
    let path = data_path(app)?;
    if !path.exists() {
        return Ok(Vec::new());
    }
    let data = fs::read_to_string(&path)?;
    let connections: Vec<Connection> = serde_json::from_str(&data)?;
    Ok(connections)
}

pub fn save_connections(
    app: &tauri::AppHandle,
    connections: &Vec<Connection>,
) -> Result<(), AppError> {
    write_connections(app, connections)
}

pub fn load_settings(app: &tauri::AppHandle) -> Result<Settings, AppError> {
    let path = settings_path(app)?;
    if !path.exists() {
        return Ok(Settings::default());
    }
    let data = fs::read_to_string(&path)?;
    let settings: Settings = serde_json::from_str(&data)?;
    Ok(settings)
}

pub fn save_settings(app: &tauri::AppHandle, settings: &Settings) -> Result<(), AppError> {
    let path = settings_path(app)?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let serialized = serde_json::to_string_pretty(settings)?;
    fs::write(&path, serialized)?;
    harden_permissions(&path);
    Ok(())
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
