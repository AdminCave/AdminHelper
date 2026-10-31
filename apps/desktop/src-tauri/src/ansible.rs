// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::error::AppError;
use crate::session::SessionState;
use crate::terminal::{open_linux_terminal, open_windows_terminal, shell_escape, which};

#[derive(Debug, serde::Deserialize)]
pub struct AnsibleTarget {
    pub hostname: String,
    pub groups: Vec<String>,
}

/// A playbook as a run takes it from the server: its file name and its content.
pub struct Playbook {
    pub filename: String,
    pub content: String,
}

/// Of the answer to `GET /api/ansible/playbooks/{id}`, what a run needs.
#[derive(serde::Deserialize)]
struct PlaybookMeta {
    filename: String,
}

/// The answer to `GET /api/ansible/playbooks/{id}/content`.
#[derive(serde::Deserialize)]
struct PlaybookText {
    content: String,
}

/// Fails unless `id` has the form the server gives a playbook, a UUID (8-4-4-4-12 hex digits,
/// either case). The id goes into the path of a request to the server.
pub fn check_playbook_id(id: &str) -> Result<(), AppError> {
    let groups: Vec<&str> = id.split('-').collect();
    let hex = groups
        .iter()
        .all(|group| group.bytes().all(|b| b.is_ascii_hexdigit()));
    if hex && groups.iter().map(|group| group.len()).eq([8, 4, 4, 4, 12]) {
        return Ok(());
    }
    Err(AppError::Validation("invalid playbook id".to_string()))
}

/// The playbook `id` (checked by [`check_playbook_id`]) from the signed-in server: its file name
/// (`GET /api/ansible/playbooks/{id}`) and its content (`…/{id}/content`), both through the
/// session ([`crate::auth::authenticated_get`]).
pub async fn fetch_playbook(session: &SessionState, id: &str) -> Result<Playbook, AppError> {
    let path = format!("/api/ansible/playbooks/{id}");
    let meta: PlaybookMeta = fetch_json(session, &path).await?;
    let text: PlaybookText = fetch_json(session, &format!("{path}/content")).await?;
    Ok(Playbook {
        filename: meta.filename,
        content: text.content,
    })
}

/// The most of an answer [`fetch_json`] reads. The gateway takes uploads up to 10 MiB, so a
/// playbook as a JSON string stays below it.
const MAX_RESPONSE_BYTES: usize = 16 * 1024 * 1024;

/// The answer to an authenticated GET of `path` as `T`. A status other than 2xx, an answer over
/// [`MAX_RESPONSE_BYTES`] (refused by its declared length before any of the body is read, else
/// as soon as more has arrived) and one that is no `T` are errors that never quote the answer.
async fn fetch_json<T: serde::de::DeserializeOwned>(
    session: &SessionState,
    path: &str,
) -> Result<T, AppError> {
    let (mut response, _) = crate::auth::authenticated_get(session, path).await?;
    let status = response.status();
    if !status.is_success() {
        return Err(AppError::Validation(format!(
            "the playbook could not be loaded ({status})"
        )));
    }
    let too_large = || {
        AppError::Validation(format!(
            "the playbook could not be loaded (answer larger than {} MiB)",
            MAX_RESPONSE_BYTES / (1024 * 1024)
        ))
    };
    if response
        .content_length()
        .is_some_and(|length| length > MAX_RESPONSE_BYTES as u64)
    {
        return Err(too_large());
    }
    let mut body = Vec::new();
    while let Some(chunk) = response.chunk().await? {
        if body.len() + chunk.len() > MAX_RESPONSE_BYTES {
            return Err(too_large());
        }
        body.extend_from_slice(&chunk);
    }
    serde_json::from_slice(&body).map_err(|_| {
        AppError::Validation("the playbook could not be loaded (unexpected answer)".to_string())
    })
}

/// A run of `playbook` on `targets`: creates a directory of its own in the temp dir
/// ([`create_run_dir`]), writes the inventory and the playbook into it, then hands both paths to
/// `launch` ([`launch_ansible`] in the app). If a step fails, the whole directory goes, a
/// half-written file with it, also when `launch` rejected the paths: it is this run's own. After
/// a launch that succeeded, it is left to the run.
pub fn run(
    targets: &[AnsibleTarget],
    playbook: &Playbook,
    launch: impl FnOnce(&str, &str) -> Result<(), AppError>,
) -> Result<(), AppError> {
    run_in(&std::env::temp_dir(), targets, playbook, launch)
}

/// [`run`] with its directory in `base` instead of the temp dir.
fn run_in(
    base: &Path,
    targets: &[AnsibleTarget],
    playbook: &Playbook,
    launch: impl FnOnce(&str, &str) -> Result<(), AppError>,
) -> Result<(), AppError> {
    let dir = create_run_dir(base)?;
    let launched = generate_inventory(&dir, targets)
        .and_then(|inventory| {
            let playbook_path = write_playbook_temp(&dir, &playbook.filename, &playbook.content)?;
            Ok((inventory, playbook_path))
        })
        .and_then(|(inventory, playbook_path)| launch(&inventory, &playbook_path));
    if launched.is_err() {
        let _ = std::fs::remove_dir_all(&dir);
    }
    launched
}

/// The name of every run directory starts with this ([`create_run_dir`]).
const RUN_DIR_PREFIX: &str = "adminhelper_ansible_";

/// Creates the directory of one run in `base`: `adminhelper_ansible_<pid>_<n>_<nanos>`, on Unix
/// mode 0700. Ansible reads `group_vars/`, `host_vars/` and plugins next to the inventory and
/// the playbook, so the directory is created afresh (`create`, never an existing one) and holds
/// only what the run writes. A name that exists already (a pid of an earlier process, a
/// planted entry) gets a new one, up to 16 tries.
fn create_run_dir(base: &Path) -> std::io::Result<PathBuf> {
    static RUN_SEQ: AtomicU64 = AtomicU64::new(0);
    #[cfg(unix)]
    let mut builder = std::fs::DirBuilder::new();
    #[cfg(not(unix))]
    let builder = std::fs::DirBuilder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    let mut tries = 1;
    loop {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|since| since.as_nanos())
            .unwrap_or_default();
        let dir = base.join(format!(
            "{RUN_DIR_PREFIX}{}_{}_{nanos}",
            std::process::id(),
            RUN_SEQ.fetch_add(1, Ordering::Relaxed)
        ));
        match builder.create(&dir) {
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists && tries < 16 => tries += 1,
            created => return created.map(|()| dir),
        }
    }
}

