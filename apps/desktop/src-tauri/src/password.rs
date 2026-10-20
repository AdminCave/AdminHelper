// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::collections::BTreeSet;
use std::path::Path;
#[cfg(unix)]
use std::sync::{Mutex, PoisonError};

use serde::{Deserialize, Serialize};

use crate::error::AppError;
use crate::models::{Connection, ConnectionKind, PasswordState};
use crate::validation::required;
#[cfg(unix)]
use crate::workspace::{self, Workspace};

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

/// The key of the connection's RDP password, `rdp|<id>|<host>|<port>|<user>|<domain>`,
/// in the keyring behind the prefix of the workspace. An empty id, or one with the
/// separator, names no single connection and gets none.
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

/// The connection's key in the keyring of `workspace`, behind its prefix (R-0431),
/// and the key without the id that RDP passwords were stored under before, shared
/// by all connections to the same target, user and domain. Only a migrated
/// workspace (`legacy_keys`) has such an entry; a new one never reads or deletes
/// it, as it belongs to the migrated ones. Callers take `workspace` from
/// `workspace::current()`, which fails in the launcher: no RDP key there, never
/// one without a prefix.
#[cfg(unix)]
fn rdp_storage_keys(
    workspace: &Workspace,
    connection: &Connection,
) -> Option<(String, Option<String>)> {
    let key = format!(
        "{}{}",
        workspace.keyring_prefix(),
        rdp_storage_key(connection)?
    );
    let legacy = if workspace.legacy_keys {
        Some(format!("rdp|{}", rdp_target(connection)?))
    } else {
        None
    };
    Some((key, legacy))
}

/// Whether the connection's target is this machine: `localhost` or a name under
/// `.localhost`, or a loopback or unspecified address, also with a trailing dot,
/// in brackets or IPv4-mapped. Short and hex forms such as `127.1` are not
/// recognized.
#[cfg(unix)]
fn targets_this_machine(connection: &Connection) -> bool {
    let host = normalized(&connection.host).to_lowercase();
    let host = host.strip_suffix('.').unwrap_or(&host);
    let host = host
        .strip_prefix('[')
        .and_then(|h| h.strip_suffix(']'))
        .unwrap_or(host);
    host == "localhost"
        || host.ends_with(".localhost")
        || host.parse::<std::net::IpAddr>().is_ok_and(|ip| {
            let ip = ip.to_canonical();
            ip.is_loopback() || ip.is_unspecified()
        })
}

/// The password under the legacy key, read for no target on this machine:
/// connections of different servers can name the same one, e.g. 127.0.0.1 and
/// the same port, so such an entry may belong to any of them.
#[cfg(unix)]
fn legacy_password(connection: &Connection, legacy: &str) -> Result<Option<String>, AppError> {
    if targets_this_machine(connection) {
        return Ok(None);
    }
    crate::keyring_store::try_get(legacy)
}

