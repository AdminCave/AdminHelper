// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! The SFTP channel of a terminal session (R-1072): a child (`ssh` with the argv of
//! [`crate::connection::ssh::build_sftp_args`]) speaks the `sftp` subsystem on its stdin and
//! stdout. Every action starts its own child and ends it before it returns.

use std::collections::HashMap;
use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, MutexGuard, PoisonError};
use std::time::Duration;

use russh_sftp::client::SftpSession;
use russh_sftp::protocol::OpenFlags;
use serde::Serialize;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};
use tokio::process::{Child, ChildStderr, Command};
use tokio::task::JoinHandle;

use crate::error::AppError;

/// Bytes a transfer moves between two progress reports.
const STEP: u64 = 256 * 1024;

/// The tail of the child's stderr kept for an error message.
const STDERR_KEEP: usize = 4096;

/// The longest error message taken from the child's stderr.
const MESSAGE_MAX: usize = 512;

/// How long the child may take to end once its stdin is closed.
const EXIT_WAIT: Duration = Duration::from_secs(5);

/// How long an action waits for its session to sign in (R-1174).
pub const SIGN_IN_WAIT: Duration = Duration::from_secs(120);

/// How often an action looks for the connection of its session while it signs in.
pub const SIGN_IN_POLL: Duration = Duration::from_millis(250);

/// The program and argv of the SFTP channel from `channel`, once the session is signed in: an
/// argv over a ControlMaster socket waits until the socket is there, as OpenSSH creates it only
/// after the login (a child before that would sign in itself and fail under `BatchMode`).
/// `channel` is asked again each round, so a session that ends meanwhile ends the wait with its
/// error.
pub async fn wait_for_sign_in(
    mut channel: impl FnMut() -> Result<(PathBuf, Vec<String>), AppError>,
    wait: Duration,
    poll: Duration,
) -> Result<(PathBuf, Vec<String>), AppError> {
    let deadline = tokio::time::Instant::now() + wait;
    loop {
        let (program, args) = channel()?;
        let ready = match crate::connection::ssh::control_socket_of(&args) {
            None => true,
            Some(socket) => tokio::fs::try_exists(&socket).await.unwrap_or(false),
        };
        if ready {
            return Ok((program, args));
        }
        if tokio::time::Instant::now() >= deadline {
            return Err(AppError::Connection(
                "the session is not signed in yet; refresh once it is".to_string(),
            ));
        }
        tokio::time::sleep(poll).await;
    }
}

/// What a directory entry is; a symlink is not followed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum SftpKind {
    Dir,
    File,
    Link,
    Other,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SftpEntry {
    pub name: String,
    pub kind: SftpKind,
    pub size: u64,
}

/// A directory: its resolved path and its entries, folders first, `..` on top below `/`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SftpListing {
    pub path: String,
    pub entries: Vec<SftpEntry>,
}

/// Bytes done and bytes in all, reported in steps of [`STEP`] and once at the end.
pub type Progress<'a> = &'a mut (dyn FnMut(u64, u64) + Send);

pub async fn list(program: &OsStr, args: &[String], path: &str) -> Result<SftpListing, AppError> {
    let channel = Channel::open(program, args).await?;
    let result = channel.list(path).await;
    channel.finish(result).await
}

pub async fn mkdir(program: &OsStr, args: &[String], path: &str) -> Result<(), AppError> {
    let channel = Channel::open(program, args).await?;
    let result = channel
        .session
        .create_dir(path)
        .await
        .map_err(|e| Failure::Remote(e.to_string()));
    channel.finish(result).await
}

/// Uploads `local` into `remote_dir` under its own name. An existing file there is replaced only
/// with `overwrite`, else the upload fails with [`AppError::SftpExists`].
pub async fn upload(
    program: &OsStr,
    args: &[String],
    local: &Path,
    remote_dir: &str,
    overwrite: bool,
    progress: Progress<'_>,
) -> Result<(), AppError> {
    let channel = Channel::open(program, args).await?;
    let result = channel.upload(local, remote_dir, overwrite, progress).await;
    channel.finish(result).await
}

/// Downloads the file `remote` to `local`: written next to it first and renamed when complete,
/// so a failed download leaves `local` as it was.
pub async fn download(
    program: &OsStr,
    args: &[String],
    remote: &str,
    local: &Path,
    progress: Progress<'_>,
) -> Result<(), AppError> {
    let channel = Channel::open(program, args).await?;
    let result = channel.download(remote, local, progress).await;
    channel.finish(result).await
}