/// Creates a fresh file in a run directory ([`create_run_dir`]). On Unix it is created 0600, and
/// everywhere `create_new` (O_EXCL) refuses to follow a symlink at the path. A file already at
/// the path is cleared first (3.55).
fn create_temp_file(path: &Path) -> std::io::Result<std::fs::File> {
    let _ = std::fs::remove_file(path);
    let mut opts = std::fs::OpenOptions::new();
    opts.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        opts.mode(0o600);
    }
    opts.open(path)
}

/// Writes an Ansible inventory in INI format to `dir/inventory.ini` and returns the path.
pub fn generate_inventory(dir: &Path, servers: &[AnsibleTarget]) -> Result<String, AppError> {
    // Host + group names arrive as attacker-controllable Tauri-command params and go straight into
    // the INI. Validate them like the ssh/rdp spawn paths do: a newline or [/] would otherwise
    // inject extra inventory lines or group headers — at best a broken, hard-to-diagnose
    // inventory, at worst the playbook running against unintended targets (4.91).
    for server in servers {
        crate::validation::validate_host(&server.hostname)?;
        for tag in &server.groups {
            crate::validation::validate_no_control_chars(tag, "Gruppe")?;
            if tag.contains(['[', ']']) {
                return Err(AppError::Validation("Ungueltiger Gruppenname".to_string()));
            }
        }
    }
    let mut content = String::from("[all]\n");
    for server in servers {
        content.push_str(&server.hostname);
        content.push('\n');
    }
    content.push('\n');

    // Build groups from tags
    let mut groups: std::collections::HashMap<&str, Vec<&str>> = std::collections::HashMap::new();
    for server in servers {
        for tag in &server.groups {
            groups
                .entry(tag.as_str())
                .or_default()
                .push(&server.hostname);
        }
    }
    let mut sorted_groups: Vec<_> = groups.into_iter().collect();
    sorted_groups.sort_by_key(|(k, _)| *k);
    for (group, hosts) in sorted_groups {
        content.push_str(&format!("[{}]\n", group));
        for host in hosts {
            content.push_str(host);
            content.push('\n');
        }
        content.push('\n');
    }

    let path = dir.join("inventory.ini");
    let mut file = create_temp_file(&path)?;
    file.write_all(content.as_bytes())?;

    Ok(path.to_string_lossy().to_string())
}

/// Writes the playbook content to `dir/playbook_<name>` and returns the path. The prefix keeps
/// any name apart from `inventory.ini`. Of `filename` only ASCII letters, digits, `.`, `_` and
/// `-` stay, every other character becomes `_`: on Windows the path goes as an argument to
/// Windows Terminal, which reads `;` as the end of a subcommand, and to `cmd`.
pub fn write_playbook_temp(dir: &Path, filename: &str, content: &str) -> Result<String, AppError> {
    let safe_name = filename
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-') {
                c
            } else {
                '_'
            }
        })
        .collect::<String>()
        .replace("..", "_");
    let path = dir.join(format!("playbook_{safe_name}"));
    let mut file = create_temp_file(&path)?;
    file.write_all(content.as_bytes())?;

    Ok(path.to_string_lossy().to_string())
}

/// The run directory of `path` if `path` is one of our own ansible files: after resolving
/// symlinks and `..`, it lies in a directory directly inside the system temp dir whose name
/// starts with `adminhelper_ansible_` and that, on Unix, has no group or other bits (as
/// [`create_run_dir`] makes it; one of another user with 0700 does not resolve). So
/// `ansible-playbook` only gets such files, and a failed start (`launch_ansible_with`) only
/// deletes such a directory. It does not check what a playbook says: `write_playbook_temp`
/// writes the content as [`fetch_playbook`] loaded it from the signed-in server.
fn confined_run_dir(path: &str) -> Option<PathBuf> {
    let canon = std::fs::canonicalize(path).ok()?;
    let temp = std::fs::canonicalize(std::env::temp_dir()).ok()?;
    let dir = canon.parent()?;
    if dir.parent() != Some(temp.as_path()) {
        return None;
    }
    let named = dir
        .file_name()
        .and_then(|name| name.to_str())
        .is_some_and(|name| name.starts_with(RUN_DIR_PREFIX));
    if !named {
        return None;
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mode = std::fs::metadata(dir).ok()?.permissions().mode();
        if mode & 0o077 != 0 {
            return None;
        }
    }
    Some(dir.to_path_buf())
}

/// Starts ansible-playbook in a native terminal.
pub fn launch_ansible(inventory_path: &str, playbook_path: &str) -> Result<(), AppError> {
    launch_ansible_with(inventory_path, playbook_path, start_in_terminal)
}

/// `launch_ansible` with the start passed in. Both files must lie in the same run directory
/// ([`confined_run_dir`]). A start that fails takes that directory with it, as no run will; a
/// path that fails the check is never removed, it may not be ours.
fn launch_ansible_with(
    inventory_path: &str,
    playbook_path: &str,
    start: impl FnOnce(&str, &str) -> Result<(), AppError>,
) -> Result<(), AppError> {
    let run_dir = confined_run_dir(inventory_path);
    let Some(run_dir) = run_dir.filter(|dir| confined_run_dir(playbook_path).as_ref() == Some(dir))
    else {
        return Err(AppError::Validation(
            "Ansible-Pfad ausserhalb des erlaubten Temp-Verzeichnisses".to_string(),
        ));
    };
    // On Unix the start gets the files under the checked directory, not the paths as given: the
    // script that ends the run removes the directory they name. Windows keeps the given paths:
    // `canonicalize` there adds a `\\?\` prefix, and no script of ours removes by them.
    #[cfg(unix)]
    let in_run_dir = |path: &str| {
        Path::new(path)
            .file_name()
            .map(|name| run_dir.join(name).to_string_lossy().into_owned())
            .unwrap_or_default()
    };
    #[cfg(not(unix))]
    let in_run_dir = |path: &str| path.to_string();
    let started = start(&in_run_dir(inventory_path), &in_run_dir(playbook_path));
    if started.is_err() {
        let _ = std::fs::remove_dir_all(&run_dir);
    }
    started
}

