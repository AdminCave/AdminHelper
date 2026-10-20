// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::collections::BTreeSet;
use std::path::Path;
use std::sync::{Mutex, PoisonError};
use std::time::Duration;

use serde::{Deserialize, Serialize};

use crate::error::AppError;
use crate::models::{Connection, ConnectionKind, PasswordState};
use crate::validation::required;
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
fn legacy_password(connection: &Connection, legacy: &str) -> Result<Option<String>, AppError> {
    if targets_this_machine(connection) {
        return Ok(None);
    }
    crate::keyring_store::try_get(legacy)
}

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
static INDEX_LOCK: Mutex<()> = Mutex::new(());

/// Apply `change` to the index in `dir`, the data dir of a workspace, and write it
/// back if `change` says it changed.
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

/// How long the `TERMSRV/…` entry of a start of mstsc holds the stored password (R-0431).
/// A fixed time, not the end of mstsc: the global name serves only the start, and mstsc
/// may ask about the publisher or the certificate before it reads the entry. Deleted too
/// early, mstsc asks for the password. See "Windows-RDP: Ergebnis des Spikes" in
/// `docs/features/desktop-workspaces.md`.
#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
pub const TERMSRV_HOLD: Duration = Duration::from_secs(60);

/// In the comment of every `TERMSRV/…` entry a start writes: `CredWriteW` replaces a generic
/// entry of the same name, so a start writes over no entry without it, and a `Remove` deletes
/// none (Kevin 2026-10-20).
#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
pub const TERMSRV_MARKER: &str = "com.admincave.adminhelper: for one start of mstsc";

/// A step of a start of mstsc on Windows, by [`termsrv_plan`].
#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
#[derive(Debug, PartialEq, Eq)]
pub enum TermsrvStep {
    /// Delete the entry under this name, the generic one and the domain password mstsc
    /// saves itself, with or without the marker.
    Clear(String),
    /// A generic entry without the marker stays under this name, and mstsc takes it instead of
    /// the stored password; the log says so.
    Keep(String),
    /// Write the stored password under this name: generic, with the marker, for this logon
    /// session only.
    Write(String),
    /// Start mstsc.
    Launch,
    /// Delete the written entry once `after` has passed since the start; at once if mstsc did
    /// not start.
    Remove { target: String, after: Duration },
}

/// What the generic entry under the `TERMSRV/…` name of a start holds before it starts.
#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TermsrvEntry {
    /// No entry.
    Missing,
    /// One with the marker, left by a start that could not remove it, e.g. after a crash.
    Own,
    /// One without the marker: the user's own (`cmdkey`), or the stored password of a version
    /// before R-0431.
    Foreign,
}

#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
impl TermsrvEntry {
    /// The entry whose comment is `comment`; `None` is no entry.
    fn of(comment: Option<&str>) -> Self {
        match comment {
            None => Self::Missing,
            Some(TERMSRV_MARKER) => Self::Own,
            Some(_) => Self::Foreign,
        }
    }
}

/// The `TERMSRV/…` name of the address `host:port`, as this app has always named it: without
/// the port for 3389.
#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
pub fn termsrv_name(host: &str, port: u16) -> String {
    if port == 3389 {
        format!("TERMSRV/{host}")
    } else {
        format!("TERMSRV/{host}:{port}")
    }
}

/// Whether `host`, as the `.rdp` file of a start names it, may be this machine: a loopback or
/// unspecified address or `localhost` ([`crate::tunnel::host_is_loopback`]), also with a port in
/// the host (`host:port`, `[IPv6 address]:port`). A host the check cannot read counts as this
/// machine: deleting its entries costs a password prompt at most, keeping them may hand a
/// password to whatever listens here now.
#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
pub fn termsrv_this_machine(host: &str) -> bool {
    use crate::tunnel::{host_is_loopback, rdp_host_port};

    match host_is_loopback(host) {
        Some(this_machine) => this_machine,
        None => rdp_host_port(host)
            .and_then(|(host, _port)| host_is_loopback(host))
            .unwrap_or(true),
    }
}

/// What a start of mstsc does in the Credential Manager for the address `host:port` it connects
/// to, `loopback` if that may be this machine ([`termsrv_this_machine`]), `entry` being what the
/// generic entry under its name holds (it counts only for another target with a stored
/// password).
///
/// An entry for this machine goes first, in both types, under every name mstsc may look up and
/// whoever wrote it: a port here may lead to another server by now, and mstsc would send it the
/// password. Those names are both forms of the address in the `.rdp` file and, for a host that
/// carries a port (`host:port`, `[IPv6 address]:port`), those of the host part at either port.
/// An entry for another target stays, it may be the user's own: while one without the
/// marker is there, the start writes nothing and mstsc takes that one; one with the marker is
/// the rest of an earlier start and is written over. A stored password is there only for the
/// start.
#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
pub fn termsrv_plan(
    host: &str,
    port: u16,
    loopback: bool,
    entry: TermsrvEntry,
    stored_password: bool,
) -> Vec<TermsrvStep> {
    let target = termsrv_name(host, port);
    let mut steps = Vec::new();
    if loopback {
        // Which name mstsc looks up is not verified (spike, point 4), nor which of the two ports
        // it takes from `full address:s:<host>:<port>:<port>` (T8).
        let mut names = vec![format!("TERMSRV/{host}:{port}"), format!("TERMSRV/{host}")];
        if let Some((inner, in_host)) = crate::tunnel::rdp_host_port(host) {
            names.extend([
                termsrv_name(inner, in_host),
                termsrv_name(inner, port),
                format!("TERMSRV/{inner}"),
            ]);
        }
        for name in names {
            let clear = TermsrvStep::Clear(name);
            if !steps.contains(&clear) {
                steps.push(clear);
            }
        }
    }
    let write = stored_password && (loopback || entry != TermsrvEntry::Foreign);
    if stored_password && !write {
        steps.push(TermsrvStep::Keep(target.clone()));
    }
    if write {
        steps.push(TermsrvStep::Write(target.clone()));
    }
    steps.push(TermsrvStep::Launch);
    if write {
        steps.push(TermsrvStep::Remove {
            target,
            after: TERMSRV_HOLD,
        });
    }
    steps
}

