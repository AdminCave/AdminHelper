// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::io::Write;

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

/// The answer to an authenticated GET of `path` as `T`. A status other than 2xx is an error
/// that names the status, not the answer.
async fn fetch_json<T: serde::de::DeserializeOwned>(
    session: &SessionState,
    path: &str,
) -> Result<T, AppError> {
    let (response, _) = crate::auth::authenticated_get(session, path).await?;
    let status = response.status();
    if !status.is_success() {
        return Err(AppError::Validation(format!(
            "the playbook could not be loaded ({status})"
        )));
    }
    Ok(response.json().await?)
}

/// A run of `playbook` on `targets`: writes the inventory and the playbook, then hands both
/// paths to `launch` ([`launch_ansible`] in the app). If a step fails, the files written so far
/// go, also when `launch` rejected their paths: they are this run's own. After a launch that
/// succeeded, they are left to the run.
pub fn run(
    targets: &[AnsibleTarget],
    playbook: &Playbook,
    launch: impl FnOnce(&str, &str) -> Result<(), AppError>,
) -> Result<(), AppError> {
    let inventory = generate_inventory(targets)?;
    let playbook_path = match write_playbook_temp(&playbook.filename, &playbook.content) {
        Ok(path) => path,
        Err(e) => {
            let _ = std::fs::remove_file(&inventory);
            return Err(e);
        }
    };
    let launched = launch(&inventory, &playbook_path);
    if launched.is_err() {
        let _ = std::fs::remove_file(&inventory);
        let _ = std::fs::remove_file(&playbook_path);
    }
    launched
}