fn start_in_terminal(inventory_path: &str, playbook_path: &str) -> Result<(), AppError> {
    if which("ansible-playbook").is_none() {
        return Err(AppError::Connection(
            "ansible-playbook wurde nicht gefunden. Bitte Ansible installieren.".to_string(),
        ));
    }

    if cfg!(target_os = "windows") {
        open_windows_terminal(
            "ansible-playbook",
            &[
                "-i".to_string(),
                inventory_path.to_string(),
                playbook_path.to_string(),
            ],
        )
    } else {
        let bash_args = vec![
            "-c".to_string(),
            linux_run_script(inventory_path, playbook_path),
        ];
        open_linux_terminal("bash", &bash_args)
    }
}

/// The `bash -c` script of a Linux run. It removes the run directory (the one the inventory lies
/// in, [`run`]) with both files once ansible-playbook ends, whatever its exit code. On SIGHUP
/// (terminal closed mid-run) or SIGTERM bash would die at once and run the EXIT trap while
/// ansible-playbook may still be running; trapping both to `exit` defers that, as bash runs such
/// a trap only after the foreground ansible-playbook has ended. INT stays untrapped: bash runs an
/// INT trap even when ansible-playbook caught Ctrl-C itself, so `exit` there would close the
/// terminal over its output, and on SIGINT bash waits for ansible-playbook anyway and, if that
/// died of it, runs the EXIT trap (the Ctrl-C test pins both).
fn linux_run_script(inventory_path: &str, playbook_path: &str) -> String {
    let run_dir = shell_escape(
        Path::new(inventory_path)
            .parent()
            .and_then(Path::to_str)
            .unwrap_or_default(),
    );
    let inventory = shell_escape(inventory_path);
    let playbook = shell_escape(playbook_path);
    format!(
        "ah_cleanup() {{ rm -rf -- {run_dir}; }}; \
         trap ah_cleanup EXIT; trap exit HUP TERM; \
         ansible-playbook -i {inventory} {playbook}; ah_cleanup; \
         echo ''; echo 'Ansible beendet. Druecke Enter zum Schliessen.'; read"
    )
}

#[cfg(test)]
mod tests {
    use super::{
        confined_run_dir, create_run_dir, create_temp_file, fetch_playbook, generate_inventory,
        launch_ansible_with, run, run_in, write_playbook_temp, AnsibleTarget, Playbook,
    };
    use crate::error::AppError;
    use crate::session::SessionState;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::sync::{Arc, Mutex};

    fn one_target() -> Vec<AnsibleTarget> {
        vec![AnsibleTarget {
            hostname: "web01".to_string(),
            groups: vec!["web".to_string()],
        }]
    }

    const PLAYBOOK_ID: &str = "0b6f2c1e-8a4d-4c3b-9e7f-1a2b3c4d5e6f";

    /// How [`serve_framed`] frames the body of a reply.
    #[derive(Clone, Copy)]
    enum Framing {
        /// `content-length` with the length of the body.
        Sized,
        /// No `content-length`: the body ends where the connection does.
        Unsized,
        /// `content-length: <n>` and no body: the connection stays open until the client closes
        /// it, so a client that reads the body waits.
        Claims(usize),
    }