#[cfg(unix)]
pub fn load_password_keyring(connection: &Connection) -> Result<Option<String>, AppError> {
    use crate::keyring_store::{delete, set, try_get};

    let Some((key, legacy)) = rdp_storage_keys(&workspace::current()?, connection) else {
        return Ok(None);
    };
    if let Some(password) = try_get(&key)? {
        return Ok(Some(password));
    }
    let Some(legacy) = legacy else {
        return Ok(None);
    };
    // The first connection that loads a legacy entry takes it over, so it stops
    // answering for the other connections to the same target.
    let Some(password) = legacy_password(connection, &legacy)? else {
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

    let Some((key, legacy)) = rdp_storage_keys(&workspace::current()?, connection) else {
        return Ok(false);
    };
    if try_get(&key)?.is_some() {
        return Ok(true);
    }
    match legacy {
        Some(legacy) => Ok(legacy_password(connection, &legacy)?.is_some()),
        None => Ok(false),
    }
}

/// In the data dir of a workspace: the names of its RDP keys in the keyring, never
/// a secret (R-0431). The keyring cannot list its entries, so deleting a workspace
/// deletes the keys named here ([`indexed_keys`]). A key that a migrated workspace
/// takes over on load is not named. The names of a migrated workspace carry no
/// prefix, as the keys of every migrated workspace: while another migrated workspace
/// is there that may use them too, its purge hands them over ([`HANDED_OVER_FILE`]),
/// and the purge of the last migrated workspace deletes them.
const SECRETS_FILE: &str = "secrets.json";

/// In the app data dir: the names of RDP keys without a prefix whose migrated
/// workspace was deleted while another migrated workspace was there; the purge of the
/// last migrated workspace deletes these keys with its own, then this file. Only the
/// purge writes it, and one purge runs at a time (`launcher::delete`).
const HANDED_OVER_FILE: &str = "legacy-secrets.json";

/// How every RDP key begins behind the keyring prefix of its workspace
/// ([`rdp_storage_key`]).
const RDP_KEY_HEAD: &str = "rdp|";

/// What [`SECRETS_FILE`] and [`HANDED_OVER_FILE`] hold.
#[derive(Default, Serialize, Deserialize)]
struct SecretIndex {
    keys: BTreeSet<String>,
}

/// The index at `path`; empty if there is none. A file that does not parse is an
/// error: written over, it would lose the names in it, and a purge would leave the
/// keys it names behind.
fn read_index(path: &Path) -> Result<SecretIndex, AppError> {
    match std::fs::read(path) {
        Ok(bytes) => Ok(serde_json::from_slice(&bytes)?),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(SecretIndex::default()),
        Err(e) => Err(e.into()),
    }
}

/// The names in the index `file` in `dir` for a purge, each an RDP key behind
/// `prefix`. Any other name is an error, so the purge stops before it deletes a key of
/// another workspace, the identity or a pin. So is a file that does not parse; its
/// error names the file and where it breaks, never a value from it.
fn purge_keys(dir: &Path, file: &str, prefix: &str) -> Result<BTreeSet<String>, AppError> {
    let keys = match read_index(&dir.join(file)) {
        Ok(index) => index.keys,
        Err(e @ AppError::Json(_)) => {
            return Err(AppError::Validation(format!(
                "{file} does not load ({})",
                crate::workspace::failure(&e)
            )))
        }
        Err(e) => return Err(e),
    };
    let own = format!("{prefix}{RDP_KEY_HEAD}");
    if keys.iter().any(|key| !key.starts_with(&own)) {
        return Err(AppError::Validation(format!(
            "{file} names a key that is no RDP password of this workspace"
        )));
    }
    Ok(keys)
}

/// The RDP keys the index in `dir` names, `dir` being the data dir of the workspace
/// whose keyring prefix is `prefix`: what the purge of that workspace deletes.
pub(crate) fn indexed_keys(dir: &Path, prefix: &str) -> Result<BTreeSet<String>, AppError> {
    purge_keys(dir, SECRETS_FILE, prefix)
}

/// The RDP keys without a prefix that purges of migrated workspaces handed over in
/// `base`, the app data dir: what the purge of the last migrated workspace deletes
/// with its own.
pub(crate) fn handed_over_keys(base: &Path) -> Result<BTreeSet<String>, AppError> {
    purge_keys(base, HANDED_OVER_FILE, "")
}

/// Hands `keys`, RDP keys without a prefix, over to the purge of the last migrated
/// workspace in `base`, the app data dir, which `handed_over` were handed over to
/// before ([`handed_over_keys`], read before the purge changed a thing).
pub(crate) fn hand_over_keys(
    base: &Path,
    mut handed_over: BTreeSet<String>,
    keys: &BTreeSet<String>,
) -> Result<(), AppError> {
    if keys.iter().any(|key| !key.starts_with(RDP_KEY_HEAD)) {
        return Err(AppError::Validation(
            "only RDP keys without a prefix are handed over".to_string(),
        ));
    }
    if !keys.is_subset(&handed_over) {
        handed_over.extend(keys.iter().cloned());
        crate::storage::write_json_atomic(
            &base.join(HANDED_OVER_FILE),
            &SecretIndex { keys: handed_over },
        )?;
    }
    Ok(())
}

/// Removes the file of the handed over keys in `base`, once they are deleted.
pub(crate) fn forget_handed_over_keys(base: &Path) -> Result<(), AppError> {
    remove_file_if_there(&base.join(HANDED_OVER_FILE))
}

/// Removes the index in `dir`, the data dir of a workspace, once the keys it names
/// are deleted or handed over.
pub(crate) fn remove_index(dir: &Path) -> Result<(), AppError> {
    remove_file_if_there(&dir.join(SECRETS_FILE))
}

fn remove_file_if_there(path: &Path) -> Result<(), AppError> {
    match std::fs::remove_file(path) {
        Err(e) if e.kind() != std::io::ErrorKind::NotFound => Err(e.into()),
        _ => Ok(()),
    }
}

/// Held while an index changes, so two saves in one process keep each other's name;
/// the workspace lock keeps every other process off the file.
#[cfg(unix)]
static INDEX_LOCK: Mutex<()> = Mutex::new(());

/// Apply `change` to the index in `dir`, the data dir of a workspace, and write it
/// back if `change` says it changed.
#[cfg(unix)]
fn update_index(
    dir: &Path,
    change: impl FnOnce(&mut BTreeSet<String>) -> bool,
) -> Result<(), AppError> {
    let _held = INDEX_LOCK.lock().unwrap_or_else(PoisonError::into_inner);
    let path = dir.join(SECRETS_FILE);
    let mut index = read_index(&path)?;
    if change(&mut index.keys) {
        crate::storage::write_json_atomic(&path, &index)?;
    }
    Ok(())
}

/// Store the password under the connection's key in the workspace of this process;
/// `base` is the app data dir.
#[cfg(unix)]
pub fn save_password_keyring(
    base: &Path,
    connection: &Connection,
    password: &str,
) -> Result<(), AppError> {
    let workspace = workspace::current()?;
    let key = format!(
        "{}{}",
        workspace.keyring_prefix(),
        rdp_storage_key_required(connection)?
    );
    // The name goes in first: a key the index does not name would outlive its workspace.
    update_index(&workspace.data_dir(base), |keys| keys.insert(key.clone()))?;
    crate::keyring_store::set(&key, password)
}

#[cfg(unix)]
pub fn delete_password_keyring(base: &Path, connection: &Connection) -> Result<(), AppError> {
    use crate::keyring_store::delete;

    let workspace = workspace::current()?;
    let Some((key, legacy)) = rdp_storage_keys(&workspace, connection) else {
        return Ok(());
    };
    delete(&key)?;
    if let Some(legacy) = legacy {
        delete(&legacy)?;
    }
    // The name goes last: while the key may still be there, the index names it.
    update_index(&workspace.data_dir(base), |keys| keys.remove(&key))
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

/// Store the RDP password of `connection`; `base` is the app data dir, where the
/// index of the workspace's keys lies.
pub fn save_password(base: &Path, connection: &Connection, password: &str) -> Result<(), AppError> {
    if connection.kind != ConnectionKind::Rdp {
        return Ok(());
    }

    #[cfg(target_os = "windows")]
    {
        let _ = base;
        let target = rdp_windows_target(connection)?;
        let username = rdp_windows_username(connection)?;
        return windows_store_credential(&target, &username, password);
    }

    #[cfg(unix)]
    {
        save_password_keyring(base, connection, password)
    }

    #[cfg(not(any(target_os = "windows", unix)))]
    {
        let _ = (base, password);
        return Ok(());
    }
}

/// Delete the RDP password of `connection`; `base` as for [`save_password`].
pub fn delete_password(base: &Path, connection: &Connection) -> Result<(), AppError> {
    if connection.kind != ConnectionKind::Rdp {
        return Ok(());
    }

    #[cfg(target_os = "windows")]
    {
        let _ = base;
        let target = rdp_windows_target(connection)?;
        return windows_delete_credential(&target);
    }

    #[cfg(unix)]
    {
        delete_password_keyring(base, connection)
    }

    #[cfg(not(any(target_os = "windows", unix)))]
    {
        let _ = base;
        return Ok(());
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::ConnectionKind;
    #[cfg(unix)]
    use crate::workspace::{self, Workspace, WorkspaceId};

    /// An app data dir of its own for one test case under the system temp dir, gone with the
    /// guard.
    #[cfg(unix)]
    struct Scratch(std::path::PathBuf);

    #[cfg(unix)]
    impl Scratch {
        fn new(case: &str) -> Self {
            let dir =
                std::env::temp_dir().join(format!("ah-password-{case}-{}", std::process::id()));
            let _ = std::fs::remove_dir_all(&dir);
            std::fs::create_dir_all(&dir).unwrap();
            Self(dir)
        }
    }

    #[cfg(unix)]
    impl Drop for Scratch {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

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

    // The keyring tests up to R-0431 run in the migrated workspace, whose keys carry
    // no prefix: the key names in them are its keys.

    #[cfg(unix)]
    #[test]
    fn a_stored_password_belongs_to_one_connection() {
        let _keyring = crate::keyring_store::memory();
        let base = Scratch::new("one-connection");
        let _standard = workspace::enter(standard());
        let a = rdp_with_id("a");
        let b = rdp_with_id("b");
        save_password(&base.0, &a, "secret-a").unwrap();
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
        let _standard = workspace::enter(standard());
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
        let base = Scratch::new("key-wins");
        let _standard = workspace::enter(standard());
        let a = rdp_with_id("a");
        save_password(&base.0, &a, "new").unwrap();
        set(LEGACY_KEY, "old").unwrap();
        assert_eq!(load_password_keyring(&a).unwrap().as_deref(), Some("new"));
        assert_eq!(try_get(LEGACY_KEY).unwrap().as_deref(), Some("old"));
    }

    #[cfg(unix)]
    #[test]
    fn saving_writes_only_the_connection_key() {
        use crate::keyring_store::try_get;
        let _keyring = crate::keyring_store::memory();
        let base = Scratch::new("save-key-only");
        let _standard = workspace::enter(standard());
        save_password(&base.0, &rdp_with_id("a"), "secret").unwrap();
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
        let base = Scratch::new("delete-both");
        let _standard = workspace::enter(standard());
        let a = rdp_with_id("a");
        save_password(&base.0, &a, "new").unwrap();
        set(LEGACY_KEY, "old").unwrap();
        delete_password(&base.0, &a).unwrap();
        assert_eq!(try_get("rdp|a|host.com|3390|admin|corp").unwrap(), None);
        assert_eq!(try_get(LEGACY_KEY).unwrap(), None);
        assert!(!password_state(&a).unwrap().stored);
    }

    #[cfg(unix)]
    #[test]
    fn a_connection_without_a_key_stores_and_takes_over_nothing() {
        use crate::keyring_store::{set, try_get};
        let _keyring = crate::keyring_store::memory();
        let base = Scratch::new("no-key");
        let _standard = workspace::enter(standard());
        set(LEGACY_KEY, "old").unwrap();
        for id in ["", "a|b"] {
            let c = rdp_with_id(id);
            assert!(!password_state(&c).unwrap().stored, "{id:?}");
            assert_eq!(load_password_keyring(&c).unwrap(), None, "{id:?}");
            assert!(
                matches!(
                    save_password(&base.0, &c, "x"),
                    Err(AppError::Validation(_))
                ),
                "{id:?}"
            );
            delete_password(&base.0, &c).unwrap();
        }
        for key in [
            "rdp||host.com|3390|admin|corp",
            "rdp|a|b|host.com|3390|admin|corp",
        ] {
            assert_eq!(try_get(key).unwrap(), None, "{key}");
        }
        assert_eq!(try_get(LEGACY_KEY).unwrap().as_deref(), Some("old"));
    }

    /// Hosts that name this machine.
    #[cfg(unix)]
    const THIS_MACHINE: &[&str] = &[
        "127.0.0.1",
        "localhost",
        "LocalHost",
        "::1",
        "127.0.0.2",
        "[::1]",
        "::ffff:127.0.0.1",
        "[::ffff:127.0.0.1]",
        "0.0.0.0",
        "::",
        "localhost.",
        "LOCALHOST.",
        "app.localhost",
    ];

    /// The connection `a` to `host:3390` as `Admin` in `CORP`, its key and the
    /// legacy key of its target.
    #[cfg(unix)]
    fn rdp_to(host: &str) -> (Connection, String, String) {
        let connection = Connection {
            id: "a".into(),
            ..rdp(Some(host), Some(3390), Some("Admin"), Some("CORP"))
        };
        let target = format!("{}|3390|admin|corp", host.to_lowercase());
        (
            connection,
            format!("rdp|a|{target}"),
            format!("rdp|{target}"),
        )
    }

    // Connections of different servers can name the same target on this machine,
    // e.g. 127.0.0.1 and the same port, so a legacy entry for it may belong to
    // any of them.
    #[cfg(unix)]
    #[test]
    fn no_connection_takes_over_a_legacy_entry_for_this_machine() {
        use crate::keyring_store::{delete, set, try_get};
        let _keyring = crate::keyring_store::memory();
        let base = Scratch::new("this-machine");
        let _standard = workspace::enter(standard());
        for &host in THIS_MACHINE {
            let (c, key, legacy) = rdp_to(host);
            set(&legacy, "old").unwrap();
            assert!(!password_state(&c).unwrap().stored, "{host}");
            assert_eq!(load_password_keyring(&c).unwrap(), None, "{host}");
            assert_eq!(try_get(&key).unwrap(), None, "{host}");
            assert_eq!(try_get(&legacy).unwrap().as_deref(), Some("old"), "{host}");

            // The connection's own key still works for such a target.
            save_password(&base.0, &c, "new").unwrap();
            assert!(password_state(&c).unwrap().stored, "{host}");
            assert_eq!(
                load_password_keyring(&c).unwrap().as_deref(),
                Some("new"),
                "{host}"
            );
            assert_eq!(try_get(&legacy).unwrap().as_deref(), Some("old"), "{host}");
            delete(&key).unwrap();
        }
    }

    #[cfg(unix)]
    #[test]
    fn a_legacy_entry_for_another_host_is_still_taken_over() {
        use crate::keyring_store::{set, try_get};
        let _keyring = crate::keyring_store::memory();
        let _standard = workspace::enter(standard());
        for host in [
            "192.0.2.10",
            "2001:db8::1",
            "localhost.example.com",
            "127.example.com",
            "notlocalhost",
        ] {
            let (c, key, legacy) = rdp_to(host);
            set(&legacy, "old").unwrap();
            assert!(password_state(&c).unwrap().stored, "{host}");
            assert_eq!(
                load_password_keyring(&c).unwrap().as_deref(),
                Some("old"),
                "{host}"
            );
            assert_eq!(try_get(&key).unwrap().as_deref(), Some("old"), "{host}");
            assert_eq!(try_get(&legacy).unwrap(), None, "{host}");
        }
    }

    #[cfg(unix)]
    #[test]
    fn deleting_removes_a_legacy_entry_for_this_machine() {
        use crate::keyring_store::{set, try_get};
        let _keyring = crate::keyring_store::memory();
        let base = Scratch::new("delete-this-machine");
        let _standard = workspace::enter(standard());
        for &host in THIS_MACHINE {
            let (c, _, legacy) = rdp_to(host);
            set(&legacy, "old").unwrap();
            delete_password(&base.0, &c).unwrap();
            assert_eq!(try_get(&legacy).unwrap(), None, "{host}");
        }
    }

    // ── R-0431: RDP passwords per workspace ────────────────────────────────

    /// A migrated workspace: its keys carry no prefix, as before workspaces.
    #[cfg(unix)]
    fn standard() -> Workspace {
        Workspace {
            id: WorkspaceId::parse("standard").unwrap(),
            name: "Standard".to_string(),
            legacy_keys: true,
        }
    }

    /// A workspace created after the migration: its keys carry its id.
    #[cfg(unix)]
    fn created(id: &str) -> Workspace {
        Workspace {
            id: WorkspaceId::parse(id).unwrap(),
            name: id.to_string(),
            legacy_keys: false,
        }
    }

    /// The key of the connection `a` in the migrated workspace, as desktop-hardening stored it.
    #[cfg(unix)]
    const STANDARD_KEY: &str = "rdp|a|host.com|3390|admin|corp";

    #[cfg(unix)]
    #[test]
    fn workspace_keys_standard_keeps_its_keys_and_takes_over_a_legacy_entry() {
        use crate::keyring_store::{set, try_get};
        let _keyring = crate::keyring_store::memory();
        let base = Scratch::new("ws-standard");
        let _standard = workspace::enter(standard());
        let a = rdp_with_id("a");

        set(LEGACY_KEY, "old").unwrap();
        assert!(password_state(&a).unwrap().stored);
        assert_eq!(load_password_keyring(&a).unwrap().as_deref(), Some("old"));
        assert_eq!(try_get(STANDARD_KEY).unwrap().as_deref(), Some("old"));
        assert_eq!(try_get(LEGACY_KEY).unwrap(), None);

        save_password(&base.0, &a, "new").unwrap();
        assert_eq!(try_get(STANDARD_KEY).unwrap().as_deref(), Some("new"));
    }

    #[cfg(unix)]
    #[test]
    fn workspace_keys_two_new_workspaces_keep_their_rdp_passwords_apart() {
        use crate::keyring_store::try_get;
        let _keyring = crate::keyring_store::memory();
        let base = Scratch::new("ws-two");
        let a = rdp_with_id("a");
        let first = created("w-0a1b2c3d");
        let first_key = format!("{}{STANDARD_KEY}", first.keyring_prefix());
        {
            let _first = workspace::enter(first);
            save_password(&base.0, &a, "first").unwrap();
            assert!(password_state(&a).unwrap().stored);
        }
        assert_eq!(try_get(&first_key).unwrap().as_deref(), Some("first"));
        assert_eq!(try_get(STANDARD_KEY).unwrap(), None);

        // The same connection id in another workspace, e.g. the same server twice.
        let _second = workspace::enter(created("w-4e5f6a7b"));
        assert!(!password_state(&a).unwrap().stored);
        assert_eq!(load_password_keyring(&a).unwrap(), None);
        save_password(&base.0, &a, "second").unwrap();
        assert_eq!(
            load_password_keyring(&a).unwrap().as_deref(),
            Some("second")
        );
        delete_password(&base.0, &a).unwrap();
        assert_eq!(try_get(&first_key).unwrap().as_deref(), Some("first"));
    }

    // A new workspace has no entries from before workspaces: those of the migrated workspaces
    // stay theirs, whether under the old key or under the key with the connection id.
    #[cfg(unix)]
    #[test]
    fn workspace_keys_a_new_workspace_reads_and_deletes_no_key_of_the_migrated_ones() {
        use crate::keyring_store::{set, try_get};
        let _keyring = crate::keyring_store::memory();
        let base = Scratch::new("ws-no-legacy");
        set(LEGACY_KEY, "old").unwrap();
        set(STANDARD_KEY, "standard").unwrap();
        let _entered = workspace::enter(created("w-0a1b2c3d"));
        let a = rdp_with_id("a");

        assert!(!password_state(&a).unwrap().stored);
        assert_eq!(load_password_keyring(&a).unwrap(), None);
        delete_password(&base.0, &a).unwrap();

        assert_eq!(try_get(LEGACY_KEY).unwrap().as_deref(), Some("old"));
        assert_eq!(try_get(STANDARD_KEY).unwrap().as_deref(), Some("standard"));
    }

    #[cfg(unix)]
    #[test]
    fn workspace_keys_the_launcher_reads_and_writes_no_rdp_password() {
        use crate::keyring_store::{set, try_get};
        let _keyring = crate::keyring_store::memory();
        let base = Scratch::new("ws-launcher");
        set(LEGACY_KEY, "old").unwrap();
        set(STANDARD_KEY, "standard").unwrap();
        let a = rdp_with_id("a");

        assert!(password_state(&a).is_err());
        assert!(load_password_keyring(&a).is_err());
        assert!(save_password(&base.0, &a, "new").is_err());
        assert!(delete_password(&base.0, &a).is_err());

        // Nothing fell back to the keys without a prefix.
        assert_eq!(try_get(LEGACY_KEY).unwrap().as_deref(), Some("old"));
        assert_eq!(try_get(STANDARD_KEY).unwrap().as_deref(), Some("standard"));
    }

    /// The index of the RDP keys in the data dir of `workspace` under the app data dir `base`.
    #[cfg(unix)]
    fn index_path(base: &std::path::Path, workspace: &Workspace) -> std::path::PathBuf {
        workspace.data_dir(base).join("secrets.json")
    }

    #[cfg(unix)]
    fn index_of(path: &std::path::Path) -> serde_json::Value {
        serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
    }

    #[cfg(unix)]
    #[test]
    fn workspace_keys_the_index_lists_each_saved_key_until_it_is_deleted() {
        use std::os::unix::fs::PermissionsExt;
        let _keyring = crate::keyring_store::memory();
        let base = Scratch::new("ws-index");
        let workspace = created("w-0a1b2c3d");
        let prefix = workspace.keyring_prefix();
        let index = index_path(&base.0, &workspace);
        let _entered = workspace::enter(workspace);
        let (a, b) = (rdp_with_id("a"), rdp_with_id("b"));
        let key_a = format!("{prefix}{STANDARD_KEY}");
        let key_b = format!("{prefix}rdp|b|host.com|3390|admin|corp");

        save_password(&base.0, &b, "secret-b").unwrap();
        save_password(&base.0, &a, "secret-a").unwrap();
        save_password(&base.0, &a, "secret-a again").unwrap();

        assert_eq!(
            index_of(&index),
            serde_json::json!({ "keys": [key_a, key_b] })
        );
        assert!(!std::fs::read_to_string(&index).unwrap().contains("secret"));
        let mode = std::fs::metadata(&index).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o600);
        let names: Vec<_> = std::fs::read_dir(index.parent().unwrap())
            .unwrap()
            .map(|entry| entry.unwrap().file_name())
            .collect();
        assert_eq!(names, ["secrets.json"], "no temp file left");

        delete_password(&base.0, &a).unwrap();
        assert_eq!(index_of(&index), serde_json::json!({ "keys": [key_b] }));
        delete_password(&base.0, &a).unwrap();
        delete_password(&base.0, &b).unwrap();
        assert_eq!(index_of(&index), serde_json::json!({ "keys": [] }));
    }

    #[cfg(unix)]
    #[test]
    fn workspace_keys_each_workspace_keeps_its_own_index() {
        let _keyring = crate::keyring_store::memory();
        let base = Scratch::new("ws-index-own");
        let a = rdp_with_id("a");
        let created = created("w-0a1b2c3d");
        let created_key = format!("{}{STANDARD_KEY}", created.keyring_prefix());
        let created_index = index_path(&base.0, &created);
        let standard_index = index_path(&base.0, &standard());
        {
            let _standard = workspace::enter(standard());
            save_password(&base.0, &a, "standard").unwrap();
        }
        let _created = workspace::enter(created);
        save_password(&base.0, &a, "created").unwrap();

        assert_eq!(
            index_of(&standard_index),
            serde_json::json!({ "keys": [STANDARD_KEY] })
        );
        assert_eq!(
            index_of(&created_index),
            serde_json::json!({ "keys": [created_key] })
        );
    }

    // A key in the keyring that the index does not name would outlive the deletion of its
    // workspace, so the name goes first.
    #[cfg(unix)]
    #[test]
    fn workspace_keys_the_index_names_the_key_before_the_password_is_written() {
        let base = Scratch::new("ws-index-first");
        let workspace = created("w-0a1b2c3d");
        let key = format!("{}{STANDARD_KEY}", workspace.keyring_prefix());
        let index = index_path(&base.0, &workspace);
        let _entered = workspace::enter(workspace);

        // Without a keyring guard every write fails, as a locked keyring would.
        assert!(save_password(&base.0, &rdp_with_id("a"), "secret").is_err());

        assert_eq!(index_of(&index), serde_json::json!({ "keys": [key] }));
    }

    #[cfg(unix)]
    #[test]
    fn workspace_keys_a_broken_index_stores_no_password() {
        use crate::keyring_store::try_get;
        let _keyring = crate::keyring_store::memory();
        let base = Scratch::new("ws-index-broken");
        let workspace = created("w-0a1b2c3d");
        let key = format!("{}{STANDARD_KEY}", workspace.keyring_prefix());
        let index = index_path(&base.0, &workspace);
        std::fs::create_dir_all(index.parent().unwrap()).unwrap();
        std::fs::write(&index, "{not json").unwrap();
        let _entered = workspace::enter(workspace);

        assert!(save_password(&base.0, &rdp_with_id("a"), "secret").is_err());

        assert_eq!(try_get(&key).unwrap(), None);
        assert_eq!(std::fs::read_to_string(&index).unwrap(), "{not json");
    }

    #[cfg(unix)]
    #[test]
    fn workspace_keys_neither_the_launcher_nor_a_delete_without_a_key_writes_an_index() {
        let _keyring = crate::keyring_store::memory();
        let base = Scratch::new("ws-index-none");
        let a = rdp_with_id("a");

        assert!(save_password(&base.0, &a, "secret").is_err());
        assert!(delete_password(&base.0, &a).is_err());
        let _entered = workspace::enter(created("w-0a1b2c3d"));
        delete_password(&base.0, &a).unwrap();

        assert_eq!(std::fs::read_dir(&base.0).unwrap().count(), 0);
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
