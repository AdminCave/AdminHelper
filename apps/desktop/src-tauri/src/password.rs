// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use crate::error::AppError;
use crate::models::{Connection, ConnectionKind, PasswordState};

fn normalized(value: &Option<String>) -> String {
    value.as_deref().unwrap_or("").trim().to_string()
}

fn required(value: &Option<String>, label: &str) -> Result<String, AppError> {
    let trimmed = normalized(value);
    if trimmed.is_empty() {
        return Err(AppError::Validation(format!("{label} fehlt")));
    }
    Ok(trimmed)
}

pub fn rdp_port(connection: &Connection) -> u16 {
    connection.port.unwrap_or(3389)
}

pub fn rdp_storage_key(connection: &Connection) -> Option<String> {
    let host = normalized(&connection.host);
    let username = normalized(&connection.username);
    if host.is_empty() || username.is_empty() {
        return None;
    }
    let domain = normalized(&connection.domain);
    let port = rdp_port(connection);
    Some(format!(
        "rdp|{}|{}|{}|{}",
        host.to_lowercase(),
        port,
        username.to_lowercase(),
        domain.to_lowercase()
    ))
}

pub fn rdp_storage_key_required(connection: &Connection) -> Result<String, AppError> {
    let host = required(&connection.host, "Host")?;
    let username = required(&connection.username, "Benutzer")?;
    let domain = normalized(&connection.domain);
    let port = rdp_port(connection);
    Ok(format!(
        "rdp|{}|{}|{}|{}",
        host.to_lowercase(),
        port,
        username.to_lowercase(),
        domain.to_lowercase()
    ))
}

#[cfg(unix)]
pub fn load_password_keyring(connection: &Connection) -> Result<Option<String>, AppError> {
    use keyring::{Entry, Error as KeyringError};
    const PASSWORD_SERVICE: &str = "com.adminhelper.app";

    let key = match rdp_storage_key(connection) {
        Some(value) => value,
        None => return Ok(None),
    };

    let entry =
        Entry::new(PASSWORD_SERVICE, &key).map_err(|err| AppError::Keyring(err.to_string()))?;
    match entry.get_password() {
        Ok(password) => Ok(Some(password)),
        Err(KeyringError::NoEntry) => Ok(None),
        Err(err) => Err(AppError::Keyring(err.to_string())),
    }
}

#[cfg(unix)]
pub fn save_password_keyring(connection: &Connection, password: &str) -> Result<(), AppError> {
    use keyring::Entry;
    const PASSWORD_SERVICE: &str = "com.adminhelper.app";

    let key = rdp_storage_key_required(connection)?;
    let entry =
        Entry::new(PASSWORD_SERVICE, &key).map_err(|err| AppError::Keyring(err.to_string()))?;
    entry
        .set_password(password)
        .map_err(|err| AppError::Keyring(err.to_string()))?;
    Ok(())
}

#[cfg(unix)]
pub fn delete_password_keyring(connection: &Connection) -> Result<(), AppError> {
    use keyring::{Entry, Error as KeyringError};
    const PASSWORD_SERVICE: &str = "com.adminhelper.app";

    let key = match rdp_storage_key(connection) {
        Some(value) => value,
        None => return Ok(()),
    };
    let entry =
        Entry::new(PASSWORD_SERVICE, &key).map_err(|err| AppError::Keyring(err.to_string()))?;
    match entry.delete_password() {
        Ok(_) => Ok(()),
        Err(KeyringError::NoEntry) => Ok(()),
        Err(err) => Err(AppError::Keyring(err.to_string())),
    }
}

#[cfg(target_os = "windows")]
pub fn rdp_windows_target(connection: &Connection) -> Result<String, AppError> {
    let host = required(&connection.host, "Host")?;
    let port = rdp_port(connection);
    if port == 3389 {
        Ok(format!("TERMSRV/{host}"))
    } else {
        Ok(format!("TERMSRV/{host}:{port}"))
    }
}