    /// [`serve_framed`] with every body [`Framing::Sized`].
    async fn serve(replies: Vec<(&'static str, String)>) -> (String, Arc<Mutex<Vec<String>>>) {
        let replies = replies
            .into_iter()
            .map(|(status, body)| (status, body, Framing::Sized))
            .collect();
        serve_framed(replies).await
    }

    /// Serve HTTP on a fresh loopback port, one request per connection: the n-th request gets
    /// the n-th of `replies` (status line, body and its framing), a request after them its
    /// connection closed unanswered. The request line of every request lands in the log.
    async fn serve_framed(
        replies: Vec<(&'static str, String, Framing)>,
    ) -> (String, Arc<Mutex<Vec<String>>>) {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://127.0.0.1:{}", listener.local_addr().unwrap().port());
        let log = Arc::new(Mutex::new(Vec::new()));
        let seen = Arc::clone(&log);
        tokio::spawn(async move {
            let mut replies = replies.into_iter();
            loop {
                let (mut tcp, _) = listener.accept().await.unwrap();
                let mut head = Vec::new();
                let mut buf = [0u8; 1024];
                while !head.windows(4).any(|w| w == b"\r\n\r\n") {
                    let n = tcp.read(&mut buf).await.unwrap();
                    if n == 0 {
                        break;
                    }
                    head.extend_from_slice(&buf[..n]);
                }
                let head = String::from_utf8_lossy(&head);
                seen.lock()
                    .unwrap()
                    .push(head.lines().next().unwrap_or_default().to_string());
                if let Some((status, body, framing)) = replies.next() {
                    let length = match framing {
                        Framing::Sized => format!("content-length: {}\r\n", body.len()),
                        Framing::Unsized => String::new(),
                        Framing::Claims(claimed) => format!("content-length: {claimed}\r\n"),
                    };
                    let reply =
                        format!("HTTP/1.1 {status}\r\n{length}connection: close\r\n\r\n{body}");
                    tcp.write_all(reply.as_bytes()).await.unwrap();
                    if let Framing::Claims(_) = framing {
                        // Returns once the client closes the connection (0 bytes) or sends.
                        let _ = tcp.read(&mut buf).await;
                    }
                }
                let _ = tcp.shutdown().await;
            }
        });
        (url, log)
    }

    /// A session of `ops-admin` on `server`.
    async fn signed_in(server: String) -> SessionState {
        let session = SessionState::default();
        session
            .set(
                server,
                "access".to_string(),
                "refresh".to_string(),
                "ops-admin".to_string(),
                false,
            )
            .await;
        session
    }

    /// The metadata of the playbook [`PLAYBOOK_ID`] as the server lists it.
    fn listed_playbook() -> String {
        serde_json::json!({
            "id": PLAYBOOK_ID,
            "name": "Deploy",
            "filename": "deploy.yml",
            "description": "",
            "tags": [],
            "createdAt": "2026-10-22T10:00:00Z",
            "updatedAt": "2026-10-22T10:00:00Z",
        })
        .to_string()
    }

    /// Removes the directory (with everything in it) or the file `.0` when dropped, also after a
    /// panic.
    struct Removed(PathBuf);

    impl Drop for Removed {
        fn drop(&mut self) {
            // Only an entry of a run or of a test: a run that wrote into the temp dir itself must
            // not make its guard take the temp dir.
            let ours = self
                .0
                .file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| {
                    name.starts_with("adminhelper_ansible_") || name.starts_with("ah-ansible-")
                });
            if ours {
                let _ = fs::remove_dir_all(&self.0).or_else(|_| fs::remove_file(&self.0));
            }
        }
    }

    /// A run directory in the temp dir ([`create_run_dir`]).
    fn run_dir() -> Removed {
        Removed(create_run_dir(&std::env::temp_dir()).unwrap())
    }

    /// An empty directory `ah-ansible-<case>-<pid>-<n>` in the temp dir, new for every call.
    fn scratch(case: &str) -> Removed {
        static SEQ: AtomicU64 = AtomicU64::new(0);
        let dir = std::env::temp_dir().join(format!(
            "ah-ansible-{case}-{}-{}",
            std::process::id(),
            SEQ.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&dir).unwrap();
        Removed(dir)
    }

    /// The playbook `filename` with one play.
    fn site(filename: &str) -> Playbook {
        Playbook {
            filename: filename.to_string(),
            content: "- hosts: all\n".to_string(),
        }
    }

    #[test]
    fn run_writes_both_files_into_a_directory_of_its_own() {
        let mut seen = None;
        let result = run(
            &one_target(),
            &site("own_dir.yml"),
            |inventory, playbook| {
                seen = Some((PathBuf::from(inventory), PathBuf::from(playbook)));
                Ok(())
            },
        );
        let (inventory, playbook) = seen.expect("the run never launched");
        let dir = inventory.parent().unwrap().to_path_buf();
        let _gone = Removed(dir.clone());

        assert!(result.is_ok(), "{result:?}");
        assert_eq!(playbook.parent(), Some(dir.as_path()), "{playbook:?}");
        let temp = std::env::temp_dir();
        assert_ne!(
            dir, temp,
            "in the temp dir itself: {inventory:?}, {playbook:?}"
        );
        assert_eq!(dir.parent(), Some(temp.as_path()), "{dir:?}");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = fs::metadata(&dir).unwrap().permissions().mode();
            assert_eq!(mode & 0o777, 0o700, "{dir:?}");
        }
    }

    #[test]
    fn run_removes_its_directory_when_the_playbook_cannot_be_written() {
        let base = scratch("unwritable");
        let mut launched = false;

        // No file system takes a name of 300 bytes (ENAMETOOLONG).
        let result = run_in(&base.0, &one_target(), &site(&"a".repeat(300)), |_, _| {
            launched = true;
            Ok(())
        });
        let left: Vec<PathBuf> = fs::read_dir(&base.0)
            .unwrap()
            .flatten()
            .map(|entry| entry.path())
            .collect();

        assert!(result.is_err(), "{result:?}");
        assert!(!launched, "launched without a playbook");
        assert_eq!(left, Vec::<PathBuf>::new(), "the run directory was left");
    }

    #[test]
    fn run_removes_its_directory_when_the_launch_fails() {
        let mut seen = None;
        let result = run(&one_target(), &site("launch_fails.yml"), |inventory, _| {
            seen = Some(PathBuf::from(inventory));
            Err(AppError::Connection("no terminal found".to_string()))
        });
        let dir = seen
            .expect("the run never launched")
            .parent()
            .unwrap()
            .to_path_buf();
        let _gone = Removed(dir.clone());

        assert!(matches!(result, Err(AppError::Connection(_))), "{result:?}");
        assert!(!dir.exists(), "{dir:?} left after a failed launch");
    }

    #[test]
    fn check_playbook_id_takes_only_a_uuid() {
        for id in [PLAYBOOK_ID, "0B6F2C1E-8A4D-4C3B-9E7F-1A2B3C4D5E6F"] {
            assert!(super::check_playbook_id(id).is_ok(), "{id}");
        }
        for id in [
            "",
            "pb1",
            "0b6f2c1e8a4d4c3b9e7f1a2b3c4d5e6f",
            "0b6f2c1e-8a4d-4c3b-9e7f-1a2b3c4d5e6",
            "0b6f2c1e-8a4d-4c3b-9e7f-1a2b3c4d5e6g",
            "0b6f2c1e-8a4d-4c3b-9e7f-1a2b3c4d5e6f-",
            "0b6f2c1e-8a4d-4c3b-9e7f-1a2b3c4d5e6f/content",
            "../0b6f2c1e-8a4d-4c3b-9e7f-1a2b3c4d5e6f",
            " 0b6f2c1e-8a4d-4c3b-9e7f-1a2b3c4d5e6f",
            "0b6f2c1e-8a4d-4c3b-9e7f-1a2b3c4d5e6f?x=1",
            "+b6f2c1e-8a4d-4c3b-9e7f-1a2b3c4d5e6f",
        ] {
            assert!(
                matches!(super::check_playbook_id(id), Err(AppError::Validation(_))),
                "{id:?}"
            );
        }
    }

    #[tokio::test]
    async fn fetch_playbook_loads_name_and_content_from_the_signed_in_server() {
        let (server, log) = serve(vec![
            ("200 OK", listed_playbook()),
            (
                "200 OK",
                serde_json::json!({ "content": "- hosts: all\n  tasks: []\n" }).to_string(),
            ),
        ])
        .await;
        let session = signed_in(server).await;

        let playbook = fetch_playbook(&session, PLAYBOOK_ID).await.unwrap();

        assert_eq!(playbook.filename, "deploy.yml");
        assert_eq!(playbook.content, "- hosts: all\n  tasks: []\n");
        assert_eq!(
            *log.lock().unwrap(),
            [
                format!("GET /api/ansible/playbooks/{PLAYBOOK_ID} HTTP/1.1"),
                format!("GET /api/ansible/playbooks/{PLAYBOOK_ID}/content HTTP/1.1"),
            ]
        );
    }

    #[tokio::test]
    async fn fetch_playbook_fails_on_a_refused_answer_and_names_only_the_status() {
        let body = r#"{"detail":"Playbook nicht gefunden"}"#.to_string();
        for (case, replies, requests) in [
            ("metadata", vec![("404 Not Found", body.clone())], 1),
            (
                "content",
                vec![
                    ("200 OK", listed_playbook()),
                    ("404 Not Found", body.clone()),
                ],
                2,
            ),
        ] {
            let (server, log) = serve(replies).await;
            let session = signed_in(server).await;

            let message = fetch_playbook(&session, PLAYBOOK_ID)
                .await
                .err()
                .map(|e| e.to_string())
                .unwrap_or_default();

            assert!(message.contains("404 Not Found"), "{case}: {message}");
            assert!(!message.contains("nicht gefunden"), "{case}: {message}");
            assert_eq!(log.lock().unwrap().len(), requests, "{case}");
        }
    }

    #[tokio::test]
    async fn fetch_playbook_fails_on_an_answer_that_is_no_playbook_and_never_quotes_it() {
        // A JSON string where an object belongs: serde names such a value in its message.
        let quoted = r#""ah-answer-text""#;
        for (case, body) in [("{}", "{}"), ("html", "<html>"), ("string", quoted)] {
            for (part, replies, requests) in [
                ("metadata", vec![("200 OK", body.to_string())], 1),
                (
                    "content",
                    vec![("200 OK", listed_playbook()), ("200 OK", body.to_string())],
                    2,
                ),
            ] {
                let (server, log) = serve(replies).await;
                let session = signed_in(server).await;

                let message = fetch_playbook(&session, PLAYBOOK_ID)
                    .await
                    .err()
                    .map(|e| e.to_string())
                    .unwrap_or_else(|| panic!("{part} {case}: no error"));

                assert!(
                    message.contains("the playbook could not be loaded"),
                    "{part} {case}: {message}"
                );
                assert!(
                    !message.contains("ah-answer-text"),
                    "{part} {case}: {message}"
                );
                assert_eq!(log.lock().unwrap().len(), requests, "{part} {case}");
            }
        }
    }

    /// The answer to the content request, exactly `bytes` long.
    fn content_of_size(bytes: usize) -> String {
        let frame = r#"{"content":""}"#.len();
        format!(r#"{{"content":"{}"}}"#, "a".repeat(bytes - frame))
    }

    #[tokio::test]
    async fn fetch_playbook_reads_at_most_16_mib_of_an_answer() {
        const LIMIT: usize = 16 * 1024 * 1024;

        // Exactly the limit, without a length: read to its end.
        let (server, _) = serve_framed(vec![
            ("200 OK", listed_playbook(), Framing::Sized),
            ("200 OK", content_of_size(LIMIT), Framing::Unsized),
        ])
        .await;
        let session = signed_in(server).await;
        let playbook = fetch_playbook(&session, PLAYBOOK_ID).await.unwrap();
        assert_eq!(playbook.content.len(), LIMIT - r#"{"content":""}"#.len());

        // One byte more, without a length: refused.
        let (server, _) = serve_framed(vec![
            ("200 OK", listed_playbook(), Framing::Sized),
            ("200 OK", content_of_size(LIMIT + 1), Framing::Unsized),
        ])
        .await;
        let session = signed_in(server).await;
        let message = fetch_playbook(&session, PLAYBOOK_ID)
            .await
            .err()
            .map(|e| e.to_string())
            .unwrap_or_default();
        assert!(message.contains("larger than 16 MiB"), "{message}");

        // A length over the limit: refused before the body. The server sends none and keeps the
        // connection open, so a client that read it would wait.
        let (server, _) = serve_framed(vec![
            ("200 OK", listed_playbook(), Framing::Sized),
            ("200 OK", String::new(), Framing::Claims(LIMIT + 1)),
        ])
        .await;
        let session = signed_in(server).await;
        let fetched = tokio::time::timeout(
            std::time::Duration::from_secs(10),
            fetch_playbook(&session, PLAYBOOK_ID),
        )
        .await
        .expect("the client waited for a body over the limit");
        let message = fetched.err().map(|e| e.to_string()).unwrap_or_default();
        assert!(message.contains("larger than 16 MiB"), "{message}");
    }

    /// A directory holding a stub `ansible-playbook`: it runs `before`, records its arguments in
    /// `args` (only if both files exist while it runs), then runs `then`. A test acts once `args`
    /// is there, so what must hold by then (a trap) goes in `before`.
    #[cfg(unix)]
    fn stub_ansible_playbook(case: &str, before: &str, then: &str) -> Removed {
        use crate::terminal::shell_escape;
        use std::os::unix::fs::PermissionsExt;
        let dir = scratch(&format!("stub-{case}"));
        let args = shell_escape(dir.0.join("args").to_str().unwrap());
        let partial = shell_escape(dir.0.join("args.partial").to_str().unwrap());
        let stub = dir.0.join("ansible-playbook");
        fs::write(
            &stub,
            format!(
                "#!/bin/sh\n{before}\n[ -f \"$2\" ] && [ -f \"$3\" ] && printf '%s\\n' \"$*\" \
                 > {partial} && mv {partial} {args}\n{then}\n"
            ),
        )
        .unwrap();
        fs::set_permissions(&stub, fs::Permissions::from_mode(0o755)).unwrap();
        dir
    }

    /// `bash -c` with the script of a Linux run, the stub first on PATH (only in the child's
    /// environment) and stdin at EOF, so the closing `read` returns at once.
    #[cfg(unix)]
    fn run_script_command(
        stub_dir: &Path,
        inventory: &str,
        playbook: &str,
    ) -> std::process::Command {
        use std::process::Stdio;
        let mut dirs = vec![stub_dir.to_path_buf()];
        dirs.extend(std::env::split_paths(
            &std::env::var_os("PATH").unwrap_or_default(),
        ));
        let mut command = std::process::Command::new("bash");
        command
            .arg("-c")
            .arg(super::linux_run_script(inventory, playbook))
            .env("PATH", std::env::join_paths(dirs).unwrap())
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        command
    }

    #[cfg(unix)]
    #[test]
    fn linux_run_script_removes_both_files_when_ansible_playbook_ends() {
        for code in [0, 2] {
            let stub = stub_ansible_playbook(&format!("exit{code}"), "", &format!("exit {code}"));
            let dir = run_dir();
            let inventory = generate_inventory(&dir.0, &one_target()).unwrap();
            let playbook = write_playbook_temp(&dir.0, "it's a run.yml", "- hosts: all\n").unwrap();

            let status = run_script_command(&stub.0, &inventory, &playbook)
                .status()
                .unwrap();
            let args = fs::read_to_string(stub.0.join("args")).unwrap_or_default();
            let left = (
                Path::new(&inventory).exists(),
                Path::new(&playbook).exists(),
                dir.0.exists(),
            );

            assert_eq!(
                args,
                format!("-i {inventory} {playbook}\n"),
                "the stub did not run on both files (exit {code}, bash {status})"
            );
            assert_eq!(
                left,
                (false, false, false),
                "files or their directory left after exit {code}"
            );
        }
    }

    #[cfg(unix)]
    struct MidRun {
        started: bool,
        ended: bool,
        left: (bool, bool),
        stdout: String,
    }

    /// Runs the script in a process group of its own with a stub that runs `before` and `then`
    /// (see [`stub_ansible_playbook`]), and once the stub runs on both files sends `signal` to
    /// the whole group, as the terminal does to bash and the run alike on close or Ctrl-C.
    #[cfg(unix)]
    fn signal_mid_run(case: &str, before: &str, then: &str, signal: &str) -> MidRun {
        use std::io::Read;
        use std::os::unix::process::CommandExt;
        use std::time::{Duration, Instant};
        let stub = stub_ansible_playbook(case, before, then);
        let dir = run_dir();
        let inventory = generate_inventory(&dir.0, &one_target()).unwrap();
        let playbook =
            write_playbook_temp(&dir.0, &format!("{case}.yml"), "- hosts: all\n").unwrap();

        let mut child = run_script_command(&stub.0, &inventory, &playbook)
            .stdout(std::process::Stdio::piped())
            .process_group(0)
            .spawn()
            .unwrap();
        let group = format!("-{}", child.id());
        let marker = stub.0.join("args");
        let deadline = Instant::now() + Duration::from_secs(10);
        while !marker.exists() && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(20));
        }
        let started = marker.exists();
        let _ = std::process::Command::new("kill")
            .args([signal, "--", &group])
            .status();
        let deadline = Instant::now() + Duration::from_secs(10);
        let mut ended = None;
        while ended.is_none() && Instant::now() < deadline {
            ended = child.try_wait().unwrap();
            std::thread::sleep(Duration::from_millis(20));
        }
        if ended.is_none() {
            let _ = std::process::Command::new("kill")
                .args(["-KILL", "--", &group])
                .status();
        }
        // After a try_wait that already had the status, wait returns it again at once.
        let _ = child.wait();
        let mut stdout = String::new();
        let _ = child.stdout.take().unwrap().read_to_string(&mut stdout);
        let left = (
            Path::new(&inventory).exists(),
            Path::new(&playbook).exists(),
        );
        MidRun {
            started,
            ended: ended.is_some(),
            left,
            stdout,
        }
    }

    #[cfg(unix)]
    #[test]
    fn linux_run_script_removes_both_files_when_the_terminal_hangs_up_mid_run() {
        let run = signal_mid_run("hangup", "", "exec sleep 30", "-HUP");
        assert!(run.started, "the stub never ran on both files");
        assert!(run.ended, "bash did not end after SIGHUP");
        assert_eq!(run.left, (false, false), "files left after SIGHUP");
    }

    #[cfg(unix)]
    #[test]
    fn linux_run_script_keeps_both_files_until_the_run_ends_after_hup_or_term() {
        // Without `trap exit HUP TERM` bash would run its EXIT trap at once and remove the
        // files under a run still reading them; the test above stays green either way, since
        // it only looks once everything has ended. Here the stub outlives the signal by a
        // moment and checks that both files are still there. No `exec`: its trap must stay.
        for (case, signal) in [("hangup-keeps", "-HUP"), ("term-keeps", "-TERM")] {
            let run = signal_mid_run(
                case,
                r#"trap 'sleep 0.3; if [ -f "$2" ] && [ -f "$3" ]; then echo AH_KEPT_BOTH; fi; exit 0' HUP TERM"#,
                "while :; do sleep 0.1; done",
                signal,
            );
            assert!(run.started, "{case}: the stub never ran on both files");
            assert!(run.ended, "{case}: bash did not end after {signal}");
            assert_eq!(run.left, (false, false), "{case}: files left after the run");
            assert!(
                run.stdout.contains("AH_KEPT_BOTH"),
                "{case}: the files went before the run ended: {:?}",
                run.stdout
            );
        }
    }

    #[cfg(unix)]
    #[test]
    fn linux_run_script_removes_both_files_after_ctrl_c_mid_run() {
        // ansible-playbook catches Ctrl-C and exits 99: the run still goes on to the prompt.
        let caught = signal_mid_run(
            "interrupt-caught",
            "trap 'exit 99' INT",
            "while :; do sleep 1; done",
            "-INT",
        );
        assert!(caught.started, "the stub never ran on both files");
        assert!(caught.ended, "bash did not end after SIGINT");
        assert_eq!(caught.left, (false, false), "files left after SIGINT");
        assert!(
            caught.stdout.contains("Ansible beendet."),
            "Ctrl-C mid-run closed before the prompt: {:?}",
            caught.stdout
        );

        // A run killed by it: bash dies of SIGINT too, and its EXIT trap takes the files.
        let killed = signal_mid_run("interrupt-killed", "", "exec sleep 30", "-INT");
        assert!(killed.started, "the stub never ran on both files");
        assert!(killed.ended, "bash did not end after SIGINT");
        assert_eq!(killed.left, (false, false), "files left after SIGINT");
    }

    #[test]
    fn launch_ansible_removes_both_files_when_the_start_fails() {
        let dir = run_dir();
        let inventory = generate_inventory(&dir.0, &one_target()).unwrap();
        let playbook = write_playbook_temp(&dir.0, "failed_start.yml", "- hosts: all\n").unwrap();

        #[cfg(unix)]
        let canonical = |path: &str| {
            fs::canonicalize(path)
                .unwrap()
                .to_string_lossy()
                .into_owned()
        };
        #[cfg(unix)]
        let expected = (canonical(&inventory), canonical(&playbook));
        #[cfg(not(unix))]
        let expected = (inventory.clone(), playbook.clone());
        let mut seen = None;
        let result = launch_ansible_with(&inventory, &playbook, |inv, pb| {
            seen = Some((inv.to_string(), pb.to_string()));
            Err(AppError::Connection("Kein Terminal gefunden".to_string()))
        });

        assert!(matches!(result, Err(AppError::Connection(_))), "{result:?}");
        assert_eq!(seen, Some((expected.0, expected.1)));
        assert!(!dir.0.exists(), "{:?} left after a failed start", dir.0);
    }

    #[cfg(unix)]
    #[test]
    fn launch_ansible_hands_the_start_the_files_under_the_checked_directory() {
        // The run script removes the directory its files lie in: that must be the one
        // `confined_run_dir` checked, not the spelling the caller used.
        let dir = run_dir();
        let inventory = generate_inventory(&dir.0, &one_target()).unwrap();
        let playbook = write_playbook_temp(&dir.0, "linked.yml", "- hosts: all\n").unwrap();
        let link = scratch("link");
        let linked = link.0.join("run");
        std::os::unix::fs::symlink(&dir.0, &linked).unwrap();
        let through = |path: &str| linked.join(Path::new(path).file_name().unwrap());

        let mut seen = None;
        launch_ansible_with(
            through(&inventory).to_str().unwrap(),
            through(&playbook).to_str().unwrap(),
            |inv, pb| {
                seen = Some((inv.to_string(), pb.to_string()));
                Ok(())
            },
        )
        .unwrap();

        let (inv, pb) = seen.unwrap();
        let expected = fs::canonicalize(&dir.0).unwrap();
        assert_eq!(Path::new(&inv).parent(), Some(expected.as_path()));
        assert_eq!(Path::new(&pb).parent(), Some(expected.as_path()));
    }

    #[test]
    fn launch_ansible_leaves_the_files_to_the_run_when_the_start_succeeds() {
        // The terminal starts asynchronously and reads both files later: removing them on a
        // successful start would break every run.
        let dir = run_dir();
        let inventory = generate_inventory(&dir.0, &one_target()).unwrap();
        let playbook = write_playbook_temp(&dir.0, "started.yml", "- hosts: all\n").unwrap();

        let result = launch_ansible_with(&inventory, &playbook, |_, _| Ok(()));
        let left = (
            Path::new(&inventory).exists(),
            Path::new(&playbook).exists(),
        );

        assert!(result.is_ok(), "{result:?}");
        assert_eq!(left, (true, true), "files gone after a successful start");
    }

    #[test]
    fn launch_ansible_never_removes_a_path_that_fails_the_check() {
        let foreign = Removed(std::env::temp_dir().join(format!(
            "ah-ansible-foreign-playbook-{}.yml",
            std::process::id()
        )));
        fs::write(&foreign.0, b"- hosts: all\n").unwrap();
        let dir = run_dir();
        let inventory = generate_inventory(&dir.0, &one_target()).unwrap();

        let mut started = false;
        let result = launch_ansible_with(&inventory, foreign.0.to_str().unwrap(), |_, _| {
            started = true;
            Err(AppError::Connection("Kein Terminal gefunden".to_string()))
        });
        let left = (Path::new(&inventory).exists(), foreign.0.exists());

        assert!(matches!(result, Err(AppError::Validation(_))), "{result:?}");
        assert!(!started, "started despite a rejected path");
        assert_eq!(
            left,
            (true, true),
            "a file was removed after a rejected path"
        );
    }

    #[test]
    fn launch_ansible_takes_both_files_only_from_one_run_directory() {
        let (first, second) = (run_dir(), run_dir());
        let inventory = generate_inventory(&first.0, &one_target()).unwrap();
        let playbook = write_playbook_temp(&second.0, "two_dirs.yml", "- hosts: all\n").unwrap();

        let mut started = false;
        let result = launch_ansible_with(&inventory, &playbook, |_, _| {
            started = true;
            Err(AppError::Connection("Kein Terminal gefunden".to_string()))
        });
        let left = (
            Path::new(&inventory).exists(),
            Path::new(&playbook).exists(),
        );

        assert!(matches!(result, Err(AppError::Validation(_))), "{result:?}");
        assert!(!started, "started on the files of two run directories");
        assert_eq!(
            left,
            (true, true),
            "a file was removed after a rejected pair"
        );
    }

    #[test]
    fn generate_inventory_rejects_host_and_group_injection() {
        // 4.91: a hostname with a newline or a group name with [/] must be rejected — otherwise it
        // injects extra inventory lines or group headers into the INI.
        let dir = run_dir();
        let bad_host = vec![AnsibleTarget {
            hostname: "host\nevil ansible_connection=local".to_string(),
            groups: vec![],
        }];
        assert!(generate_inventory(&dir.0, &bad_host).is_err());

        let bad_group = vec![AnsibleTarget {
            hostname: "host".to_string(),
            groups: vec!["[evil]".to_string()],
        }];
        assert!(generate_inventory(&dir.0, &bad_group).is_err());

        // A clean target still passes.
        let ok = vec![AnsibleTarget {
            hostname: "web01.example.com".to_string(),
            groups: vec!["web".to_string()],
        }];
        assert!(generate_inventory(&dir.0, &ok).is_ok());
    }

    #[test]
    fn generate_inventory_builds_group_sections() {
        let targets = vec![
            AnsibleTarget {
                hostname: "web01".to_string(),
                groups: vec!["web".to_string()],
            },
            AnsibleTarget {
                hostname: "db01".to_string(),
                groups: vec!["db".to_string()],
            },
        ];
        let dir = run_dir();
        let path = generate_inventory(&dir.0, &targets).unwrap();
        let content = fs::read_to_string(&path).unwrap();
        assert_eq!(Path::new(&path), dir.0.join("inventory.ini"));
        assert!(
            content.contains("[all]\nweb01\ndb01\n"),
            "all section: {content}"
        );
        assert!(
            content.contains("[db]\ndb01\n"),
            "db group (sorted first): {content}"
        );
        assert!(content.contains("[web]\nweb01\n"), "web group: {content}");
    }

    #[test]
    fn write_playbook_temp_sanitizes_traversal() {
        // Path separators and .. in the filename must be neutralized so the written playbook stays
        // in its run directory (an unconfined path is RCE via ansible-playbook).
        let dir = run_dir();
        let path = write_playbook_temp(&dir.0, "../../etc/passwd", "- hosts: all\n").unwrap();
        assert_eq!(
            Path::new(&path).parent(),
            Some(dir.0.as_path()),
            "traversal filename escaped its directory: {path}"
        );
        assert!(
            confined_run_dir(&path).is_some(),
            "traversal filename escaped temp: {path}"
        );
        assert!(!path.contains(".."), "'..' not sanitized: {path}");
    }

    #[test]
    fn write_playbook_temp_keeps_only_letters_digits_dot_underscore_and_dash() {
        // On Windows the path goes as an argument to Windows Terminal, which reads `;` as the end
        // of a subcommand, and to `cmd`.
        let dir = run_dir();
        for (name, written) in [
            ("a;b&c%d^e|f.yml", "playbook_a_b_c_d_e_f.yml"),
            ("x y.yml", "playbook_x_y.yml"),
            ("ü.yml", "playbook__.yml"),
            ("Deploy-web_v1.2.yml", "playbook_Deploy-web_v1.2.yml"),
        ] {
            let path = write_playbook_temp(&dir.0, name, "- hosts: all\n").unwrap();
            assert_eq!(Path::new(&path), dir.0.join(written), "{name:?}");
        }
    }

    #[test]
    fn two_runs_of_one_playbook_get_a_directory_each() {
        // Two workspace processes (or two runs in one) write the same playbook name: the second
        // write must not replace the file a terminal of the first is about to run.
        let (first_dir, second_dir) = (run_dir(), run_dir());
        let first =
            write_playbook_temp(&first_dir.0, "per_process_site.yml", "- hosts: first\n").unwrap();
        let second =
            write_playbook_temp(&second_dir.0, "per_process_site.yml", "- hosts: second\n")
                .unwrap();

        assert_ne!(first_dir.0, second_dir.0, "two runs, one directory");
        let name = first_dir.0.file_name().unwrap().to_string_lossy();
        assert!(
            name.starts_with(&format!("adminhelper_ansible_{}_", std::process::id())),
            "no pid in {name}"
        );
        assert_eq!(fs::read_to_string(&first).unwrap(), "- hosts: first\n");
        assert_eq!(fs::read_to_string(&second).unwrap(), "- hosts: second\n");
        assert!(
            first.ends_with("playbook_per_process_site.yml"),
            "the name stays last: {first}"
        );
    }

    #[test]
    fn confines_ansible_paths_to_files_of_a_run_directory() {
        let dir = run_dir();
        let pid = std::process::id();

        // A file of a run directory: accepted, with that directory.
        let ours = dir.0.join("site.yml");
        fs::write(&ours, b"- hosts: all\n").unwrap();
        assert_eq!(
            confined_run_dir(ours.to_str().unwrap()),
            Some(fs::canonicalize(&dir.0).unwrap())
        );

        // A file with our prefix directly in the temp dir: rejected, also when reached through a
        // run directory.
        let loose =
            Removed(std::env::temp_dir().join(format!("adminhelper_ansible_loose_{pid}.yml")));
        fs::write(&loose.0, b"- hosts: all\n").unwrap();
        assert_eq!(confined_run_dir(loose.0.to_str().unwrap()), None);
        let escape = dir
            .0
            .join(format!("../adminhelper_ansible_loose_{pid}.yml"));
        assert_eq!(confined_run_dir(escape.to_str().unwrap()), None);

        // A file in a directory without our prefix, or one level down in a run directory:
        // rejected.
        let foreign = scratch("foreign-dir");
        let foreign_file = foreign.0.join("site.yml");
        fs::write(&foreign_file, b"- hosts: all\n").unwrap();
        assert_eq!(confined_run_dir(foreign_file.to_str().unwrap()), None);
        let nested = dir.0.join("group_vars");
        fs::create_dir(&nested).unwrap();
        fs::write(nested.join("all.yml"), b"x: 1\n").unwrap();
        assert_eq!(
            confined_run_dir(nested.join("all.yml").to_str().unwrap()),
            None
        );

        // A non-existent path: rejected (cannot be canonicalized).
        assert_eq!(
            confined_run_dir(dir.0.join("does_not_exist.yml").to_str().unwrap()),
            None
        );

        // A run directory that others may read: rejected.
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let open = run_dir();
            let file = open.0.join("site.yml");
            fs::write(&file, b"- hosts: all\n").unwrap();
            fs::set_permissions(&open.0, fs::Permissions::from_mode(0o755)).unwrap();
            assert_eq!(confined_run_dir(file.to_str().unwrap()), None);
        }
    }

