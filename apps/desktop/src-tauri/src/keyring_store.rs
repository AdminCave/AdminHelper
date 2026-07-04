// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! Central OS-keyring backend shared by every security module (auth session,
//! enrollment identity, TOFU pins). It collapses the per-module `#[cfg(unix)]` /
//! `#[cfg(windows)]` dispatch and the duplicated service constant into one place,
//! so a change to error handling, the service name, or the Windows persist flag
//! happens once instead of drifting across four copies.
//!
//! On Unix this is the `keyring` crate; on Windows it delegates to the Windows
//! Credential Manager wrappers in [`crate::password`] (the platform storage
//! layer). The RDP password store in `password` keeps its own OS-specific
//! `TERMSRV/` logic — that credential must be readable by `mstsc.exe`, so it is
//! not a generic app key and cannot go through this abstraction.

use crate::error::AppError;

/// Credential-store service/collection every app secret lives under.
pub const SERVICE: &str = "com.admincave.adminhelper";

#[cfg(unix)]
pub fn set(key: &str, value: &str) -> Result<(), AppError> {
    use keyring::Entry;
    Entry::new(SERVICE, key)
        .and_then(|entry| entry.set_password(value))
        .map_err(|e| AppError::Keyring(e.to_string()))
}

#[cfg(target_os = "windows")]
pub fn set(key: &str, value: &str) -> Result<(), AppError> {
    crate::password::windows_store_credential(key, "adminhelper", value)
}

#[cfg(not(any(unix, target_os = "windows")))]
pub fn set(_key: &str, _value: &str) -> Result<(), AppError> {
    Err(AppError::Keyring("Plattform nicht unterstützt".to_string()))
}

/// Read a stored secret, or `None` if absent or the store is unavailable. Errors
/// degrade to `None` on purpose — callers treat "no value" and "cannot read"
/// alike (first-use capture for TOFU, "not enrolled" for the identity).
#[cfg(unix)]
pub fn get(key: &str) -> Option<String> {
    use keyring::Entry;
    Entry::new(SERVICE, key).ok()?.get_password().ok()
}

#[cfg(target_os = "windows")]
pub fn get(key: &str) -> Option<String> {
    crate::password::windows_read_credential(key)
        .ok()
        .filter(|v| !v.is_empty())
}

#[cfg(not(any(unix, target_os = "windows")))]
pub fn get(_key: &str) -> Option<String> {
    None
}

/// Delete a stored secret. A missing entry is success; a real store error
/// propagates so callers that care (session logout) can surface it.
#[cfg(unix)]
pub fn delete(key: &str) -> Result<(), AppError> {
    use keyring::{Entry, Error as KeyringError};
    match Entry::new(SERVICE, key) {
        Ok(entry) => match entry.delete_credential() {
            Ok(_) | Err(KeyringError::NoEntry) => Ok(()),
            Err(e) => Err(AppError::Keyring(e.to_string())),
        },
        Err(e) => Err(AppError::Keyring(e.to_string())),
    }
}

#[cfg(target_os = "windows")]
pub fn delete(key: &str) -> Result<(), AppError> {
    crate::password::windows_delete_credential(key)
}

#[cfg(not(any(unix, target_os = "windows")))]
pub fn delete(_key: &str) -> Result<(), AppError> {
    Ok(())
}