#[cfg(target_os = "windows")]
pub fn rdp_windows_username(connection: &Connection) -> Result<String, AppError> {
    let username = required(&connection.username, "Benutzer")?;
    let domain = normalized(&connection.domain);
    if domain.is_empty() {
        Ok(username)
    } else {
        Ok(format!("{domain}\\{username}"))
    }
}

#[cfg(target_os = "windows")]
pub fn to_utf16_null(value: &str) -> Vec<u16> {
    use std::os::windows::prelude::OsStrExt;
    let mut utf16: Vec<u16> = std::ffi::OsStr::new(value).encode_wide().collect();
    utf16.push(0);
    utf16
}

#[cfg(target_os = "windows")]
pub fn utf16_bytes(value: &str) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(value.encode_utf16().count() * 2);
    for unit in value.encode_utf16() {
        bytes.extend_from_slice(&unit.to_le_bytes());
    }
    bytes
}

#[cfg(target_os = "windows")]
pub fn windows_credential_exists(target: &str) -> Result<bool, AppError> {
    use std::ptr::null_mut;
    use windows::core::PCWSTR;
    use windows::Win32::Foundation::{GetLastError, ERROR_NOT_FOUND};
    use windows::Win32::Security::Credentials::{
        CredFree, CredReadW, CREDENTIALW, CRED_TYPE_GENERIC,
    };

    let target_w = to_utf16_null(target);
    let mut credential_ptr: *mut CREDENTIALW = null_mut();
    let ok = unsafe {
        CredReadW(
            PCWSTR(target_w.as_ptr()),
            CRED_TYPE_GENERIC,
            0,
            &mut credential_ptr,
        )
    }
    .is_ok();
    if ok {
        unsafe { CredFree(credential_ptr as *const _) };
        return Ok(true);
    }
    let err = unsafe { GetLastError() };
    if err == ERROR_NOT_FOUND {
        return Ok(false);
    }
    Err(AppError::Keyring(format!(
        "Credential Manager Fehler: {}",
        err.0
    )))
}

/// Reads the secret stored under `target` by `windows_store_credential`. The
/// blob is the value encoded as UTF-16LE bytes (see `utf16_bytes`), so decode it
/// back the same way. Mirrors the `CredReadW`/`CredFree` pattern of
/// `windows_credential_exists`.
#[cfg(target_os = "windows")]
pub fn windows_read_credential(target: &str) -> Result<String, AppError> {
    use std::ptr::null_mut;
    use std::slice;
    use windows::core::PCWSTR;
    use windows::Win32::Foundation::GetLastError;
    use windows::Win32::Security::Credentials::{
        CredFree, CredReadW, CREDENTIALW, CRED_TYPE_GENERIC,
    };

    let target_w = to_utf16_null(target);
    let mut credential_ptr: *mut CREDENTIALW = null_mut();
    let ok = unsafe {
        CredReadW(
            PCWSTR(target_w.as_ptr()),
            CRED_TYPE_GENERIC,
            0,
            &mut credential_ptr,
        )
    }
    .is_ok();
    if !ok {
        let err = unsafe { GetLastError() };
        return Err(AppError::Keyring(format!(
            "Credential Manager Fehler: {}",
            err.0
        )));
    }

    // Copy the blob out before freeing the credential.
    let cred = unsafe { &*credential_ptr };
    let size = cred.CredentialBlobSize as usize;
    let value = if size == 0 || cred.CredentialBlob.is_null() {
        String::new()
    } else {
        let bytes = unsafe { slice::from_raw_parts(cred.CredentialBlob, size) };
        let units: Vec<u16> = bytes
            .chunks_exact(2)
            .map(|c| u16::from_le_bytes([c[0], c[1]]))
            .collect();
        String::from_utf16_lossy(&units)
    };
    unsafe { CredFree(credential_ptr as *const _) };
    Ok(value)
}

