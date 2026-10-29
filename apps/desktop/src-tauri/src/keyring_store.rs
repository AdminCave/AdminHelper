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
//! layer). The RDP passwords live here on Windows as well (R-0431); only for a
//! start of `mstsc.exe` does `password` write a `TERMSRV/` entry of its own,
//! which mstsc reads, and removes it after the start (`password::termsrv_plan`).
//!
//! In tests, [`memory`] switches this thread's keyring to an empty map for as long
//! as its guard lives (R-0294). Without the guard a test build answers like a
//! platform without a store (`set` fails, `get` and `try_get` find nothing, `delete`
//! succeeds), so no test reaches the OS store (R-0327).

use crate::error::AppError;

/// Credential-store service/collection every app secret lives under.
pub const SERVICE: &str = "com.admincave.adminhelper";

/// Why `set` fails in a test that took no [`memory`] guard.
const NO_KEYRING_IN_TESTS: &str = "no keyring in tests: take keyring_store::memory()";

/// Store a secret under `key`.
pub fn set(key: &str, value: &str) -> Result<(), AppError> {
    #[cfg(test)]
    if memory_backend::with(|m| {
        m.insert(key.to_string(), value.to_string());
    })
    .is_some()
    {
        return Ok(());
    }
    if cfg!(test) {
        return Err(AppError::Keyring(NO_KEYRING_IN_TESTS.to_string()));
    }
    os_set(key, value)
}

/// Read a stored secret, or `None` if absent or the store is unavailable (see
/// [`os_get`] for why errors degrade to `None`).
pub fn get(key: &str) -> Option<String> {
    #[cfg(test)]
    if let Some(value) = memory_backend::with(|m| m.get(key).cloned()) {
        return value;
    }
    if cfg!(test) {
        return None;
    }
    os_get(key)
}

/// Like [`get`], but a real read failure is an `Err` (see [`os_try_get`]).
pub fn try_get(key: &str) -> Result<Option<String>, AppError> {
    #[cfg(test)]
    if let Some(value) = memory_backend::with(|m| m.get(key).cloned()) {
        return Ok(value);
    }
    if cfg!(test) {
        return Ok(None);
    }
    os_try_get(key)
}

/// Delete a stored secret; a missing entry is success (see [`os_delete`]).
pub fn delete(key: &str) -> Result<(), AppError> {
    #[cfg(test)]
    if memory_backend::with(|m| {
        m.remove(key);
    })
    .is_some()
    {
        return Ok(());
    }
    if cfg!(test) {
        return Ok(());
    }
    os_delete(key)
}

/// While the guard lives, this thread's keyring is a map in memory, empty at the
/// start; dropping the guard throws it away and switches back to no store. One
/// thread, one map: each `#[test]` and each current-thread `#[tokio::test]` has its
/// own, so tests share nothing.
#[cfg(test)]
pub fn memory() -> MemoryKeyring {
    memory_backend::switch(true);
    MemoryKeyring(())
}

/// The guard of [`memory`].
#[cfg(test)]
#[must_use = "the in-memory keyring lasts as long as its guard"]
pub struct MemoryKeyring(());

#[cfg(test)]
impl Drop for MemoryKeyring {
    fn drop(&mut self) {
        memory_backend::switch(false);
    }
}

#[cfg(test)]
mod memory_backend {
    use std::cell::RefCell;
    use std::collections::HashMap;

    thread_local! {
        static STORE: RefCell<Option<HashMap<String, String>>> = const { RefCell::new(None) };
    }

    /// Run `f` on this thread's map, or `None` when no guard is alive.
    pub(super) fn with<R>(f: impl FnOnce(&mut HashMap<String, String>) -> R) -> Option<R> {
        STORE.with(|store| store.borrow_mut().as_mut().map(f))
    }

    pub(super) fn switch(on: bool) {
        STORE.with(|store| *store.borrow_mut() = on.then(HashMap::new));
        EPOCH.with(|epoch| epoch.set(epoch.get() + 1));
    }

    thread_local! {
        static EPOCH: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    }

    pub(super) fn epoch() -> u64 {
        EPOCH.with(|epoch| epoch.get())
    }
}

/// Which in-memory keyring this thread has: it changes with every [`memory`] guard, so a
/// cache of keyring contents (the held device identity) can tell a test's keyring from the
/// one of an earlier test on the same thread.
#[cfg(test)]
pub fn memory_epoch() -> u64 {
    memory_backend::epoch()
}

#[cfg(unix)]
fn os_set(key: &str, value: &str) -> Result<(), AppError> {
    use keyring::Entry;
    Entry::new(SERVICE, key)
        .and_then(|entry| entry.set_password(value))
        .map_err(|e| AppError::Keyring(e.to_string()))
}

#[cfg(target_os = "windows")]
fn os_set(key: &str, value: &str) -> Result<(), AppError> {
    crate::password::windows_store_credential(key, "adminhelper", value)
}

#[cfg(not(any(unix, target_os = "windows")))]
fn os_set(_key: &str, _value: &str) -> Result<(), AppError> {
    Err(AppError::Keyring("Plattform nicht unterstützt".to_string()))
}

/// Read a stored secret, or `None` if absent or the store is unavailable. Errors
/// degrade to `None` on purpose — callers treat "no value" and "cannot read"
/// alike ("not enrolled" for the identity).
#[cfg(unix)]
fn os_get(key: &str) -> Option<String> {
    use keyring::Entry;
    Entry::new(SERVICE, key).ok()?.get_password().ok()
}

#[cfg(target_os = "windows")]
fn os_get(key: &str) -> Option<String> {
    crate::password::windows_read_credential(key)
        .ok()
        .filter(|v| !v.is_empty())
}

#[cfg(not(any(unix, target_os = "windows")))]
fn os_get(_key: &str) -> Option<String> {
    None
}