    #[test]
    fn create_temp_file_is_exclusive_and_hardened() {
        let dir = run_dir();
        let path = dir.0.join("create_test");

        let f = create_temp_file(&path).unwrap();
        drop(f);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = fs::metadata(&path).unwrap().permissions().mode();
            assert_eq!(mode & 0o777, 0o600, "ansible temp file must be 0600");
        }
        // A second call over a file already there still succeeds (remove-first).
        assert!(create_temp_file(&path).is_ok());
    }

    #[cfg(unix)]
    #[test]
    fn create_temp_file_does_not_write_through_a_pre_planted_symlink() {
        let dir = run_dir();
        let victim = dir.0.join("victim");
        let link = dir.0.join("symlink");
        fs::write(&victim, b"important").unwrap();
        std::os::unix::fs::symlink(&victim, &link).unwrap();

        let f = create_temp_file(&link).unwrap();
        drop(f);
        // The symlink was unlinked (remove-first) and a fresh regular file created —
        // the victim it pointed at is untouched, not truncated through the link.
        assert_eq!(
            fs::read(&victim).unwrap(),
            b"important",
            "victim must be untouched"
        );
        assert!(
            !fs::symlink_metadata(&link)
                .unwrap()
                .file_type()
                .is_symlink(),
            "link must now be a fresh regular file, not a symlink"
        );
    }
}
