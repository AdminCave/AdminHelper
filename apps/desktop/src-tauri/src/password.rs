// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use crate::error::AppError;
use crate::models::{Connection, ConnectionKind, PasswordState};
use crate::validation::required;

fn normalized(value: &Option<String>) -> String {
    value.as_deref().unwrap_or("").trim().to_string()
}

pub fn rdp_port(connection: &Connection) -> u16 {
    connection.port.unwrap_or(3389)
}

/// Host, port, user and domain of an RDP password's key.
fn rdp_target(connection: &Connection) -> Option<String> {
    let host = normalized(&connection.host);
    let username = normalized(&connection.username);
    if host.is_empty() || username.is_empty() {
        return None;
    }
    let domain = normalized(&connection.domain);
    let port = rdp_port(connection);
    Some(format!(
        "{}|{}|{}|{}",
        host.to_lowercase(),
        port,
        username.to_lowercase(),
        domain.to_lowercase()
    ))
}

/// The key of the connection's RDP password, `rdp|<id>|<host>|<port>|<user>|<domain>`.
/// An empty id, or one with the separator, names no single connection and gets none.
pub fn rdp_storage_key(connection: &Connection) -> Option<String> {
    let id = &connection.id;
    if id.is_empty() || id.contains('|') {
        return None;
    }
    Some(format!("rdp|{id}|{}", rdp_target(connection)?))
}

pub fn rdp_storage_key_required(connection: &Connection) -> Result<String, AppError> {
    required(&connection.host, "Host")?;
    required(&connection.username, "Benutzer")?;
    rdp_storage_key(connection)
        .ok_or_else(|| AppError::Validation("connection id is empty or contains '|'".to_string()))
}

/// The connection's key, and the key without the id that RDP passwords were stored
/// under before, shared by all connections to the same target, user and domain.
#[cfg(unix)]
fn rdp_storage_keys(connection: &Connection) -> Option<(String, String)> {
    let key = rdp_storage_key(connection)?;
    let legacy = format!("rdp|{}", rdp_target(connection)?);
    Some((key, legacy))
}

#[cfg(unix)]
pub fn load_password_keyring(connection: &Connection) -> Result<Option<String>, AppError> {
    use crate::keyring_store::{delete, set, try_get};

    let Some((key, legacy)) = rdp_storage_keys(connection) else {
        return Ok(None);
    };
    if let Some(password) = try_get(&key)? {
        return Ok(Some(password));
    }
    // The first connection that loads a legacy entry takes it over, so it stops
    // answering for the other connections to the same target.
    let Some(password) = try_get(&legacy)? else {
        return Ok(None);
    };
    set(&key, &password)?;
    delete(&legacy)?;
    Ok(Some(password))
}

/// Whether a password is stored for the connection, under its key or the legacy
/// one. Reads only: the legacy entry moves when it is loaded.
#[cfg(unix)]
fn password_stored_keyring(connection: &Connection) -> Result<bool, AppError> {
    use crate::keyring_store::try_get;

    let Some((key, legacy)) = rdp_storage_keys(connection) else {
        return Ok(false);
    };
    Ok(try_get(&key)?.is_some() || try_get(&legacy)?.is_some())
}

#[cfg(unix)]
pub fn save_password_keyring(connection: &Connection, password: &str) -> Result<(), AppError> {
    let key = rdp_storage_key_required(connection)?;
    crate::keyring_store::set(&key, password)
}

