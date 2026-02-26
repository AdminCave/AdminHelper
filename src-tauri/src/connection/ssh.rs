use crate::error::AppError;
use crate::models::Connection;
use crate::terminal::{open_linux_terminal, open_windows_terminal};
use crate::validation::{validate_host, validate_no_control_chars};

fn required(value: &Option<String>, label: &str) -> Result<String, AppError> {
    let trimmed = value.as_deref().unwrap_or("").trim().to_string();
    if trimmed.is_empty() {
        return Err(AppError::Validation(format!("{label} fehlt")));
    }
    Ok(trimmed)
}

pub fn open_ssh(connection: &Connection) -> Result<(), AppError> {
    let host = required(&connection.host, "Host")?;
    validate_host(&host)?;
    let port = connection.port.unwrap_or(22);
    let mut args: Vec<String> = Vec::new();
    if port != 22 {
        args.push("-p".to_string());
        args.push(port.to_string());
    }
    if let Some(key_path) = connection.key_path.as_ref() {
        let trimmed = key_path.trim();
        if !trimmed.is_empty() {
            if trimmed.contains("..") {
                return Err(AppError::Validation("Ungueltiger SSH Key Pfad".to_string()));
            }
            args.push("-i".to_string());
            args.push(trimmed.to_string());
        }
    }
    let target = if let Some(username) = connection.username.as_ref() {
        let u = username.trim();
        if !u.is_empty() {
            validate_no_control_chars(u, "Benutzer")?;
            format!("{u}@{host}")
        } else {
            host.to_string()
        }
    } else {
        host.to_string()
    };
    args.push("--".to_string());
    args.push(target);

    if cfg!(target_os = "windows") {
        open_windows_terminal("ssh", &args)
    } else {
        open_linux_terminal("ssh", &args)
    }
}