/// Like [`get`], but distinguishes a genuine "no entry" (`Ok(None)`, first use)
/// from a real read failure (`Err`) — a locked/unavailable store (locked login
/// keyring, D-Bus hang) must NOT masquerade as "no value" to a security check that
/// fails open on `None` (the TOFU pin capture, 3.60).
#[cfg(unix)]
fn os_try_get(key: &str) -> Result<Option<String>, AppError> {
    use keyring::{Entry, Error as KeyringError};
    let entry = Entry::new(SERVICE, key).map_err(|e| AppError::Keyring(e.to_string()))?;
    match entry.get_password() {
        Ok(v) => Ok(Some(v)),
        Err(KeyringError::NoEntry) => Ok(None),
        Err(e) => Err(AppError::Keyring(e.to_string())),
    }
}

#[cfg(target_os = "windows")]
fn os_try_get(key: &str) -> Result<Option<String>, AppError> {
    // CredReadW reports a missing entry as ERROR_NOT_FOUND, which is "no entry"; any
    // other failure is an `Err`. An empty value counts as no entry, as in `os_get`.
    Ok(crate::password::windows_try_read_credential(key)?.filter(|v| !v.is_empty()))
}

#[cfg(not(any(unix, target_os = "windows")))]
fn os_try_get(_key: &str) -> Result<Option<String>, AppError> {
    Ok(None)
}

/// Delete a stored secret. A missing entry is success; a real store error
/// propagates so callers that care (session logout) can surface it.
#[cfg(unix)]
fn os_delete(key: &str) -> Result<(), AppError> {
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
fn os_delete(key: &str) -> Result<(), AppError> {
    crate::password::windows_delete_credential(key)
}

#[cfg(not(any(unix, target_os = "windows")))]
fn os_delete(_key: &str) -> Result<(), AppError> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_memory_keyring_stores_reads_and_deletes() {
        let _keyring = memory();
        assert_eq!(get("a"), None);
        assert!(matches!(try_get("a"), Ok(None)));
        set("a", "1").unwrap();
        assert_eq!(get("a").as_deref(), Some("1"));
        assert_eq!(try_get("a").unwrap().as_deref(), Some("1"));
        delete("a").unwrap();
        assert_eq!(get("a"), None);
        // A missing entry is success, as in the OS store.
        delete("a").unwrap();
    }

    #[test]
    fn the_memory_keyring_is_empty_again_after_its_guard() {
        {
            let _keyring = memory();
            set("b", "2").unwrap();
        }
        // Dropping the guard switched back to no store.
        assert!(memory_backend::with(|_| ()).is_none());
        let _keyring = memory();
        assert_eq!(get("b"), None);
    }

    #[test]
    fn each_thread_has_its_own_memory_keyring() {
        let _keyring = memory();
        set("c", "main").unwrap();
        std::thread::spawn(|| {
            let _keyring = memory();
            assert_eq!(get("c"), None);
            set("c", "other").unwrap();
        })
        .join()
        .unwrap();
        assert_eq!(get("c").as_deref(), Some("main"));
    }

    #[test]
    fn without_a_guard_a_test_reaches_no_store() {
        assert!(set("d", "1").is_err());
        // The test build refuses, not a store that happens to be unreachable.
        assert!(matches!(set("d", "1"), Err(AppError::Keyring(m)) if m == NO_KEYRING_IN_TESTS));
        assert_eq!(get("d"), None);
        assert!(matches!(try_get("d"), Ok(None)));
        assert!(delete("d").is_ok());
    }

    /// A credential name no one has, of this run and this call only.
    #[cfg(target_os = "windows")]
    fn probe_key() -> String {
        static CALLS: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);
        let call = CALLS.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|elapsed| elapsed.as_nanos())
            .unwrap_or(0);
        format!(
            "adminhelper-keyring-probe-{}-{nanos}-{call}",
            std::process::id()
        )
    }

    /// Deletes the probe entry, also after a failed assertion.
    #[cfg(target_os = "windows")]
    struct ProbeEntry(String);

    #[cfg(target_os = "windows")]
    impl Drop for ProbeEntry {
        fn drop(&mut self) {
            let _ = crate::password::windows_delete_credential(&self.0);
        }
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn on_windows_try_get_finds_no_entry_where_there_is_none() {
        assert!(matches!(os_try_get(&probe_key()), Ok(None)));
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn on_windows_try_get_reads_a_stored_value() {
        let key = probe_key();
        let _entry = ProbeEntry(key.clone());
        crate::password::windows_store_credential(&key, "adminhelper", "pin ✓").unwrap();
        assert_eq!(os_try_get(&key).unwrap().as_deref(), Some("pin ✓"));
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn on_windows_only_not_found_is_no_entry_any_other_read_failure_is_an_error() {
        use windows::Win32::Foundation::{ERROR_NOT_FOUND, ERROR_NO_SUCH_LOGON_SESSION};

        let key = probe_key();
        let _entry = ProbeEntry(key.clone());
        crate::password::windows_store_credential(&key, "adminhelper", "pin").unwrap();
        {
            let _failing = crate::password::fail_cred_read(ERROR_NO_SUCH_LOGON_SESSION);
            let code = ERROR_NO_SUCH_LOGON_SESSION.0.to_string();
            assert!(matches!(
                os_try_get(&key),
                Err(AppError::Keyring(m)) if m.ends_with(&code)
            ));
        }
        {
            let _failing = crate::password::fail_cred_read(ERROR_NOT_FOUND);
            assert!(matches!(os_try_get(&key), Ok(None)));
        }
        // Without a guard the read reaches the Credential Manager again.
        assert_eq!(os_try_get(&key).unwrap().as_deref(), Some("pin"));
    }
}