#[cfg(unix)]
pub fn delete_password_keyring(connection: &Connection) -> Result<(), AppError> {
    use crate::keyring_store::delete;

    let Some((key, legacy)) = rdp_storage_keys(connection) else {
        return Ok(());
    };
    delete(&key)?;
    delete(&legacy)
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
            Some(0),
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
            Some(0),
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
    let ok = unsafe { CredDeleteW(PCWSTR(target_w.as_ptr()), CRED_TYPE_GENERIC, Some(0)) }.is_ok();
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
        Ok(PasswordState {
            stored: password_stored_keyring(connection)?,
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::ConnectionKind;

    fn rdp(
        host: Option<&str>,
        port: Option<u16>,
        user: Option<&str>,
        domain: Option<&str>,
    ) -> Connection {
        Connection {
            id: "c1".into(),
            name: "T".into(),
            kind: ConnectionKind::Rdp,
            host: host.map(String::from),
            port,
            username: user.map(String::from),
            domain: domain.map(String::from),
            key_path: None,
            url: None,
            notes: None,
            tags: Vec::new(),
            trust_cert: false,
            last_used: None,
            server_id: None,
        }
    }

    #[test]
    fn rdp_port_defaults_to_3389() {
        assert_eq!(rdp_port(&rdp(Some("h"), None, Some("u"), None)), 3389);
        assert_eq!(rdp_port(&rdp(Some("h"), Some(3390), Some("u"), None)), 3390);
    }

    /// `Host.COM:3390` as `Admin` in `CORP`, under the connection id `id`.
    fn rdp_with_id(id: &str) -> Connection {
        Connection {
            id: id.into(),
            ..rdp(Some("Host.COM"), Some(3390), Some("Admin"), Some("CORP"))
        }
    }

    /// Where an RDP password for `rdp_with_id` was stored before keys carried the
    /// connection id.
    #[cfg(unix)]
    const LEGACY_KEY: &str = "rdp|host.com|3390|admin|corp";

    // The storage key is the credential cache key: it must be host/user/domain
    // case-insensitive (so "Host"/"host" don't double-store) and carry the port.
    #[test]
    fn storage_key_lowercases_and_joins_fields() {
        let c = rdp(Some("Host.COM"), Some(3390), Some("Admin"), Some("CORP"));
        assert_eq!(
            rdp_storage_key(&c).as_deref(),
            Some("rdp|c1|host.com|3390|admin|corp")
        );
    }

    #[test]
    fn storage_key_uses_default_port_and_empty_domain() {
        let c = rdp(Some("h"), None, Some("u"), None);
        assert_eq!(rdp_storage_key(&c).as_deref(), Some("rdp|c1|h|3389|u|"));
    }

    #[test]
    fn storage_key_keeps_the_connection_id_as_it_is() {
        assert_eq!(
            rdp_storage_key(&rdp_with_id("Conn-A")).as_deref(),
            Some("rdp|Conn-A|host.com|3390|admin|corp")
        );
    }

    // Two connections to the same target, user and domain, e.g. from two servers,
    // keep their passwords apart.
    #[test]
    fn storage_key_differs_by_connection_id() {
        let a = rdp_storage_key(&rdp_with_id("a"));
        let b = rdp_storage_key(&rdp_with_id("b"));
        assert!(a.is_some() && b.is_some());
        assert_ne!(a, b);
    }

    #[test]
    fn storage_key_is_none_for_an_empty_id_or_one_with_the_separator() {
        for id in ["", "a|b", "|"] {
            let c = rdp_with_id(id);
            assert!(rdp_storage_key(&c).is_none(), "{id:?}");
            assert!(
                matches!(rdp_storage_key_required(&c), Err(AppError::Validation(_))),
                "{id:?}"
            );
        }
    }

    #[test]
    fn storage_key_is_none_without_host_or_user() {
        assert!(rdp_storage_key(&rdp(None, None, Some("u"), None)).is_none());
        assert!(rdp_storage_key(&rdp(Some("h"), None, None, None)).is_none());
        assert!(rdp_storage_key(&rdp(Some("   "), None, Some("u"), None)).is_none());
    }

    #[test]
    fn storage_key_required_errors_when_host_or_user_missing() {
        assert!(rdp_storage_key_required(&rdp(None, None, Some("u"), None)).is_err());
        assert!(rdp_storage_key_required(&rdp(Some("h"), None, None, None)).is_err());
        assert_eq!(
            rdp_storage_key_required(&rdp(Some("H"), Some(3389), Some("U"), None)).unwrap(),
            "rdp|c1|h|3389|u|"
        );
    }

    #[cfg(unix)]
    #[test]
    fn a_stored_password_belongs_to_one_connection() {
        let _keyring = crate::keyring_store::memory();
        let a = rdp_with_id("a");
        let b = rdp_with_id("b");
        save_password(&a, "secret-a").unwrap();
        assert!(password_state(&a).unwrap().stored);
        assert!(!password_state(&b).unwrap().stored);
        assert_eq!(
            load_password_keyring(&a).unwrap().as_deref(),
            Some("secret-a")
        );
        assert_eq!(load_password_keyring(&b).unwrap(), None);
    }

    #[cfg(unix)]
    #[test]
    fn a_legacy_password_goes_to_the_first_connection_that_loads_it() {
        use crate::keyring_store::{set, try_get};
        let _keyring = crate::keyring_store::memory();
        set(LEGACY_KEY, "old").unwrap();
        let a = rdp_with_id("a");
        let b = rdp_with_id("b");

        // The state finds the legacy entry for both and leaves it where it is.
        assert!(password_state(&a).unwrap().stored);
        assert!(password_state(&b).unwrap().stored);
        assert_eq!(try_get(LEGACY_KEY).unwrap().as_deref(), Some("old"));

        assert_eq!(load_password_keyring(&a).unwrap().as_deref(), Some("old"));
        assert_eq!(
            try_get("rdp|a|host.com|3390|admin|corp")
                .unwrap()
                .as_deref(),
            Some("old")
        );
        assert_eq!(try_get(LEGACY_KEY).unwrap(), None);
        assert_eq!(load_password_keyring(&a).unwrap().as_deref(), Some("old"));

        assert!(!password_state(&b).unwrap().stored);
        assert_eq!(load_password_keyring(&b).unwrap(), None);
    }

    #[cfg(unix)]
    #[test]
    fn the_connection_key_wins_over_a_legacy_entry() {
        use crate::keyring_store::{set, try_get};
        let _keyring = crate::keyring_store::memory();
        let a = rdp_with_id("a");
        save_password(&a, "new").unwrap();
        set(LEGACY_KEY, "old").unwrap();
        assert_eq!(load_password_keyring(&a).unwrap().as_deref(), Some("new"));
        assert_eq!(try_get(LEGACY_KEY).unwrap().as_deref(), Some("old"));
    }

    #[cfg(unix)]
    #[test]
    fn saving_writes_only_the_connection_key() {
        use crate::keyring_store::try_get;
        let _keyring = crate::keyring_store::memory();
        save_password(&rdp_with_id("a"), "secret").unwrap();
        assert_eq!(
            try_get("rdp|a|host.com|3390|admin|corp")
                .unwrap()
                .as_deref(),
            Some("secret")
        );
        assert_eq!(try_get(LEGACY_KEY).unwrap(), None);
    }

    #[cfg(unix)]
    #[test]
    fn deleting_removes_the_connection_key_and_the_legacy_entry() {
        use crate::keyring_store::{set, try_get};
        let _keyring = crate::keyring_store::memory();
        let a = rdp_with_id("a");
        save_password(&a, "new").unwrap();
        set(LEGACY_KEY, "old").unwrap();
        delete_password(&a).unwrap();
        assert_eq!(try_get("rdp|a|host.com|3390|admin|corp").unwrap(), None);
        assert_eq!(try_get(LEGACY_KEY).unwrap(), None);
        assert!(!password_state(&a).unwrap().stored);
    }

    #[cfg(unix)]
    #[test]
    fn a_connection_without_a_key_stores_and_takes_over_nothing() {
        use crate::keyring_store::{set, try_get};
        let _keyring = crate::keyring_store::memory();
        set(LEGACY_KEY, "old").unwrap();
        for id in ["", "a|b"] {
            let c = rdp_with_id(id);
            assert!(!password_state(&c).unwrap().stored, "{id:?}");
            assert_eq!(load_password_keyring(&c).unwrap(), None, "{id:?}");
            assert!(
                matches!(save_password(&c, "x"), Err(AppError::Validation(_))),
                "{id:?}"
            );
            delete_password(&c).unwrap();
        }
        for key in [
            "rdp||host.com|3390|admin|corp",
            "rdp|a|b|host.com|3390|admin|corp",
        ] {
            assert_eq!(try_get(key).unwrap(), None, "{key}");
        }
        assert_eq!(try_get(LEGACY_KEY).unwrap().as_deref(), Some("old"));
    }

    // Windows-only credential/target formatting. These execute now that the CI
    // Windows job runs `cargo test` instead of only `cargo check` (6.33).
    #[cfg(target_os = "windows")]
    #[test]
    fn windows_target_uses_termsrv_and_omits_default_port() {
        assert_eq!(
            rdp_windows_target(&rdp(Some("srv"), None, Some("u"), None)).unwrap(),
            "TERMSRV/srv"
        );
        assert_eq!(
            rdp_windows_target(&rdp(Some("srv"), Some(3390), Some("u"), None)).unwrap(),
            "TERMSRV/srv:3390"
        );
        assert!(rdp_windows_target(&rdp(None, None, Some("u"), None)).is_err());
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn windows_username_prefixes_domain_with_backslash() {
        assert_eq!(
            rdp_windows_username(&rdp(Some("h"), None, Some("u"), None)).unwrap(),
            "u"
        );
        assert_eq!(
            rdp_windows_username(&rdp(Some("h"), None, Some("u"), Some("CORP"))).unwrap(),
            "CORP\\u"
        );
        assert!(rdp_windows_username(&rdp(Some("h"), None, None, None)).is_err());
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn utf16_null_appends_terminator() {
        assert_eq!(to_utf16_null("AB"), vec![0x41u16, 0x42, 0x00]);
        assert_eq!(to_utf16_null(""), vec![0x00u16]);
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn utf16_bytes_are_little_endian_without_terminator() {
        // 'A' = U+0041 → LE bytes 0x41 0x00; no trailing NUL.
        assert_eq!(utf16_bytes("A"), vec![0x41u8, 0x00]);
        assert_eq!(utf16_bytes("AB"), vec![0x41u8, 0x00, 0x42, 0x00]);
    }
}