/// Files picked in the dialog or dropped on a window, for an upload.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SftpDrop {
    pub drop: u64,
    pub names: Vec<String>,
}

/// What an upload of picked files did: the files it wrote, and those it left as they existed.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SftpUploaded {
    pub drop: u64,
    pub uploaded: u32,
    pub existing: Vec<String>,
}

/// A step of a transfer, for the UI.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SftpTransfer {
    pub name: String,
    pub done: u64,
    pub total: u64,
}

/// The files picked or dropped last, per window, under a number that only grows: an upload
/// names the number, so a webview can upload nothing but what the user chose last.
#[derive(Default)]
pub struct Picks {
    next: AtomicU64,
    by_window: Mutex<HashMap<String, (u64, Vec<PathBuf>)>>,
}

impl Picks {
    /// Keeps `paths` as the pick of `window`, in place of the one before.
    pub fn put(&self, window: &str, paths: Vec<PathBuf>) -> SftpDrop {
        let drop = self.next.fetch_add(1, Ordering::Relaxed) + 1;
        let names = paths.iter().map(|path| name_of(path)).collect();
        lock(&self.by_window).insert(window.to_string(), (drop, paths));
        SftpDrop { drop, names }
    }

    /// The files of `drop` not uploaded yet: only the last pick of `window`, and only when each
    /// of them is a file.
    pub fn files(&self, window: &str, drop: u64) -> Result<Vec<PathBuf>, AppError> {
        let paths = match lock(&self.by_window).get(window) {
            Some((last, paths)) if *last == drop => paths.clone(),
            _ => {
                return Err(AppError::Validation(format!(
                    "the files of drop {drop} are gone; drop them again"
                )))
            }
        };
        if let Some(folder) = paths.iter().find(|path| !path.is_file()) {
            return Err(AppError::Validation(format!(
                "cannot upload {}: it is not a file",
                name_of(folder)
            )));
        }
        Ok(paths)
    }

    /// `path` of `drop` is uploaded.
    pub fn done(&self, window: &str, drop: u64, path: &Path) {
        if let Some((last, paths)) = lock(&self.by_window).get_mut(window) {
            if *last == drop {
                paths.retain(|kept| kept != path);
            }
        }
    }
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(PoisonError::into_inner)
}

/// The name a local file goes by in the UI.
pub fn name_of(path: &Path) -> String {
    path.file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_else(|| path.display().to_string())
}

/// The name a download is offered under: the last part of its remote path. The server names it,
/// so whatever a local file system reads as a separator or a drive, and control characters,
/// become `_`; nothing usable left is "download".
pub fn suggested_name(path: &str) -> String {
    let last = path.rsplit('/').find(|part| !part.is_empty()).unwrap_or("");
    let name: String = last
        .chars()
        .map(|c| {
            if c == '\\' || c == ':' || c.is_control() || is_bidi_control(c) {
                '_'
            } else {
                c
            }
        })
        .collect();
    if name.is_empty() || name == "." || name == ".." {
        "download".to_string()
    } else {
        name
    }
}

/// Why an action failed: on the server (its message, or the child's stderr when the child
/// ended), on this machine, or by a rule of its own.
enum Failure {
    Remote(String),
    Local(std::io::Error),
    App(AppError),
}

fn remote<E: std::fmt::Display>(err: E) -> Failure {
    Failure::Remote(err.to_string())
}

struct Channel {
    session: SftpSession,
    child: Child,
    stderr: JoinHandle<Vec<u8>>,
}