/// Creates a fresh temp file for our ansible scratch data. On Unix it is created
/// 0600 (the shared /tmp is world-readable), and everywhere `create_new` (O_EXCL)
/// refuses to follow a pre-planted symlink at the predictable path. A stale file from
/// our own prior run is cleared first; a racing local attacker can then only cause the
/// O_EXCL open to fail, not overwrite a victim path or read the contents (3.55).
fn create_temp_file(path: &std::path::Path) -> std::io::Result<std::fs::File> {
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

/// Generates an Ansible inventory file in INI format and returns the path.
pub fn generate_inventory(servers: &[AnsibleTarget]) -> Result<String, AppError> {
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

    // process::id() alone is identical for every generate_inventory call in one process, so two
    // concurrent inventories (parallel ansible runs, or the test suite) race on the same temp file —
    // one caller's create_temp_file collides with another's write/remove. A per-call sequence makes
    // each inventory's temp file unique; the "adminhelper_ansible" prefix is kept so the path still
    // passes is_confined_ansible_path.
    static INVENTORY_SEQ: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let seq = INVENTORY_SEQ.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let path = std::env::temp_dir().join(format!(
        "adminhelper_ansible_inventory_{}_{}.ini",
        std::process::id(),
        seq
    ));
    let mut file = create_temp_file(&path)?;
    file.write_all(content.as_bytes())?;

    Ok(path.to_string_lossy().to_string())
}

/// Writes the playbook content to a temporary file and returns the path.
pub fn write_playbook_temp(filename: &str, content: &str) -> Result<String, AppError> {
    let safe_name = filename
        .replace(['/', '\\'], "_")
        .replace("..", "_")
        .trim()
        .to_string();
    // Pid and sequence as in generate_inventory: by name alone, a second write of the same
    // playbook (another workspace process or another run) would replace the file a terminal of the
    // first is about to run, against the first one's inventory. They go before the name, so the
    // name keeps its extension.
    static PLAYBOOK_SEQ: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let seq = PLAYBOOK_SEQ.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let path = std::env::temp_dir().join(format!(
        "adminhelper_ansible_{}_{}_{}",
        std::process::id(),
        seq,
        safe_name
    ));
    let mut file = create_temp_file(&path)?;
    file.write_all(content.as_bytes())?;

    Ok(path.to_string_lossy().to_string())
}

/// True only for one of our own ansible temp files: after resolving symlinks and
/// `..`, the path must sit directly inside the system temp dir and carry our
/// `adminhelper_ansible` prefix. So `ansible-playbook` only gets such files, and a
/// failed start (`launch_ansible_with`) only deletes such files. It does not check
/// what a playbook says: `write_playbook_temp` writes the content as
/// [`fetch_playbook`] loaded it from the signed-in server.
fn is_confined_ansible_path(path: &str) -> bool {
    let canon = match std::fs::canonicalize(path) {
        Ok(p) => p,
        Err(_) => return false,
    };
    let temp = match std::fs::canonicalize(std::env::temp_dir()) {
        Ok(p) => p,
        Err(_) => return false,
    };
    if canon.parent() != Some(temp.as_path()) {
        return false;
    }
    canon
        .file_name()
        .and_then(|name| name.to_str())
        .map(|name| name.starts_with("adminhelper_ansible"))
        .unwrap_or(false)
}

/// Starts ansible-playbook in a native terminal.
pub fn launch_ansible(inventory_path: &str, playbook_path: &str) -> Result<(), AppError> {
    launch_ansible_with(inventory_path, playbook_path, start_in_terminal)
}

/// `launch_ansible` with the start passed in. A start that fails takes both files with it, as no
/// run will; a path that fails the check is never removed, it may not be ours.
fn launch_ansible_with(
    inventory_path: &str,
    playbook_path: &str,
    start: impl FnOnce(&str, &str) -> Result<(), AppError>,
) -> Result<(), AppError> {
    if !is_confined_ansible_path(inventory_path) || !is_confined_ansible_path(playbook_path) {
        return Err(AppError::Validation(
            "Ansible-Pfad ausserhalb des erlaubten Temp-Verzeichnisses".to_string(),
        ));
    }
    let started = start(inventory_path, playbook_path);
    if started.is_err() {
        let _ = std::fs::remove_file(inventory_path);
        let _ = std::fs::remove_file(playbook_path);
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

/// The `bash -c` script of a Linux run. It removes both files once ansible-playbook ends,
/// whatever its exit code. On SIGHUP (terminal closed mid-run) or SIGTERM bash would die at once
/// and run the EXIT trap while ansible-playbook may still be running; trapping both to `exit`
/// defers that, as bash runs such a trap only after the foreground ansible-playbook has ended.
/// INT stays untrapped: bash runs an INT trap even when ansible-playbook caught Ctrl-C itself, so
/// `exit` there would close the terminal over its output, and on SIGINT bash waits for
/// ansible-playbook anyway and, if that died of it, runs the EXIT trap (the Ctrl-C test pins
/// both).
fn linux_run_script(inventory_path: &str, playbook_path: &str) -> String {
    let inventory = shell_escape(inventory_path);
    let playbook = shell_escape(playbook_path);
    format!(
        "ah_cleanup() {{ rm -f -- {inventory} {playbook}; }}; \
         trap ah_cleanup EXIT; trap exit HUP TERM; \
         ansible-playbook -i {inventory} {playbook}; ah_cleanup; \
         echo ''; echo 'Ansible beendet. Druecke Enter zum Schliessen.'; read"
    )
}

#[cfg(test)]
mod tests {
    use super::{
        create_temp_file, fetch_playbook, generate_inventory, is_confined_ansible_path,
        launch_ansible_with, write_playbook_temp, AnsibleTarget,
    };
    use crate::error::AppError;
    use crate::session::SessionState;
    use std::fs;
    use std::path::Path;
    use std::sync::{Arc, Mutex};

    fn one_target() -> Vec<AnsibleTarget> {
        vec![AnsibleTarget {
            hostname: "web01".to_string(),
            groups: vec!["web".to_string()],
        }]
    }

    const PLAYBOOK_ID: &str = "0b6f2c1e-8a4d-4c3b-9e7f-1a2b3c4d5e6f";

    /// Serve HTTP on a fresh loopback port, one request per connection: the n-th request gets
    /// the n-th of `replies` (status line and body), a request after them its connection closed
    /// unanswered. The request line of every request lands in the log.
    async fn serve(replies: Vec<(&'static str, String)>) -> (String, Arc<Mutex<Vec<String>>>) {
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
                if let Some((status, body)) = replies.next() {
                    let reply = format!(
                        "HTTP/1.1 {status}\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
                        body.len()
                    );
                    tcp.write_all(reply.as_bytes()).await.unwrap();
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

    /// A directory holding a stub `ansible-playbook`: it runs `before`, records its arguments in
    /// `args` (only if both files exist while it runs), then runs `then`. A test acts once `args`
    /// is there, so what must hold by then (a trap) goes in `before`.
    #[cfg(unix)]
    fn stub_ansible_playbook(case: &str, before: &str, then: &str) -> std::path::PathBuf {
        use crate::terminal::shell_escape;
        use std::os::unix::fs::PermissionsExt;
        let dir =
            std::env::temp_dir().join(format!("ah-ansible-stub-{case}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let args = shell_escape(dir.join("args").to_str().unwrap());
        let partial = shell_escape(dir.join("args.partial").to_str().unwrap());
        let stub = dir.join("ansible-playbook");
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
            let inventory = generate_inventory(&one_target()).unwrap();
            let playbook = write_playbook_temp("it's a run.yml", "- hosts: all\n").unwrap();

            let status = run_script_command(&stub, &inventory, &playbook)
                .status()
                .unwrap();
            let args = fs::read_to_string(stub.join("args")).unwrap_or_default();
            let left = (
                Path::new(&inventory).exists(),
                Path::new(&playbook).exists(),
            );
            let _ = fs::remove_file(&inventory);
            let _ = fs::remove_file(&playbook);
            let _ = fs::remove_dir_all(&stub);

            assert_eq!(
                args,
                format!("-i {inventory} {playbook}\n"),
                "the stub did not run on both files (exit {code}, bash {status})"
            );
            assert_eq!(left, (false, false), "files left after exit {code}");
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
        let inventory = generate_inventory(&one_target()).unwrap();
        let playbook = write_playbook_temp(&format!("{case}.yml"), "- hosts: all\n").unwrap();

        let mut child = run_script_command(&stub, &inventory, &playbook)
            .stdout(std::process::Stdio::piped())
            .process_group(0)
            .spawn()
            .unwrap();
        let group = format!("-{}", child.id());
        let marker = stub.join("args");
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
            let _ = child.wait();
        }
        let mut stdout = String::new();
        let _ = child.stdout.take().unwrap().read_to_string(&mut stdout);
        let left = (
            Path::new(&inventory).exists(),
            Path::new(&playbook).exists(),
        );
        let _ = fs::remove_file(&inventory);
        let _ = fs::remove_file(&playbook);
        let _ = fs::remove_dir_all(&stub);
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
        let inventory = generate_inventory(&one_target()).unwrap();
        let playbook = write_playbook_temp("failed_start.yml", "- hosts: all\n").unwrap();

        let mut seen = None;
        let result = launch_ansible_with(&inventory, &playbook, |inv, pb| {
            seen = Some((inv.to_string(), pb.to_string()));
            Err(AppError::Connection("Kein Terminal gefunden".to_string()))
        });
        let left = (
            Path::new(&inventory).exists(),
            Path::new(&playbook).exists(),
        );
        let _ = fs::remove_file(&inventory);
        let _ = fs::remove_file(&playbook);

        assert!(matches!(result, Err(AppError::Connection(_))), "{result:?}");
        assert_eq!(seen, Some((inventory.clone(), playbook.clone())));
        assert_eq!(left, (false, false), "files left after a failed start");
    }

    #[test]
    fn launch_ansible_leaves_the_files_to_the_run_when_the_start_succeeds() {
        // The terminal starts asynchronously and reads both files later: removing them on a
        // successful start would break every run.
        let inventory = generate_inventory(&one_target()).unwrap();
        let playbook = write_playbook_temp("started.yml", "- hosts: all\n").unwrap();

        let result = launch_ansible_with(&inventory, &playbook, |_, _| Ok(()));
        let left = (
            Path::new(&inventory).exists(),
            Path::new(&playbook).exists(),
        );
        let _ = fs::remove_file(&inventory);
        let _ = fs::remove_file(&playbook);

        assert!(result.is_ok(), "{result:?}");
        assert_eq!(left, (true, true), "files gone after a successful start");
    }

    #[test]
    fn launch_ansible_never_removes_a_path_that_fails_the_check() {
        let foreign =
            std::env::temp_dir().join(format!("evil_playbook_keep_{}.yml", std::process::id()));
        fs::write(&foreign, b"- hosts: all\n").unwrap();
        let inventory = generate_inventory(&one_target()).unwrap();

        let mut started = false;
        let result = launch_ansible_with(&inventory, foreign.to_str().unwrap(), |_, _| {
            started = true;
            Err(AppError::Connection("Kein Terminal gefunden".to_string()))
        });
        let left = (Path::new(&inventory).exists(), foreign.exists());
        let _ = fs::remove_file(&inventory);
        let _ = fs::remove_file(&foreign);

        assert!(matches!(result, Err(AppError::Validation(_))), "{result:?}");
        assert!(!started, "started despite a rejected path");
        assert_eq!(
            left,
            (true, true),
            "a file was removed after a rejected path"
        );
    }

    #[test]
    fn generate_inventory_rejects_host_and_group_injection() {
        // 4.91: a hostname with a newline or a group name with [/] must be rejected — otherwise it
        // injects extra inventory lines or group headers into the INI.
        let bad_host = vec![AnsibleTarget {
            hostname: "host\nevil ansible_connection=local".to_string(),
            groups: vec![],
        }];
        assert!(generate_inventory(&bad_host).is_err());

        let bad_group = vec![AnsibleTarget {
            hostname: "host".to_string(),
            groups: vec!["[evil]".to_string()],
        }];
        assert!(generate_inventory(&bad_group).is_err());

        // A clean target still passes.
        let ok = vec![AnsibleTarget {
            hostname: "web01.example.com".to_string(),
            groups: vec!["web".to_string()],
        }];
        let path = generate_inventory(&ok).unwrap();
        let _ = fs::remove_file(path);
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
        let path = generate_inventory(&targets).unwrap();
        let content = fs::read_to_string(&path).unwrap();
        let _ = fs::remove_file(&path);
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
        // Path separators and .. in the filename must be neutralized so the written playbook stays a
        // confined adminhelper_ansible temp file (an unconfined path is RCE via ansible-playbook).
        let path = write_playbook_temp("../../etc/passwd", "- hosts: all\n").unwrap();
        assert!(
            is_confined_ansible_path(&path),
            "traversal filename escaped temp: {path}"
        );
        assert!(!path.contains(".."), "'..' not sanitized: {path}");
        let _ = fs::remove_file(&path);
    }

    #[test]
    fn per_process_playbooks_of_one_name_get_a_file_each() {
        // Two workspace processes (or two runs in one) write the same playbook name: the second
        // write must not replace the file a terminal of the first is about to run.
        let first = write_playbook_temp("per_process_site.yml", "- hosts: first\n").unwrap();
        let second = write_playbook_temp("per_process_site.yml", "- hosts: second\n").unwrap();
        let contents = (fs::read_to_string(&first), fs::read_to_string(&second));
        let confined = (
            is_confined_ansible_path(&first),
            is_confined_ansible_path(&second),
        );
        let _ = fs::remove_file(&first);
        let _ = fs::remove_file(&second);

        assert_ne!(first, second, "one name, one path");
        assert!(
            first.contains(&format!("_{}_", std::process::id())),
            "no pid in {first}"
        );
        assert_eq!(contents.0.unwrap(), "- hosts: first\n");
        assert_eq!(contents.1.unwrap(), "- hosts: second\n");
        assert_eq!(confined, (true, true), "{first} / {second}");
        assert!(
            first.ends_with("_per_process_site.yml"),
            "the name stays last: {first}"
        );
    }

    #[test]
    fn confines_ansible_paths_to_own_temp_files() {
        let dir = std::env::temp_dir();
        let pid = std::process::id();

        // One of our own temp files: accepted.
        let ours = dir.join(format!("adminhelper_ansible_confine_test_{pid}.yml"));
        fs::write(&ours, b"- hosts: all\n").unwrap();
        assert!(is_confined_ansible_path(ours.to_str().unwrap()));

        // A real temp file without our prefix: rejected.
        let foreign = dir.join(format!("evil_playbook_{pid}.yml"));
        fs::write(&foreign, b"- hosts: all\n").unwrap();
        assert!(!is_confined_ansible_path(foreign.to_str().unwrap()));

        // A traversal escape out of temp resolving to an existing file: rejected.
        let escape = dir.join(format!("adminhelper_ansible_{pid}/../../etc/hostname"));
        assert!(!is_confined_ansible_path(escape.to_str().unwrap()));

        // A non-existent path: rejected (cannot be canonicalized).
        assert!(!is_confined_ansible_path(
            dir.join("adminhelper_ansible_does_not_exist.yml")
                .to_str()
                .unwrap()
        ));

        let _ = fs::remove_file(&ours);
        let _ = fs::remove_file(&foreign);
    }

    #[test]
    fn create_temp_file_is_exclusive_and_hardened() {
        let dir = std::env::temp_dir();
        let path = dir.join(format!(
            "adminhelper_ansible_create_test_{}",
            std::process::id()
        ));
        let _ = fs::remove_file(&path);

        let f = create_temp_file(&path).unwrap();
        drop(f);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = fs::metadata(&path).unwrap().permissions().mode();
            assert_eq!(mode & 0o777, 0o600, "ansible temp file must be 0600");
        }
        // A second call over our own stale file still succeeds (remove-first).
        assert!(create_temp_file(&path).is_ok());
        let _ = fs::remove_file(&path);
    }

    #[cfg(unix)]
    #[test]
    fn create_temp_file_does_not_write_through_a_pre_planted_symlink() {
        let dir = std::env::temp_dir();
        let pid = std::process::id();
        let victim = dir.join(format!("adminhelper_ansible_victim_{pid}"));
        let link = dir.join(format!("adminhelper_ansible_symlink_{pid}"));
        let _ = fs::remove_file(&victim);
        let _ = fs::remove_file(&link);
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
        let _ = fs::remove_file(&victim);
        let _ = fs::remove_file(&link);
    }
}