/// The Credential Manager as a start of mstsc changes it ([`run_termsrv_plan`]).
#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
pub trait TermsrvStore {
    /// Delete the generic entry and the domain password under `target`, whoever wrote them.
    fn clear(&mut self, target: &str) -> Result<(), AppError>;
    /// Write the stored password under `target`: generic, with the marker, for this logon
    /// session only.
    fn write(&mut self, target: &str) -> Result<(), AppError>;
    /// Delete the entry under `target` if it is still the one this start wrote.
    fn remove(&mut self, target: &str) -> Result<(), AppError>;
    /// [`Self::remove`] once `after` has passed, or when the process ends before.
    fn remove_after(&mut self, target: &str, after: Duration);
}

/// Runs `steps` against `store`, `launch` starting mstsc. A step that fails ends the start
/// before mstsc runs; if mstsc does not start, the `Remove` steps run at once.
#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
pub fn run_termsrv_plan(
    steps: &[TermsrvStep],
    store: &mut impl TermsrvStore,
    launch: impl FnOnce() -> Result<(), AppError>,
) -> Result<(), AppError> {
    let mut launch = Some(launch);
    for step in steps {
        match step {
            TermsrvStep::Clear(target) => store.clear(target)?,
            TermsrvStep::Keep(target) => log::info!(
                "{target} holds an entry this app did not write; mstsc takes it, the stored \
                 password stays unused"
            ),
            TermsrvStep::Write(target) => store.write(target)?,
            TermsrvStep::Launch => {
                if let Err(e) = launch.take().map_or(Ok(()), |launch| launch()) {
                    for step in steps {
                        if let TermsrvStep::Remove { target, .. } = step {
                            if let Err(e) = store.remove(target) {
                                log::warn!("{target} stays until the logon session ends: {e}");
                            }
                        }
                    }
                    return Err(e);
                }
            }
            TermsrvStep::Remove { target, after } => store.remove_after(target, *after),
        }
    }
    Ok(())
}

/// An entry a start wrote: its name and the user it holds, which a `Remove` checks first.
#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
#[derive(Debug, Clone, PartialEq, Eq)]
struct WrittenTermsrv {
    target: String,
    username: String,
}

#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
impl WrittenTermsrv {
    /// Whether the generic entry under its name, with `comment` and `username`, may still be
    /// the one written: with the marker and for the same user. Any other is not this app's to
    /// delete.
    fn is(&self, comment: &str, username: &str) -> bool {
        TermsrvEntry::of(Some(comment)) == TermsrvEntry::Own && username == self.username
    }
}

/// The `Remove` steps of this process that are not due yet: the timer of a start takes its own,
/// the end of the process those left.
#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
struct PendingRemoves {
    next: u64,
    open: Vec<(u64, WrittenTermsrv)>,
}

#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
impl PendingRemoves {
    const fn new() -> Self {
        Self {
            next: 0,
            open: Vec::new(),
        }
    }

    /// Holds `written` until [`Self::take`] with the id this returns, or [`Self::take_all`].
    fn add(&mut self, written: WrittenTermsrv) -> u64 {
        let id = self.next;
        self.next += 1;
        self.open.push((id, written));
        id
    }

    /// The entry held under `id`, unless it was taken before.
    fn take(&mut self, id: u64) -> Option<WrittenTermsrv> {
        let at = self.open.iter().position(|(open, _)| *open == id)?;
        Some(self.open.remove(at).1)
    }

    fn take_all(&mut self) -> Vec<WrittenTermsrv> {
        self.open.drain(..).map(|(_, written)| written).collect()
    }
}

/// The generic `TERMSRV/<address>` of the connection as listed, under which versions before
/// R-0431 stored its RDP password on Windows. As with the key without the id
/// ([`rdp_storage_keys`]), only a migrated workspace has such an entry, and only a connection
/// with a key reads or deletes it.
#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
fn legacy_termsrv(workspace: &Workspace, connection: &Connection) -> Option<String> {
    let (_, legacy) = rdp_storage_keys(workspace, connection)?;
    legacy.map(|_| termsrv_name(&normalized(&connection.host), rdp_port(connection)))
}

/// [`legacy_termsrv`] where it counts as a stored password: not for an address on this machine,
/// whose entries a start deletes before mstsc runs.
#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
fn readable_legacy_termsrv(workspace: &Workspace, connection: &Connection) -> Option<String> {
    legacy_termsrv(workspace, connection)
        .filter(|_| !termsrv_this_machine(&normalized(&connection.host)))
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

/// The comment and the user of the generic credential `target`, `None` if there is none. A
/// value that is no valid UTF-16 reads as empty, so it is never the marker.
#[cfg(target_os = "windows")]
fn windows_generic_entry(target: &str) -> Result<Option<(String, String)>, AppError> {
    use std::ptr::null_mut;
    use windows::core::{PCWSTR, PWSTR};
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
    if !ok {
        let err = unsafe { GetLastError() };
        if err == ERROR_NOT_FOUND {
            return Ok(None);
        }
        return Err(AppError::Keyring(format!(
            "Credential Manager error: {}",
            err.0
        )));
    }
    let text = |value: PWSTR| {
        if value.is_null() {
            String::new()
        } else {
            unsafe { value.to_string() }.unwrap_or_default()
        }
    };
    let credential = unsafe { &*credential_ptr };
    let found = (text(credential.Comment), text(credential.UserName));
    unsafe { CredFree(credential_ptr as *const _) };
    Ok(Some(found))
}

/// Reads the secret stored under `target` by `windows_store_credential`. The
/// blob is the value encoded as UTF-16LE bytes (see `utf16_bytes`), so decode it
/// back the same way. Mirrors the `CredReadW`/`CredFree` pattern of
/// `windows_generic_entry`.
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
    use windows::Win32::Security::Credentials::CRED_PERSIST_LOCAL_MACHINE;

    windows_write_credential(target, username, password, CRED_PERSIST_LOCAL_MACHINE, None)
}