impl Channel {
    async fn open(program: &OsStr, args: &[String]) -> Result<Self, AppError> {
        let mut child = Command::new(program)
            .args(args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .map_err(|e| {
                AppError::Connection(format!(
                    "cannot start {}: {e}",
                    Path::new(program).display()
                ))
            })?;
        let (Some(stdin), Some(stdout), Some(stderr)) =
            (child.stdin.take(), child.stdout.take(), child.stderr.take())
        else {
            return Err(AppError::Connection("the SFTP child has no pipes".into()));
        };
        let stderr = tokio::spawn(tail(stderr));
        match SftpSession::new(tokio::io::join(stdout, stdin)).await {
            Ok(session) => Ok(Self {
                session,
                child,
                stderr,
            }),
            Err(err) => {
                let said = end(&mut child, stderr, true).await;
                Err(AppError::Connection(
                    said.unwrap_or_else(|| format!("SFTP: {err}")),
                ))
            }
        }
    }

    /// Ends the child and turns the result of the action into the answer.
    async fn finish<T>(mut self, result: Result<T, Failure>) -> Result<T, AppError> {
        // The child's stderr explains a failure only when the child ended with it; while it runs,
        // the server's answer does, and stderr holds at most warnings.
        let ended = matches!(self.child.try_wait(), Ok(Some(_)));
        let _ = self.session.close().await;
        drop(self.session);
        let said = end(&mut self.child, self.stderr, false).await;
        result.map_err(|failure| match failure {
            Failure::Remote(message) => {
                AppError::Connection(said.filter(|_| ended).unwrap_or(message))
            }
            Failure::Local(err) => AppError::Io(err),
            Failure::App(err) => err,
        })
    }

    async fn list(&self, path: &str) -> Result<SftpListing, Failure> {
        let resolved = self.session.canonicalize(path).await.map_err(remote)?;
        let mut entries: Vec<SftpEntry> = self
            .session
            .read_dir(resolved.as_str())
            .await
            .map_err(remote)?
            .map(|entry| {
                let file_type = entry.file_type();
                let kind = if file_type.is_dir() {
                    SftpKind::Dir
                } else if file_type.is_file() {
                    SftpKind::File
                } else if file_type.is_symlink() {
                    SftpKind::Link
                } else {
                    SftpKind::Other
                };
                SftpEntry {
                    name: entry.file_name(),
                    kind,
                    size: if kind == SftpKind::File {
                        entry.metadata().len()
                    } else {
                        0
                    },
                }
            })
            .collect();
        entries.sort_by(|a, b| {
            (a.kind != SftpKind::Dir)
                .cmp(&(b.kind != SftpKind::Dir))
                .then_with(|| a.name.cmp(&b.name))
        });
        if resolved != "/" {
            entries.insert(
                0,
                SftpEntry {
                    name: "..".into(),
                    kind: SftpKind::Dir,
                    size: 0,
                },
            );
        }
        Ok(SftpListing {
            path: resolved,
            entries,
        })
    }

    async fn upload(
        &self,
        local: &Path,
        remote_dir: &str,
        overwrite: bool,
        progress: Progress<'_>,
    ) -> Result<(), Failure> {
        let name = local.file_name().and_then(OsStr::to_str).ok_or_else(|| {
            Failure::App(AppError::Validation(format!(
                "cannot upload {}: the name is not plain text",
                local.display()
            )))
        })?;
        let mut source = tokio::fs::File::open(local).await.map_err(Failure::Local)?;
        let meta = source.metadata().await.map_err(Failure::Local)?;
        // A folder opens as well on Unix; it would only fail on the first read, after the target
        // on the server was created or emptied.
        if !meta.is_file() {
            return Err(Failure::App(AppError::Validation(format!(
                "cannot upload {}: it is not a file",
                local.display()
            ))));
        }
        let total = meta.len();
        let target_path = join(remote_dir, name);
        if !overwrite
            && self
                .session
                .try_exists(target_path.as_str())
                .await
                .map_err(remote)?
        {
            return Err(Failure::App(AppError::SftpExists(name.to_string())));
        }
        // EXCLUDE: a file created meanwhile is not replaced either.
        let flags = OpenFlags::WRITE
            | OpenFlags::CREATE
            | if overwrite {
                OpenFlags::TRUNCATE
            } else {
                OpenFlags::EXCLUDE
            };
        let mut target = self
            .session
            .open_with_flags(target_path, flags)
            .await
            .map_err(remote)?;
        pump(
            &mut source,
            &mut target,
            total,
            progress,
            Failure::Local,
            remote,
        )
        .await?;
        target.close().await.map_err(remote)
    }

    async fn download(
        &self,
        remote_path: &str,
        local: &Path,
        progress: Progress<'_>,
    ) -> Result<(), Failure> {
        let meta = self.session.metadata(remote_path).await.map_err(remote)?;
        if meta.is_dir() {
            return Err(Failure::App(AppError::Validation(format!(
                "{remote_path} is a folder"
            ))));
        }
        let mut source = self.session.open(remote_path).await.map_err(remote)?;
        let part = part_path(local).map_err(Failure::App)?;
        let result = async {
            let mut target = create_part(&part).await.map_err(Failure::Local)?;
            pump(
                &mut source,
                &mut target,
                meta.len(),
                progress,
                remote,
                Failure::Local,
            )
            .await?;
            target.sync_all().await.map_err(Failure::Local)?;
            drop(target);
            tokio::fs::rename(&part, local)
                .await
                .map_err(Failure::Local)
        }
        .await;
        if result.is_err() {
            let _ = tokio::fs::remove_file(&part).await;
        }
        let _ = source.close().await;
        result
    }
}

/// Copies `from` to `to` and reports the progress in steps.
async fn pump<R, W>(
    from: &mut R,
    to: &mut W,
    total: u64,
    progress: Progress<'_>,
    read_failed: fn(std::io::Error) -> Failure,
    write_failed: fn(std::io::Error) -> Failure,
) -> Result<(), Failure>
where
    R: AsyncRead + Unpin,
    W: AsyncWrite + Unpin,
{
    let mut buf = vec![0u8; STEP as usize];
    let mut done = 0u64;
    let mut reported = 0u64;
    progress(0, total);
    loop {
        let n = from.read(&mut buf).await.map_err(read_failed)?;
        if n == 0 {
            break;
        }
        to.write_all(&buf[..n]).await.map_err(write_failed)?;
        done += n as u64;
        if done - reported >= STEP {
            reported = done;
            progress(done, total.max(done));
        }
    }
    to.flush().await.map_err(write_failed)?;
    if reported != done || done == 0 {
        progress(done, total.max(done));
    }
    Ok(())
}

/// `name` in the remote folder `dir`.
fn join(dir: &str, name: &str) -> String {
    if dir.is_empty() {
        name.to_string()
    } else if dir.ends_with('/') {
        format!("{dir}{name}")
    } else {
        format!("{dir}/{name}")
    }
}

/// Where a download is written before it is complete: a hidden file next to `local`.
fn part_path(local: &Path) -> Result<PathBuf, AppError> {
    let name = local
        .file_name()
        .ok_or_else(|| AppError::Validation(format!("cannot save to {}", local.display())))?;
    let mut part = std::ffi::OsString::from(".");
    part.push(name);
    part.push(".ah-part");
    Ok(local.with_file_name(part))
}

/// The bidi controls a host could put into a name to make it read as another one (the set
/// `HIDDEN` in `FilesPanel.svelte` shows as a replacement character).
fn is_bidi_control(c: char) -> bool {
    matches!(c, '\u{061c}' | '\u{200e}' | '\u{200f}' | '\u{202a}'..='\u{202e}' | '\u{2066}'..='\u{2069}')
}

/// Creates the part file anew. Whatever already sits at its place (the rest of an aborted
/// download, or a link someone put there) is removed and never written through.
async fn create_part(part: &Path) -> std::io::Result<tokio::fs::File> {
    match create_new(part).await {
        Err(err) if err.kind() == std::io::ErrorKind::AlreadyExists => {
            tokio::fs::remove_file(part).await?;
            create_new(part).await
        }
        other => other,
    }
}

async fn create_new(path: &Path) -> std::io::Result<tokio::fs::File> {
    tokio::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .await
}

/// Reads stderr to its end and keeps its tail.
async fn tail(mut stderr: ChildStderr) -> Vec<u8> {
    let mut kept = Vec::new();
    let mut buf = [0u8; 1024];
    while let Ok(n) = stderr.read(&mut buf).await {
        if n == 0 {
            break;
        }
        kept.extend_from_slice(&buf[..n]);
        if kept.len() > 2 * STDERR_KEEP {
            kept.drain(..kept.len() - STDERR_KEEP);
        }
    }
    kept
}

/// Ends the child (`kill` at once, else after [`EXIT_WAIT`]) and returns the last line of its
/// stderr, cut to [`MESSAGE_MAX`] characters.
async fn end(child: &mut Child, stderr: JoinHandle<Vec<u8>>, kill: bool) -> Option<String> {
    if kill || tokio::time::timeout(EXIT_WAIT, child.wait()).await.is_err() {
        let _ = child.kill().await;
    }
    let text = tokio::time::timeout(EXIT_WAIT, stderr).await.ok()?.ok()?;
    let text = String::from_utf8_lossy(&text);
    let line = text.lines().map(str::trim).rfind(|l| !l.is_empty())?;
    Some(line.chars().take(MESSAGE_MAX).collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The tests against OpenSSH's sftp-server: the task asks them on Linux only, and the Windows
    /// runner has no such server.
    #[cfg(target_os = "linux")]
    mod with_server {
        use super::*;
        use sha2::{Digest, Sha256};

        /// OpenSSH's own server end of the subsystem: the tests run it in place of `ssh`.
        const SERVER: &str = "/usr/lib/openssh/sftp-server";

        /// A private folder that goes with the test.
        struct Scratch(PathBuf);

        impl Scratch {
            fn new() -> Self {
                Self(
                    crate::ansible::create_private_dir(&std::env::temp_dir(), "ah-sftp-test-")
                        .unwrap(),
                )
            }
        }

        impl Drop for Scratch {
            fn drop(&mut self) {
                let _ = std::fs::remove_dir_all(&self.0);
            }
        }

        /// The program and argv of a channel whose server starts in `dir`.
        fn server(dir: &Path) -> (&'static OsStr, Vec<String>) {
            assert!(
                Path::new(SERVER).exists(),
                "{SERVER} is missing: install openssh-sftp-server"
            );
            (
                OsStr::new(SERVER),
                vec!["-d".into(), dir.display().to_string()],
            )
        }

        fn sha(bytes: &[u8]) -> Vec<u8> {
            Sha256::digest(bytes).to_vec()
        }

        /// Bytes that are not one value repeated: 1.1 steps of progress and an odd tail.
        fn content() -> Vec<u8> {
            (0..(STEP as usize * 3 + 12345))
                .map(|i| (i * 31 % 251) as u8)
                .collect()
        }

        /// From 0 to `total`, at least one report between, each a step or more after the one before.
        fn in_steps(steps: &[(u64, u64)], total: u64) {
            assert_eq!(steps.first(), Some(&(0, total)), "{steps:?}");
            assert_eq!(steps.last(), Some(&(total, total)), "{steps:?}");
            assert!(steps.len() >= 3, "{steps:?}");
            assert!(
                steps[..steps.len() - 1]
                    .windows(2)
                    .all(|w| w[1].0 - w[0].0 >= STEP),
                "{steps:?}"
            );
            assert!(steps.windows(2).all(|w| w[0].0 < w[1].0), "{steps:?}");
        }

        #[tokio::test]
        async fn lists_folders_first_with_the_resolved_path_and_the_way_up() {
            let scratch = Scratch::new();
            let root = scratch.0.canonicalize().unwrap();
            std::fs::create_dir(root.join("zeta")).unwrap();
            std::fs::create_dir(root.join("alpha")).unwrap();
            std::fs::write(root.join("b.txt"), b"12345").unwrap();
            std::fs::write(root.join("a.txt"), b"").unwrap();
            #[cfg(unix)]
            std::os::unix::fs::symlink("b.txt", root.join("link")).unwrap();
            let (program, args) = server(&root);

            let listing = list(program, &args, ".").await.unwrap();
            assert_eq!(listing.path, root.display().to_string());
            let entries: Vec<_> = listing
                .entries
                .iter()
                .map(|e| (e.name.as_str(), e.kind, e.size))
                .collect();
            assert_eq!(
                entries,
                [
                    ("..", SftpKind::Dir, 0),
                    ("alpha", SftpKind::Dir, 0),
                    ("zeta", SftpKind::Dir, 0),
                    ("a.txt", SftpKind::File, 0),
                    ("b.txt", SftpKind::File, 5),
                    ("link", SftpKind::Link, 0),
                ]
            );

            let top = list(program, &args, "/").await.unwrap();
            assert_eq!(top.path, "/");
            assert!(top.entries.iter().all(|e| e.name != ".."));
        }

        #[tokio::test]
        async fn makes_a_folder_and_refuses_one_that_is_there() {
            let scratch = Scratch::new();
            let (program, args) = server(&scratch.0);
            mkdir(program, &args, "new").await.unwrap();
            assert!(scratch.0.join("new").is_dir());
            let err = mkdir(program, &args, "new").await.unwrap_err();
            assert_eq!(err.code(), "ERR_CONNECTION");
        }

        #[tokio::test]
        async fn uploads_and_downloads_a_file_unchanged_with_progress_in_steps() {
            let scratch = Scratch::new();
            let remote_dir = scratch.0.join("remote");
            std::fs::create_dir(&remote_dir).unwrap();
            let local = scratch.0.join("data.bin");
            let bytes = content();
            std::fs::write(&local, &bytes).unwrap();
            let (program, args) = server(&scratch.0);
            let total = bytes.len() as u64;

            let mut steps = Vec::new();
            upload(program, &args, &local, "remote", false, &mut |done, all| {
                steps.push((done, all))
            })
            .await
            .unwrap();
            assert_eq!(
                sha(&std::fs::read(remote_dir.join("data.bin")).unwrap()),
                sha(&bytes)
            );
            in_steps(&steps, total);

            let back = scratch.0.join("back.bin");
            let mut steps = Vec::new();
            download(
                program,
                &args,
                "remote/data.bin",
                &back,
                &mut |done, all| steps.push((done, all)),
            )
            .await
            .unwrap();
            assert_eq!(sha(&std::fs::read(&back).unwrap()), sha(&bytes));
            in_steps(&steps, total);
            assert!(!part_path(&back).unwrap().exists());
        }

        #[tokio::test]
        async fn replaces_a_file_only_when_asked() {
            let scratch = Scratch::new();
            let local = scratch.0.join("note.txt");
            std::fs::write(&local, b"new").unwrap();
            let remote_dir = scratch.0.join("remote");
            std::fs::create_dir(&remote_dir).unwrap();
            std::fs::write(remote_dir.join("note.txt"), b"old").unwrap();
            let (program, args) = server(&scratch.0);

            let err = upload(program, &args, &local, "remote/", false, &mut |_, _| {})
                .await
                .unwrap_err();
            assert_eq!(err.code(), "ERR_SFTP_EXISTS");
            assert!(err.to_string().contains("note.txt"), "{err}");
            assert_eq!(std::fs::read(remote_dir.join("note.txt")).unwrap(), b"old");

            upload(program, &args, &local, "remote/", true, &mut |_, _| {})
                .await
                .unwrap();
            assert_eq!(std::fs::read(remote_dir.join("note.txt")).unwrap(), b"new");
        }

        #[tokio::test]
        async fn a_failed_download_leaves_the_local_file_as_it_was() {
            let scratch = Scratch::new();
            std::fs::create_dir(scratch.0.join("folder")).unwrap();
            let local = scratch.0.join("keep.txt");
            std::fs::write(&local, b"mine").unwrap();
            let (program, args) = server(&scratch.0);

            for remote_path in ["missing.txt", "folder"] {
                let err = download(program, &args, remote_path, &local, &mut |_, _| {})
                    .await
                    .unwrap_err();
                assert!(!err.to_string().is_empty());
                assert_eq!(std::fs::read(&local).unwrap(), b"mine");
                assert!(!part_path(&local).unwrap().exists());
            }

            // Complete, but the rename onto a folder fails: the part file goes as well.
            std::fs::write(scratch.0.join("file.txt"), b"theirs").unwrap();
            let taken = scratch.0.join("taken");
            std::fs::create_dir(&taken).unwrap();
            std::fs::write(taken.join("inside"), b"mine").unwrap();
            download(program, &args, "file.txt", &taken, &mut |_, _| {})
                .await
                .unwrap_err();
            assert_eq!(std::fs::read(taken.join("inside")).unwrap(), b"mine");
            assert!(!part_path(&taken).unwrap().exists());
        }

        #[tokio::test]
        async fn refuses_to_upload_a_folder_before_touching_the_server() {
            let scratch = Scratch::new();
            let folder = scratch.0.join("folder");
            std::fs::create_dir(&folder).unwrap();
            let remote_dir = scratch.0.join("remote");
            std::fs::create_dir(&remote_dir).unwrap();
            std::fs::write(remote_dir.join("folder"), b"old").unwrap();
            let (program, args) = server(&scratch.0);

            let err = upload(program, &args, &folder, "remote/", true, &mut |_, _| {})
                .await
                .unwrap_err();
            assert_eq!(err.code(), "ERR_VALIDATION");
            assert_eq!(std::fs::read(remote_dir.join("folder")).unwrap(), b"old");
        }
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn a_child_that_cannot_connect_reports_its_last_stderr_line() {
        let args = [
            "-c".to_string(),
            "echo 'Warning: something' >&2; \
             echo 'ssh: connect to host h port 22: Connection refused' >&2; exit 255"
                .to_string(),
        ];
        let err = list(OsStr::new("sh"), &args, ".").await.unwrap_err();
        assert_eq!(err.code(), "ERR_CONNECTION");
        assert_eq!(
            err.to_string(),
            "ssh: connect to host h port 22: Connection refused"
        );
    }

    #[tokio::test]
    async fn a_program_that_is_not_there_is_an_error() {
        let err = list(OsStr::new("/nonexistent/ah-ssh"), &[], ".")
            .await
            .unwrap_err();
        assert!(
            err.to_string()
                .starts_with("cannot start /nonexistent/ah-ssh"),
            "{err}"
        );
    }

    #[test]
    fn an_upload_takes_only_the_last_pick_of_its_window() {
        let dir = crate::ansible::create_private_dir(&std::env::temp_dir(), "ah-sftp-pick-")
            .expect("a private folder");
        let a = dir.join("a.txt");
        let b = dir.join("b.txt");
        std::fs::write(&a, b"a").unwrap();
        std::fs::write(&b, b"b").unwrap();
        let picks = Picks::default();

        let first = picks.put("main", vec![a.clone()]);
        assert_eq!(first.names, ["a.txt"]);
        assert_eq!(picks.files("main", first.drop).unwrap(), vec![a.clone()]);
        let second = picks.put("main", vec![a.clone(), b.clone()]);
        assert!(second.drop > first.drop);
        // The pick before is gone with the next one.
        let old = picks.files("main", first.drop).unwrap_err();
        assert_eq!(old.code(), "ERR_VALIDATION");
        // A number not given out, and another window, reach nothing.
        assert!(picks.files("main", second.drop + 1).is_err());
        assert!(picks.files("terminal-1", second.drop).is_err());
        let other = picks.put("terminal-1", vec![b.clone()]);
        assert!(picks.files("main", other.drop).is_err());
        assert_eq!(
            picks.files("main", second.drop).unwrap(),
            [a.clone(), b.clone()]
        );

        // An uploaded file leaves the pick; an old number changes nothing.
        picks.done("main", second.drop, &a);
        picks.done("main", first.drop, &b);
        assert_eq!(picks.files("main", second.drop).unwrap(), vec![b.clone()]);

        // A folder in a drop refuses the whole drop, before any upload.
        let folder = dir.join("sub");
        std::fs::create_dir(&folder).unwrap();
        let mixed = picks.put("main", vec![b.clone(), folder]);
        let err = picks.files("main", mixed.drop).unwrap_err();
        assert_eq!(err.to_string(), "cannot upload sub: it is not a file");
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn a_download_is_saved_under_the_last_part_of_its_path() {
        assert_eq!(suggested_name("/var/log/syslog"), "syslog");
        assert_eq!(suggested_name("notes.txt"), "notes.txt");
        assert_eq!(suggested_name("/srv/data/"), "data");
        assert_eq!(suggested_name("/"), "download");
        assert_eq!(suggested_name(""), "download");
    }

    #[test]
    fn a_suggested_name_names_no_other_folder_or_drive() {
        assert_eq!(suggested_name("/srv/..\\..\\evil.bat"), ".._.._evil.bat");
        assert_eq!(suggested_name("/srv/C:evil"), "C_evil");
        assert_eq!(suggested_name("/srv/a\nb\u{1b}c"), "a_b_c");
        assert_eq!(
            suggested_name("/srv/invoice\u{202e}fdp.exe"),
            "invoice_fdp.exe"
        );
        assert_eq!(
            suggested_name("/srv/\u{061c}a\u{200e}\u{200f}\u{202a}\u{2066}\u{2069}"),
            "_a_____"
        );
        assert_eq!(suggested_name("/srv/.."), "download");
        assert_eq!(suggested_name("/srv/./"), "download");
        assert_eq!(suggested_name("/srv/.hidden"), ".hidden");
    }

    #[tokio::test]
    async fn a_part_file_left_behind_is_replaced_not_written_into() {
        let dir = crate::ansible::create_private_dir(&std::env::temp_dir(), "ah-sftp-part-")
            .expect("a private folder");
        let part = dir.join(".x.ah-part");
        std::fs::write(&part, b"old rest").unwrap();

        let mut file = create_part(&part).await.expect("the part file");
        file.write_all(b"new").await.unwrap();
        file.flush().await.unwrap();
        drop(file);
        assert_eq!(std::fs::read(&part).unwrap(), b"new");
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn a_link_at_the_part_file_is_not_followed() {
        let dir = crate::ansible::create_private_dir(&std::env::temp_dir(), "ah-sftp-link-")
            .expect("a private folder");
        let elsewhere = dir.join("elsewhere");
        std::fs::write(&elsewhere, b"keep").unwrap();
        let part = dir.join(".x.ah-part");
        std::os::unix::fs::symlink(&elsewhere, &part).unwrap();

        let mut file = create_part(&part).await.expect("the part file");
        file.write_all(b"new").await.unwrap();
        file.flush().await.unwrap();
        drop(file);
        assert_eq!(std::fs::read(&elsewhere).unwrap(), b"keep");
        assert!(!std::fs::symlink_metadata(&part).unwrap().is_symlink());
        assert_eq!(std::fs::read(&part).unwrap(), b"new");
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[tokio::test]
    async fn a_folder_at_the_part_file_stops_the_download() {
        let dir = crate::ansible::create_private_dir(&std::env::temp_dir(), "ah-sftp-dir-")
            .expect("a private folder");
        let part = dir.join(".x.ah-part");
        std::fs::create_dir(&part).unwrap();
        assert!(create_part(&part).await.is_err());
        assert!(part.is_dir());
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn joins_remote_paths_and_names_the_part_file() {
        assert_eq!(join("", "a"), "a");
        assert_eq!(join("/", "a"), "/a");
        assert_eq!(join("/srv", "a"), "/srv/a");
        assert_eq!(join("/srv/", "a"), "/srv/a");
        assert_eq!(
            part_path(Path::new("/home/u/x.tar")).unwrap(),
            Path::new("/home/u/.x.tar.ah-part")
        );
    }

    fn channel_over(socket: &Path) -> (PathBuf, Vec<String>) {
        let mut args = vec!["-o".to_string(), "BatchMode=yes".to_string()];
        args.extend(crate::connection::ssh::control_args(socket, false));
        (PathBuf::from("/usr/bin/ssh"), args)
    }

    #[tokio::test]
    async fn an_action_waits_until_the_session_has_signed_in() {
        let dir =
            crate::ansible::create_private_dir(&std::env::temp_dir(), "ah-sftp-wait-").unwrap();
        let socket = dir.join("cm");
        let maker = {
            let socket = socket.clone();
            tokio::spawn(async move {
                tokio::time::sleep(Duration::from_millis(150)).await;
                tokio::fs::write(&socket, b"").await.unwrap();
            })
        };
        let mut asked = 0;
        let got = wait_for_sign_in(
            || {
                asked += 1;
                Ok(channel_over(&socket))
            },
            Duration::from_secs(10),
            Duration::from_millis(20),
        )
        .await;
        maker.await.unwrap();
        std::fs::remove_dir_all(&dir).unwrap();
        assert_eq!(got.unwrap(), channel_over(&socket));
        assert!(asked > 1, "the first round found no socket and waited");
    }

    #[tokio::test]
    async fn an_action_gives_up_when_the_session_never_signs_in() {
        let socket = std::env::temp_dir().join("ah-sftp-wait-missing").join("cm");
        let err = wait_for_sign_in(
            || Ok(channel_over(&socket)),
            Duration::from_millis(100),
            Duration::from_millis(20),
        )
        .await
        .unwrap_err();
        assert_eq!(err.code(), "ERR_CONNECTION");
        assert!(err.to_string().contains("not signed in yet"), "{err}");
    }

    #[tokio::test]
    async fn an_action_ends_with_the_session_it_waits_for() {
        let socket = std::env::temp_dir().join("ah-sftp-wait-ended").join("cm");
        let mut rounds = 0;
        let err = wait_for_sign_in(
            || {
                rounds += 1;
                if rounds < 3 {
                    Ok(channel_over(&socket))
                } else {
                    Err(AppError::Connection(
                        "the terminal session has ended".to_string(),
                    ))
                }
            },
            Duration::from_secs(10),
            Duration::from_millis(10),
        )
        .await
        .unwrap_err();
        assert_eq!(err.to_string(), "the terminal session has ended");
    }

    #[tokio::test]
    async fn an_action_without_a_control_socket_goes_at_once() {
        let channel = (
            PathBuf::from("ssh.exe"),
            vec!["-s".to_string(), "sftp".to_string()],
        );
        let got = wait_for_sign_in(
            || Ok(channel.clone()),
            Duration::ZERO,
            Duration::from_secs(60),
        )
        .await
        .unwrap();
        assert_eq!(got, channel);
    }
}