#[cfg(target_os = "windows")]
pub fn windows_store_credential(
    target: &str,
    username: &str,
    password: &str,
) -> Result<(), AppError> {
    use windows::core::PWSTR;
    use windows::Win32::Foundation::GetLastError;
    use windows::Win32::Security::Credentials::{
        CredWriteW, CREDENTIALW, CRED_PERSIST_LOCAL_MACHINE, CRED_TYPE_GENERIC,
    };

    let target_w = to_utf16_null(target);
    let username_w = to_utf16_null(username);
    let mut secret_bytes = utf16_bytes(password);

    let mut credential = CREDENTIALW::default();
    credential.Type = CRED_TYPE_GENERIC;
    credential.TargetName = PWSTR(target_w.as_ptr() as *mut _);
    credential.UserName = PWSTR(username_w.as_ptr() as *mut _);
    credential.CredentialBlobSize = secret_bytes.len() as u32;
    credential.CredentialBlob = secret_bytes.as_mut_ptr();
    credential.Persist = CRED_PERSIST_LOCAL_MACHINE;

    let ok = unsafe { CredWriteW(&credential, 0) }.is_ok();
    for byte in &mut secret_bytes {
        *byte = 0;
    }
    if ok {
        Ok(())
    } else {
        let err = unsafe { GetLastError() };
        Err(AppError::Keyring(format!(
            "Credential Manager Fehler: {}",
            err.0
        )))
    }
}

#[cfg(target_os = "windows")]
pub fn windows_delete_credential(target: &str) -> Result<(), AppError> {
    use windows::core::PCWSTR;
    use windows::Win32::Foundation::{GetLastError, ERROR_NOT_FOUND};
    use windows::Win32::Security::Credentials::{CredDeleteW, CRED_TYPE_GENERIC};

    let target_w = to_utf16_null(target);
    let ok = unsafe { CredDeleteW(PCWSTR(target_w.as_ptr()), CRED_TYPE_GENERIC, 0) }.is_ok();
    if ok {
        return Ok(());
    }
    let err = unsafe { GetLastError() };
    if err == ERROR_NOT_FOUND {
        return Ok(());
    }
    Err(AppError::Keyring(format!(
        "Credential Manager Fehler: {}",
        err.0
    )))
}

pub fn password_state(connection: &Connection) -> Result<PasswordState, AppError> {
    if connection.kind != ConnectionKind::Rdp {
        return Ok(PasswordState {
            stored: false,
            can_store: false,
        });
    }

    #[cfg(target_os = "windows")]
    {
        let target = rdp_windows_target(connection)?;
        let stored = windows_credential_exists(&target)?;
        return Ok(PasswordState {
            stored,
            can_store: true,
        });
    }

    #[cfg(unix)]
    {
        let password = load_password_keyring(connection)?;
        Ok(PasswordState {
            stored: password.is_some(),
            can_store: true,
        })
    }

    #[cfg(not(any(target_os = "windows", unix)))]
    {
        return Ok(PasswordState {
            stored: false,
            can_store: false,
        });
    }
}

pub fn save_password(connection: &Connection, password: &str) -> Result<(), AppError> {
    if connection.kind != ConnectionKind::Rdp {
        return Ok(());
    }

    #[cfg(target_os = "windows")]
    {
        let target = rdp_windows_target(connection)?;
        let username = rdp_windows_username(connection)?;
        return windows_store_credential(&target, &username, password);
    }

    #[cfg(unix)]
    {
        save_password_keyring(connection, password)
    }

    #[cfg(not(any(target_os = "windows", unix)))]
    {
        let _ = password;
        return Ok(());
    }
}

pub fn delete_password(connection: &Connection) -> Result<(), AppError> {
    if connection.kind != ConnectionKind::Rdp {
        return Ok(());
    }

    #[cfg(target_os = "windows")]
    {
        let target = rdp_windows_target(connection)?;
        return windows_delete_credential(&target);
    }

    #[cfg(unix)]
    {
        delete_password_keyring(connection)
    }

    #[cfg(not(any(target_os = "windows", unix)))]
    {
        return Ok(());
    }
}