/// Writes `password` as the generic credential `target` of `username`, kept as long as
/// `persist` says, with `comment` if there is one.
#[cfg(target_os = "windows")]
fn windows_write_credential(
    target: &str,
    username: &str,
    password: &str,
    persist: windows::Win32::Security::Credentials::CRED_PERSIST,
    comment: Option<&str>,
) -> Result<(), AppError> {
    use windows::core::PWSTR;
    use windows::Win32::Foundation::GetLastError;
    use windows::Win32::Security::Credentials::{CredWriteW, CREDENTIALW, CRED_TYPE_GENERIC};

    let target_w = to_utf16_null(target);
    let username_w = to_utf16_null(username);
    let comment_w = comment.map(to_utf16_null);
    let mut secret_bytes = utf16_bytes(password);

    let mut credential = CREDENTIALW::default();
    credential.Type = CRED_TYPE_GENERIC;
    credential.TargetName = PWSTR(target_w.as_ptr() as *mut _);
    credential.UserName = PWSTR(username_w.as_ptr() as *mut _);
    if let Some(comment_w) = &comment_w {
        credential.Comment = PWSTR(comment_w.as_ptr() as *mut _);
    }
    credential.CredentialBlobSize = secret_bytes.len() as u32;
    credential.CredentialBlob = secret_bytes.as_mut_ptr();
    credential.Persist = persist;

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
    use windows::Win32::Security::Credentials::CRED_TYPE_GENERIC;

    windows_delete_credential_of(target, CRED_TYPE_GENERIC)
}

/// Deletes the credential `target` of the type `kind`; a missing one is no error.
#[cfg(target_os = "windows")]
fn windows_delete_credential_of(
    target: &str,
    kind: windows::Win32::Security::Credentials::CRED_TYPE,
) -> Result<(), AppError> {
    use windows::core::PCWSTR;
    use windows::Win32::Foundation::{GetLastError, ERROR_NOT_FOUND};
    use windows::Win32::Security::Credentials::CredDeleteW;

    let target_w = to_utf16_null(target);
    let ok = unsafe { CredDeleteW(PCWSTR(target_w.as_ptr()), kind, Some(0)) }.is_ok();
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

/// What the generic entry under the `TERMSRV/…` name `target` is to a start.
#[cfg(target_os = "windows")]
fn windows_termsrv_entry(target: &str) -> Result<TermsrvEntry, AppError> {
    let found = windows_generic_entry(target)?;
    Ok(TermsrvEntry::of(
        found.as_ref().map(|(comment, _)| comment.as_str()),
    ))
}

/// Deletes the entry a start wrote, if the generic entry under its name is still that one
/// ([`WrittenTermsrv::is`]); another one, or none, stays as it is.
#[cfg(target_os = "windows")]
fn windows_remove_termsrv(written: &WrittenTermsrv) -> Result<(), AppError> {
    match windows_generic_entry(&written.target)? {
        Some((comment, username)) if written.is(&comment, &username) => {
            windows_delete_credential(&written.target)
        }
        _ => Ok(()),
    }
}

#[cfg(target_os = "windows")]
static PENDING_REMOVES: Mutex<PendingRemoves> = Mutex::new(PendingRemoves::new());

/// Runs the `Remove` steps that are not due yet at once, as the process ends
/// (`RunEvent::Exit`) and their timers with it.
#[cfg(target_os = "windows")]
pub fn remove_pending_termsrv() {
    let open = PENDING_REMOVES
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
        .take_all();
    for written in open {
        if let Err(e) = windows_remove_termsrv(&written) {
            log::warn!("{} stays until the logon session ends: {e}", written.target);
        }
    }
}

/// The Credential Manager of this logon session for a start of mstsc as `username`, with the
/// stored `password`.
#[cfg(target_os = "windows")]
struct WindowsTermsrv<'a> {
    username: String,
    password: &'a str,
}

#[cfg(target_os = "windows")]
impl WindowsTermsrv<'_> {
    fn written(&self, target: &str) -> WrittenTermsrv {
        WrittenTermsrv {
            target: target.to_string(),
            username: self.username.clone(),
        }
    }
}

#[cfg(target_os = "windows")]
impl TermsrvStore for WindowsTermsrv<'_> {
    fn clear(&mut self, target: &str) -> Result<(), AppError> {
        use windows::Win32::Security::Credentials::{CRED_TYPE_DOMAIN_PASSWORD, CRED_TYPE_GENERIC};

        windows_delete_credential_of(target, CRED_TYPE_GENERIC)?;
        windows_delete_credential_of(target, CRED_TYPE_DOMAIN_PASSWORD)
    }

    fn write(&mut self, target: &str) -> Result<(), AppError> {
        use windows::Win32::Security::Credentials::CRED_PERSIST_SESSION;

        windows_write_credential(
            target,
            &self.username,
            self.password,
            CRED_PERSIST_SESSION,
            Some(TERMSRV_MARKER),
        )
    }

    fn remove(&mut self, target: &str) -> Result<(), AppError> {
        windows_remove_termsrv(&self.written(target))
    }

    fn remove_after(&mut self, target: &str, after: Duration) {
        let id = PENDING_REMOVES
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .add(self.written(target));
        std::thread::spawn(move || {
            std::thread::sleep(after);
            let due = PENDING_REMOVES
                .lock()
                .unwrap_or_else(PoisonError::into_inner)
                .take(id);
            if let Some(written) = due {
                if let Err(e) = windows_remove_termsrv(&written) {
                    log::warn!("{} stays until the logon session ends: {e}", written.target);
                }
            }
        });
    }
}

/// Starts mstsc through `launch` for the address `host:port` that the `.rdp` file of
/// `connection` names, as [`termsrv_plan`] says; `password` is the one stored for the
/// connection (R-0431).
#[cfg(target_os = "windows")]
pub fn start_mstsc(
    host: &str,
    port: u16,
    connection: &Connection,
    password: Option<&str>,
    launch: impl FnOnce() -> Result<(), AppError>,
) -> Result<(), AppError> {
    let password = password.filter(|password| !password.is_empty());
    let loopback = termsrv_this_machine(host);
    let username = match password {
        Some(_) => rdp_windows_username(connection)?,
        None => String::new(),
    };
    let entry = match password {
        Some(_) if !loopback => windows_termsrv_entry(&termsrv_name(host, port))?,
        _ => TermsrvEntry::Missing,
    };
    let steps = termsrv_plan(host, port, loopback, entry, password.is_some());
    let mut store = WindowsTermsrv {
        username,
        password: password.unwrap_or_default(),
    };
    run_termsrv_plan(&steps, &mut store, launch)
}

/// Whether a migrated workspace holds the password of a version before R-0431 for the
/// connection as listed: a generic entry without the marker ([`readable_legacy_termsrv`]).
#[cfg(target_os = "windows")]
fn legacy_termsrv_stored(connection: &Connection) -> Result<bool, AppError> {
    match readable_legacy_termsrv(&workspace::current()?, connection) {
        Some(target) => Ok(windows_termsrv_entry(&target)? == TermsrvEntry::Foreign),
        None => Ok(false),
    }
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
        return Ok(PasswordState {
            stored: password_stored_keyring(connection)? || legacy_termsrv_stored(connection)?,
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
/// index of the workspace's keys lies. On Windows, too, it goes to the keyring of the
/// app, never to a `TERMSRV/…` entry, which only a start writes (R-0431).
pub fn save_password(base: &Path, connection: &Connection, password: &str) -> Result<(), AppError> {
    if connection.kind != ConnectionKind::Rdp {
        return Ok(());
    }

    #[cfg(any(target_os = "windows", unix))]
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
        delete_password_keyring(base, connection)?;
        return match legacy_termsrv(&workspace::current()?, connection) {
            Some(target) => windows_delete_credential(&target),
            None => Ok(()),
        };
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
    use std::cell::RefCell;

    use super::TermsrvEntry::{Foreign, Missing, Own};
    use super::*;
    use crate::models::ConnectionKind;
    use crate::workspace::{self, Workspace, WorkspaceId};

    /// An app data dir of its own for one test case under the system temp dir, gone with the
    /// guard.
    struct Scratch(std::path::PathBuf);

    impl Scratch {
        fn new(case: &str) -> Self {
            let dir =
                std::env::temp_dir().join(format!("ah-password-{case}-{}", std::process::id()));
            let _ = std::fs::remove_dir_all(&dir);
            std::fs::create_dir_all(&dir).unwrap();
            Self(dir)
        }
    }

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
    fn standard() -> Workspace {
        Workspace {
            id: WorkspaceId::parse("standard").unwrap(),
            name: "Standard".to_string(),
            legacy_keys: true,
        }
    }

    /// A workspace created after the migration: its keys carry its id.
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
    fn index_path(base: &std::path::Path, workspace: &Workspace) -> std::path::PathBuf {
        workspace.data_dir(base).join("secrets.json")
    }

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

    // ── R-0431: TERMSRV just in time for mstsc ─────────────────────────────

    /// Another target and this machine, both at port 3390 in the plans below.
    const ELSEWHERE: &str = "192.0.2.10";
    const HERE: &str = "127.0.0.1";

    /// The steps named in `steps` for `host` at port 3390; `clear` stands for both names.
    fn termsrv_steps(host: &str, steps: &[&str]) -> Vec<TermsrvStep> {
        let target = format!("TERMSRV/{host}:3390");
        steps
            .iter()
            .flat_map(|&step| match step {
                "clear" => vec![
                    TermsrvStep::Clear(target.clone()),
                    TermsrvStep::Clear(format!("TERMSRV/{host}")),
                ],
                "keep" => vec![TermsrvStep::Keep(target.clone())],
                "write" => vec![TermsrvStep::Write(target.clone())],
                "launch" => vec![TermsrvStep::Launch],
                "remove" => vec![TermsrvStep::Remove {
                    target: target.clone(),
                    after: TERMSRV_HOLD,
                }],
                other => panic!("no step {other}"),
            })
            .collect()
    }

    #[test]
    fn termsrv_plan_holds_a_stored_password_only_for_the_start() {
        assert_eq!(
            termsrv_plan(ELSEWHERE, 3390, false, Missing, true),
            termsrv_steps(ELSEWHERE, &["write", "launch", "remove"])
        );
    }

    // An entry for another target may be the user's own; mstsc uses it as before.
    #[test]
    fn termsrv_plan_without_a_password_leaves_the_entry_of_another_target() {
        for entry in [Missing, Own, Foreign] {
            assert_eq!(
                termsrv_plan(ELSEWHERE, 3390, false, entry, false),
                termsrv_steps(ELSEWHERE, &["launch"]),
                "{entry:?}"
            );
        }
    }

    // A port on this machine may lead to another server than when its entry was written,
    // and mstsc would send that server the password.
    #[test]
    fn termsrv_plan_clears_the_entry_for_this_machine_even_without_a_password() {
        assert_eq!(
            termsrv_plan(HERE, 3390, true, Missing, false),
            termsrv_steps(HERE, &["clear", "launch"])
        );
    }

    // Whatever the entry under its name holds, with or without the marker, it goes first.
    #[test]
    fn termsrv_plan_clears_the_entry_for_this_machine_before_it_writes_the_password() {
        for entry in [Missing, Own, Foreign] {
            assert_eq!(
                termsrv_plan(HERE, 3390, true, entry, true),
                termsrv_steps(HERE, &["clear", "write", "launch", "remove"]),
                "{entry:?}"
            );
        }
    }

    // `CredWriteW` would replace it: the user's own entry (`cmdkey`) or the password of a
    // version before R-0431. mstsc takes that one.
    #[test]
    fn termsrv_plan_writes_over_no_entry_of_another_target_without_the_marker() {
        assert_eq!(
            termsrv_plan(ELSEWHERE, 3390, false, Foreign, true),
            termsrv_steps(ELSEWHERE, &["keep", "launch"])
        );
    }

    // The rest of a start that could not remove it, e.g. after a crash.
    #[test]
    fn termsrv_plan_writes_over_the_rest_of_an_earlier_start() {
        assert_eq!(
            termsrv_plan(ELSEWHERE, 3390, false, Own, true),
            termsrv_steps(ELSEWHERE, &["write", "launch", "remove"])
        );
    }

    // Which of the two names mstsc looks up for this machine is not verified, so both go, at
    // 3389 as well; the one written is the name this app has always used.
    #[test]
    fn termsrv_plan_at_the_default_port_writes_the_name_without_it_and_clears_both() {
        assert_eq!(
            termsrv_plan("localhost", 3389, true, Missing, true),
            vec![
                TermsrvStep::Clear("TERMSRV/localhost:3389".to_string()),
                TermsrvStep::Clear("TERMSRV/localhost".to_string()),
                TermsrvStep::Write("TERMSRV/localhost".to_string()),
                TermsrvStep::Launch,
                TermsrvStep::Remove {
                    target: "TERMSRV/localhost".to_string(),
                    after: TERMSRV_HOLD,
                },
            ]
        );
    }

    /// The plans for the RDP host `127.0.0.1:6000` at `port`, with and without a stored
    /// password, against the names `clear` of the entries they delete first.
    fn assert_plans_of_a_host_with_a_port(port: u16, clear: &[&str]) {
        let target = termsrv_name("127.0.0.1:6000", port);
        let cleared = || {
            clear
                .iter()
                .map(|name| TermsrvStep::Clear(name.to_string()))
        };
        let with_password: Vec<_> = cleared()
            .chain([
                TermsrvStep::Write(target.clone()),
                TermsrvStep::Launch,
                TermsrvStep::Remove {
                    target: target.clone(),
                    after: TERMSRV_HOLD,
                },
            ])
            .collect();
        let without: Vec<_> = cleared().chain([TermsrvStep::Launch]).collect();
        assert_eq!(
            termsrv_plan("127.0.0.1:6000", port, true, Missing, true),
            with_password
        );
        assert_eq!(
            termsrv_plan("127.0.0.1:6000", port, true, Missing, false),
            without
        );
    }

    // mstsc gets `full address:s:127.0.0.1:6000:3390`: which of the two ports it takes is not
    // verified (T8), nor under which name it looks up (spike, point 4), so the names of the host
    // part at either port go as well.
    #[test]
    fn termsrv_plan_clears_the_names_of_a_host_with_a_port_at_either_port() {
        assert_plans_of_a_host_with_a_port(
            3390,
            &[
                "TERMSRV/127.0.0.1:6000:3390",
                "TERMSRV/127.0.0.1:6000",
                "TERMSRV/127.0.0.1:3390",
                "TERMSRV/127.0.0.1",
            ],
        );
    }

    // At 3389 the name of the host part goes without the port, as `termsrv_name` has it.
    #[test]
    fn termsrv_plan_clears_the_names_of_a_host_with_a_port_at_the_default_port() {
        assert_plans_of_a_host_with_a_port(
            3389,
            &[
                "TERMSRV/127.0.0.1:6000:3389",
                "TERMSRV/127.0.0.1:6000",
                "TERMSRV/127.0.0.1",
            ],
        );
    }

    #[test]
    fn termsrv_name_omits_the_default_port() {
        assert_eq!(termsrv_name("srv", 3389), "TERMSRV/srv");
        assert_eq!(termsrv_name("srv", 3390), "TERMSRV/srv:3390");
    }

    // The host as it stands in the `.rdp` file: with a port in it, both ports may be the one
    // mstsc takes (as in `tunnel.rs`), and what the check cannot read may be this machine.
    #[test]
    fn termsrv_this_machine_reads_a_port_in_the_host_and_takes_what_it_cannot_read() {
        for host in [
            "127.0.0.1",
            "127.0.0.2",
            "127.1",
            "localhost",
            "LocalHost",
            "localhost.",
            "app.localhost",
            "::1",
            "[::1]",
            "::ffff:127.0.0.1",
            "0.0.0.0",
            "::",
            "127.0.0.1:6000",
            "localhost:6000",
            "[::1]:6000",
            "fe80::1%eth0",
            "user@192.0.2.10",
            "rdp.example.com:port",
        ] {
            assert!(termsrv_this_machine(host), "{host}");
        }
        for host in [
            "192.0.2.10",
            "rdp.example.com",
            "2001:db8::1",
            "[2001:db8::1]",
            "192.0.2.10:6000",
            "rdp.example.com:6000",
            "[2001:db8::1]:6000",
            "127.example.com",
            "notlocalhost",
        ] {
            assert!(!termsrv_this_machine(host), "{host}");
        }
    }

    #[test]
    fn termsrv_entry_is_own_only_with_the_marker() {
        assert_eq!(TermsrvEntry::of(None), Missing);
        assert_eq!(TermsrvEntry::of(Some(TERMSRV_MARKER)), Own);
        assert_eq!(TermsrvEntry::of(Some("")), Foreign);
        assert_eq!(TermsrvEntry::of(Some("com.admincave.adminhelper")), Foreign);
    }

    #[test]
    fn termsrv_remove_takes_only_the_entry_a_start_wrote_for_its_user() {
        let written = WrittenTermsrv {
            target: "TERMSRV/192.0.2.10:3390".to_string(),
            username: "CORP\\admin".to_string(),
        };
        assert!(written.is(TERMSRV_MARKER, "CORP\\admin"));
        // Written over by a start for another user.
        assert!(!written.is(TERMSRV_MARKER, "CORP\\other"));
        // The user's own, or one from before R-0431, even for the same user.
        assert!(!written.is("", "CORP\\admin"));
        assert!(!written.is("my server", "CORP\\admin"));
    }

    #[test]
    fn termsrv_pending_removes_go_once_by_their_timer_or_at_the_exit() {
        let written = |target: &str| WrittenTermsrv {
            target: target.to_string(),
            username: "u".to_string(),
        };
        let mut pending = PendingRemoves::new();
        let first = pending.add(written("TERMSRV/a"));
        let second = pending.add(written("TERMSRV/b"));
        let third = pending.add(written("TERMSRV/c"));

        assert_eq!(pending.take(second), Some(written("TERMSRV/b")));
        assert_eq!(pending.take(second), None, "a timer takes its own once");
        assert_eq!(
            pending.take_all(),
            [written("TERMSRV/a"), written("TERMSRV/c")]
        );
        // A timer that wakes after the exit finds nothing, not even a later start's entry
        // under the same name.
        let later = pending.add(written("TERMSRV/a"));
        assert_ne!(later, first);
        assert_eq!(pending.take(first), None);
        assert_eq!(pending.take(third), None);
        assert_eq!(pending.take_all(), [written("TERMSRV/a")]);
    }

    /// The Credential Manager of a start as a log of what it was told, failing at `failing`.
    struct Recorded<'a> {
        calls: &'a RefCell<Vec<String>>,
        failing: Option<&'static str>,
    }

    impl Recorded<'_> {
        fn call(&mut self, step: &'static str, target: &str) -> Result<(), AppError> {
            self.calls.borrow_mut().push(format!("{step} {target}"));
            if self.failing == Some(step) {
                Err(AppError::Keyring(format!("{step} fails")))
            } else {
                Ok(())
            }
        }
    }

    impl TermsrvStore for Recorded<'_> {
        fn clear(&mut self, target: &str) -> Result<(), AppError> {
            self.call("clear", target)
        }

        fn write(&mut self, target: &str) -> Result<(), AppError> {
            self.call("write", target)
        }

        fn remove(&mut self, target: &str) -> Result<(), AppError> {
            self.call("remove", target)
        }

        fn remove_after(&mut self, target: &str, after: Duration) {
            self.calls
                .borrow_mut()
                .push(format!("remove {target} after {}s", after.as_secs()));
        }
    }

    /// Runs `steps` against a store failing at `failing`, mstsc starting if `starts`: what the
    /// store was told, the start of mstsc in between, and the outcome.
    fn run(
        steps: &[TermsrvStep],
        failing: Option<&'static str>,
        starts: bool,
    ) -> (Vec<String>, Result<(), AppError>) {
        let calls = RefCell::new(Vec::new());
        let mut store = Recorded {
            calls: &calls,
            failing,
        };
        let outcome = run_termsrv_plan(steps, &mut store, || {
            calls.borrow_mut().push("launch".to_string());
            if starts {
                Ok(())
            } else {
                Err(AppError::Connection("mstsc does not start".to_string()))
            }
        });
        (calls.into_inner(), outcome)
    }

    #[test]
    fn termsrv_run_holds_the_written_entry_until_its_time() {
        let (calls, outcome) = run(&termsrv_plan(HERE, 3390, true, Missing, true), None, true);
        assert!(outcome.is_ok(), "{outcome:?}");
        assert_eq!(
            calls,
            [
                "clear TERMSRV/127.0.0.1:3390",
                "clear TERMSRV/127.0.0.1",
                "write TERMSRV/127.0.0.1:3390",
                "launch",
                "remove TERMSRV/127.0.0.1:3390 after 60s",
            ]
        );
    }

    #[test]
    fn termsrv_run_removes_the_entry_at_once_if_mstsc_does_not_start() {
        let steps = termsrv_plan(ELSEWHERE, 3390, false, Missing, true);
        let (calls, outcome) = run(&steps, None, false);
        assert!(
            matches!(outcome, Err(AppError::Connection(_))),
            "{outcome:?}"
        );
        assert_eq!(
            calls,
            [
                "write TERMSRV/192.0.2.10:3390",
                "launch",
                "remove TERMSRV/192.0.2.10:3390"
            ]
        );

        // A removal that fails leaves the entry to the end of the logon session; the start
        // still reports why mstsc did not start.
        let (calls, outcome) = run(&steps, Some("remove"), false);
        assert!(
            matches!(outcome, Err(AppError::Connection(_))),
            "{outcome:?}"
        );
        assert_eq!(calls.last().unwrap(), "remove TERMSRV/192.0.2.10:3390");
    }

    // mstsc never runs while an entry for this machine may still be there, nor without the
    // one the start meant to write.
    #[test]
    fn termsrv_run_starts_no_mstsc_after_a_step_fails() {
        let steps = termsrv_plan(HERE, 3390, true, Missing, true);
        let (calls, outcome) = run(&steps, Some("clear"), true);
        assert!(matches!(outcome, Err(AppError::Keyring(_))), "{outcome:?}");
        assert_eq!(calls, ["clear TERMSRV/127.0.0.1:3390"]);

        let (calls, outcome) = run(&steps, Some("write"), true);
        assert!(matches!(outcome, Err(AppError::Keyring(_))), "{outcome:?}");
        assert_eq!(
            calls,
            [
                "clear TERMSRV/127.0.0.1:3390",
                "clear TERMSRV/127.0.0.1",
                "write TERMSRV/127.0.0.1:3390"
            ]
        );
    }

    #[test]
    fn termsrv_run_leaves_an_entry_without_the_marker_alone() {
        let (calls, outcome) = run(
            &termsrv_plan(ELSEWHERE, 3390, false, Foreign, true),
            None,
            true,
        );
        assert!(outcome.is_ok(), "{outcome:?}");
        assert_eq!(calls, ["launch"]);
    }

    #[test]
    fn termsrv_legacy_entry_only_in_a_migrated_workspace_and_for_a_connection_with_a_key() {
        let a = rdp_with_id("a");
        assert_eq!(
            legacy_termsrv(&standard(), &a).as_deref(),
            Some("TERMSRV/Host.COM:3390")
        );
        assert_eq!(
            readable_legacy_termsrv(&standard(), &a).as_deref(),
            Some("TERMSRV/Host.COM:3390")
        );
        let at_default_port = Connection {
            id: "a".into(),
            ..rdp(Some(" srv "), None, Some("u"), None)
        };
        assert_eq!(
            legacy_termsrv(&standard(), &at_default_port).as_deref(),
            Some("TERMSRV/srv")
        );

        assert_eq!(legacy_termsrv(&created("w-0a1b2c3d"), &a), None);
        for id in ["", "a|b"] {
            assert_eq!(
                legacy_termsrv(&standard(), &rdp_with_id(id)),
                None,
                "{id:?}"
            );
        }
    }

    // A start deletes the entries for this machine before mstsc runs, so such an entry is no
    // stored password; deleting the password still takes it.
    #[test]
    fn termsrv_legacy_entry_for_this_machine_is_no_stored_password() {
        for host in ["127.0.0.1", "localhost", "127.0.0.1:6000", "[::1]"] {
            let c = Connection {
                id: "a".into(),
                ..rdp(Some(host), Some(3390), Some("u"), None)
            };
            assert_eq!(
                legacy_termsrv(&standard(), &c),
                Some(format!("TERMSRV/{host}:3390")),
                "{host}"
            );
            assert_eq!(readable_legacy_termsrv(&standard(), &c), None, "{host}");
        }
    }

    /// A host no one has (`.invalid`, RFC 2606), of this run and this call only.
    #[cfg(target_os = "windows")]
    fn probe_host() -> String {
        static CALLS: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);
        let call = CALLS.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|elapsed| elapsed.as_nanos())
            .unwrap_or(0);
        format!(
            "adminhelper-probe-{}-{nanos}-{call}.invalid",
            std::process::id()
        )
    }

    /// A `TERMSRV/…` name no host has, of this run only.
    #[cfg(target_os = "windows")]
    fn probe_target() -> String {
        termsrv_name(&probe_host(), 3390)
    }

    /// Deletes the probe entry, also after a failed assertion.
    #[cfg(target_os = "windows")]
    struct ProbeEntry(String);

    #[cfg(target_os = "windows")]
    impl Drop for ProbeEntry {
        fn drop(&mut self) {
            let _ = windows_delete_credential(&self.0);
        }
    }

    /// Type, persistence and user of the generic credential `target`, as `CredReadW` reads them.
    #[cfg(target_os = "windows")]
    fn probe_read(
        target: &str,
    ) -> (
        windows::Win32::Security::Credentials::CRED_TYPE,
        windows::Win32::Security::Credentials::CRED_PERSIST,
        String,
    ) {
        use std::ptr::null_mut;
        use windows::core::PCWSTR;
        use windows::Win32::Security::Credentials::{
            CredFree, CredReadW, CREDENTIALW, CRED_TYPE_GENERIC,
        };

        let target_w = to_utf16_null(target);
        let mut credential_ptr: *mut CREDENTIALW = null_mut();
        unsafe {
            CredReadW(
                PCWSTR(target_w.as_ptr()),
                CRED_TYPE_GENERIC,
                Some(0),
                &mut credential_ptr,
            )
        }
        .unwrap();
        let credential = unsafe { &*credential_ptr };
        let user = if credential.UserName.is_null() {
            String::new()
        } else {
            unsafe { credential.UserName.to_string() }.unwrap()
        };
        let read = (credential.Type, credential.Persist, user);
        unsafe { CredFree(credential_ptr as *const _) };
        read
    }

    // The type and persistence of the spike under a `TERMSRV/<host>:<port>` name: the
    // Credential Manager takes, returns and deletes such an entry. Whether mstsc reads it
    // is not verified here.
    #[cfg(target_os = "windows")]
    #[test]
    fn termsrv_probe_a_generic_entry_of_this_logon_session_is_written_read_and_deleted() {
        use windows::Win32::Security::Credentials::{CRED_PERSIST_SESSION, CRED_TYPE_GENERIC};

        let target = probe_target();
        assert_eq!(windows_generic_entry(&target).unwrap(), None);
        let _entry = ProbeEntry(target.clone());

        windows_write_credential(
            &target,
            "CORP\\probe",
            "pässwort ✓",
            CRED_PERSIST_SESSION,
            None,
        )
        .unwrap();

        assert_eq!(
            windows_generic_entry(&target).unwrap(),
            Some((String::new(), "CORP\\probe".to_string()))
        );
        assert_eq!(
            probe_read(&target),
            (
                CRED_TYPE_GENERIC,
                CRED_PERSIST_SESSION,
                "CORP\\probe".to_string()
            )
        );
        assert_eq!(windows_read_credential(&target).unwrap(), "pässwort ✓");

        windows_delete_credential(&target).unwrap();
        assert_eq!(windows_generic_entry(&target).unwrap(), None);
        // A removal finds nothing once the entry is gone, and that is no error.
        windows_delete_credential(&target).unwrap();
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn termsrv_probe_a_start_removes_only_the_entry_it_wrote() {
        use windows::Win32::Security::Credentials::{CRED_PERSIST_SESSION, CRED_TYPE_GENERIC};

        let target = probe_target();
        let _entry = ProbeEntry(target.clone());
        let mut start = WindowsTermsrv {
            username: "CORP\\probe".to_string(),
            password: "pässwort ✓",
        };

        start.write(&target).unwrap();
        assert_eq!(
            windows_generic_entry(&target).unwrap(),
            Some((TERMSRV_MARKER.to_string(), "CORP\\probe".to_string()))
        );
        assert_eq!(windows_termsrv_entry(&target).unwrap(), Own);
        assert_eq!(
            probe_read(&target),
            (
                CRED_TYPE_GENERIC,
                CRED_PERSIST_SESSION,
                "CORP\\probe".to_string()
            )
        );
        assert_eq!(windows_read_credential(&target).unwrap(), "pässwort ✓");

        // The removal of a start for another user leaves it.
        WindowsTermsrv {
            username: "CORP\\other".to_string(),
            password: "",
        }
        .remove(&target)
        .unwrap();
        assert_eq!(windows_termsrv_entry(&target).unwrap(), Own);
        start.remove(&target).unwrap();
        assert_eq!(windows_termsrv_entry(&target).unwrap(), Missing);

        // An entry without the marker, as `cmdkey` writes it, stays even for the same user.
        windows_write_credential(&target, "CORP\\probe", "own", CRED_PERSIST_SESSION, None)
            .unwrap();
        start.remove(&target).unwrap();
        assert_eq!(windows_termsrv_entry(&target).unwrap(), Foreign);

        // A clear takes it whoever wrote it, and finds nothing of either type afterwards.
        start.clear(&target).unwrap();
        assert_eq!(windows_termsrv_entry(&target).unwrap(), Missing);
        start.clear(&target).unwrap();
    }

    /// The connection `a` to `host:3390` as `probe` in `CORP`.
    #[cfg(target_os = "windows")]
    fn probe_connection(host: &str) -> Connection {
        Connection {
            id: "a".into(),
            ..rdp(Some(host), Some(3390), Some("probe"), Some("CORP"))
        }
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn termsrv_probe_a_failed_start_removes_its_entry_at_once_a_running_one_at_the_exit() {
        let host = probe_host();
        let target = termsrv_name(&host, 3390);
        let _entry = ProbeEntry(target.clone());
        let connection = probe_connection(&host);

        let failed = start_mstsc(&host, 3390, &connection, Some("pässwort"), || {
            assert_eq!(windows_termsrv_entry(&target).unwrap(), Own);
            Err(AppError::Connection("mstsc does not start".to_string()))
        });
        assert!(matches!(failed, Err(AppError::Connection(_))), "{failed:?}");
        assert_eq!(windows_termsrv_entry(&target).unwrap(), Missing);

        start_mstsc(&host, 3390, &connection, Some("pässwort"), || Ok(())).unwrap();
        assert_eq!(windows_read_credential(&target).unwrap(), "pässwort");
        assert_eq!(windows_termsrv_entry(&target).unwrap(), Own);
        remove_pending_termsrv();
        assert_eq!(windows_termsrv_entry(&target).unwrap(), Missing);
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn termsrv_probe_a_start_writes_over_no_entry_without_the_marker() {
        use windows::Win32::Security::Credentials::CRED_PERSIST_SESSION;

        let host = probe_host();
        let target = termsrv_name(&host, 3390);
        let _entry = ProbeEntry(target.clone());
        windows_write_credential(&target, "CORP\\probe", "own", CRED_PERSIST_SESSION, None)
            .unwrap();

        start_mstsc(
            &host,
            3390,
            &probe_connection(&host),
            Some("stored"),
            || Ok(()),
        )
        .unwrap();

        assert_eq!(windows_read_credential(&target).unwrap(), "own");
        assert_eq!(windows_termsrv_entry(&target).unwrap(), Foreign);
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn workspace_keys_windows_the_password_lives_in_the_app_namespace() {
        use crate::keyring_store::try_get;
        let _keyring = crate::keyring_store::memory();
        let base = Scratch::new("windows-app-namespace");
        let workspace = created("w-0a1b2c3d");
        let index = index_path(&base.0, &workspace);
        let _entered = workspace::enter(workspace);
        let a = rdp_with_id("a");
        let key = "com.admincave.adminhelper/ws:w-0a1b2c3d|rdp|a|host.com|3390|admin|corp";

        assert!(!password_state(&a).unwrap().stored);
        save_password(&base.0, &a, "secret").unwrap();
        assert_eq!(try_get(key).unwrap().as_deref(), Some("secret"));
        assert_eq!(index_of(&index), serde_json::json!({ "keys": [key] }));
        assert!(password_state(&a).unwrap().stored);
        assert_eq!(
            load_password_keyring(&a).unwrap().as_deref(),
            Some("secret")
        );

        delete_password(&base.0, &a).unwrap();
        assert_eq!(try_get(key).unwrap(), None);
        assert_eq!(index_of(&index), serde_json::json!({ "keys": [] }));
        assert!(!password_state(&a).unwrap().stored);
    }

    // Before R-0431 the password stood in `TERMSRV/<address as listed>`; only a migrated
    // workspace counts it as stored, and deleting the password there takes it.
    #[cfg(target_os = "windows")]
    #[test]
    fn workspace_keys_windows_a_migrated_workspace_finds_and_deletes_the_entry_from_before() {
        use windows::Win32::Security::Credentials::CRED_PERSIST_SESSION;
        let _keyring = crate::keyring_store::memory();
        let base = Scratch::new("windows-legacy-termsrv");
        let host = probe_host();
        let target = termsrv_name(&host, 3390);
        let _entry = ProbeEntry(target.clone());
        let a = probe_connection(&host);
        let before = |password: &str, comment: Option<&str>| {
            windows_write_credential(
                &target,
                "CORP\\probe",
                password,
                CRED_PERSIST_SESSION,
                comment,
            )
            .unwrap()
        };
        before("old", None);

        {
            let _created = workspace::enter(created("w-0a1b2c3d"));
            assert!(!password_state(&a).unwrap().stored);
            delete_password(&base.0, &a).unwrap();
            assert_eq!(windows_termsrv_entry(&target).unwrap(), Foreign);
        }

        let _standard = workspace::enter(standard());
        assert!(password_state(&a).unwrap().stored);
        // An entry a start wrote is no password from before.
        before("jit", Some(TERMSRV_MARKER));
        assert!(!password_state(&a).unwrap().stored);
        before("old", None);
        delete_password(&base.0, &a).unwrap();
        assert_eq!(windows_termsrv_entry(&target).unwrap(), Missing);
        assert!(!password_state(&a).unwrap().stored);
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
