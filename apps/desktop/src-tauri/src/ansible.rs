// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{Map, Value};

use crate::error::AppError;
use crate::models::{Connection, ConnectionKind, SshAuthMethod};
use crate::pty::Spawn;
use crate::session::SessionState;
use crate::terminal::{open_linux_terminal, open_windows_terminal, shell_escape, which};

/// A server of a run: its hostname (its name in the inventory), its tags (its groups) and the SSH
/// connection that reaches it, as the UI resolved it for Verbinden (R-1202). Without one, Ansible
/// goes to the hostname.
#[derive(Debug, serde::Deserialize)]
pub struct AnsibleTarget {
    pub hostname: String,
    pub groups: Vec<String>,
    #[serde(default)]
    pub connection: Option<Connection>,
}

/// Fails unless every target is fit for the inventory: hostname and group names as
/// [`generate_inventory`] needs them, a connection as `terminal_open_ssh` takes it (checked
/// values, an SSH connection with a host).
pub fn check_targets(targets: &[AnsibleTarget]) -> Result<(), AppError> {
    // Host + group names arrive as attacker-controllable Tauri-command params. Validate them like
    // the ssh/rdp spawn paths do: a newline or [/] once injected inventory lines or group headers
    // into the INI (4.91), and the names stay plain in the JSON too.
    for target in targets {
        crate::validation::validate_host(&target.hostname)?;
        for tag in &target.groups {
            crate::validation::validate_no_control_chars(tag, "Gruppe")?;
            if tag.contains(['[', ']']) {
                return Err(AppError::Validation("Ungueltiger Gruppenname".to_string()));
            }
        }
        if let Some(connection) = target.connection.as_ref() {
            crate::validation::validate_connection_input(connection)?;
            if connection.kind != ConnectionKind::Ssh {
                return Err(AppError::Validation(
                    "Ansible reaches a server over an SSH connection only".to_string(),
                ));
            }
            crate::validation::required(&connection.host, "Host")?;
            // Ansible renders every inventory variable as a Jinja template on this machine, so a
            // `{{ lookup('pipe', …) }}` in the user or key path would run here; Verbinden passes
            // both as plain argv. Host and jump host already exclude braces by their patterns.
            for value in [&connection.username, &connection.key_path] {
                if value.as_deref().is_some_and(|v| v.contains(['{', '}'])) {
                    return Err(AppError::Validation(
                        "User and key path of an Ansible target must not contain { or }"
                            .to_string(),
                    ));
                }
            }
        }
    }
    Ok(())
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
/// [`MAX_RESPONSE_BYTES`] or past the body deadline ([`crate::http_client::read_bounded`]) and
/// one that is no `T` are errors that never quote the answer.
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
    let body = crate::http_client::read_bounded(response, MAX_RESPONSE_BYTES, "playbook").await?;
    serde_json::from_slice(&body).map_err(|_| {
        AppError::Validation("the playbook could not be loaded (unexpected answer)".to_string())
    })
}

/// A run of `playbook` on `targets`: creates a directory of its own in the temp dir
/// ([`create_run_dir`]), writes the inventory and the playbook into it, then hands both paths to
/// `launch` ([`launch_ansible`] in the app). If a step fails, the whole directory goes, a
/// half-written file with it, also when `launch` rejected the paths: it is this run's own. After
/// a launch that succeeded, it is left to the run.
pub fn run<T>(
    targets: &[AnsibleTarget],
    playbook: &Playbook,
    launch: impl FnOnce(&str, &str) -> Result<T, AppError>,
) -> Result<T, AppError> {
    run_in(&std::env::temp_dir(), targets, playbook, launch)
}

/// [`run`] with its directory in `base` instead of the temp dir.
fn run_in<T>(
    base: &Path,
    targets: &[AnsibleTarget],
    playbook: &Playbook,
    launch: impl FnOnce(&str, &str) -> Result<T, AppError>,
) -> Result<T, AppError> {
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
/// only what the run writes.
fn create_run_dir(base: &Path) -> std::io::Result<PathBuf> {
    create_private_dir(base, RUN_DIR_PREFIX)
}

/// Creates `<prefix><pid>_<n>_<nanos>` in `base`, on Unix mode 0700, always afresh: a name that
/// exists already (a pid of an earlier process, a planted entry) gets a new one, up to 16
/// tries. The run directory of Ansible and the ControlMaster directory of the embedded
/// terminal (R-1072).
pub(crate) fn create_private_dir(base: &Path, prefix: &str) -> std::io::Result<PathBuf> {
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
            "{prefix}{}_{}_{nanos}",
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

/// The name of the inventory file in a run directory. JSON, read by the `yaml` inventory plugin
/// Ansible enables by default: values such as `ansible_ssh_common_args` keep their quotes there,
/// which INI has no clean escape for.
const INVENTORY_FILE: &str = "inventory.json";

/// Writes the Ansible inventory of `servers` (checked by [`check_targets`]) to
/// `dir/inventory.json` and returns the path: every host under `all` by its hostname, with the
/// variables of [`host_vars`], and a group per tag.
pub fn generate_inventory(dir: &Path, servers: &[AnsibleTarget]) -> Result<String, AppError> {
    check_targets(servers)?;
    let ask_pass = asks_password(servers);
    let mut hosts = Map::new();
    let mut groups: std::collections::BTreeMap<&str, Map<String, Value>> =
        std::collections::BTreeMap::new();
    for server in servers {
        let alias = server.hostname.trim();
        let vars = Value::Object(host_vars(server.connection.as_ref(), ask_pass));
        if hosts.get(alias).is_some_and(|known| *known != vars) {
            return Err(AppError::Validation(format!(
                "two servers named {alias} are reached in different ways"
            )));
        }
        hosts.insert(alias.to_string(), vars);
        // `all` holds every host already; as a child of itself Ansible rejects it as a loop.
        for tag in server.groups.iter().filter(|tag| tag.as_str() != "all") {
            groups
                .entry(tag)
                .or_default()
                .insert(alias.to_string(), Value::Object(Map::new()));
        }
    }
    let children: Map<String, Value> = groups
        .into_iter()
        .map(|(tag, members)| (tag.to_string(), serde_json::json!({ "hosts": members })))
        .collect();
    let inventory = serde_json::json!({ "all": { "hosts": hosts, "children": children } });

    let path = dir.join(INVENTORY_FILE);
    let mut file = create_temp_file(&path)?;
    file.write_all(&serde_json::to_vec_pretty(&inventory)?)?;

    Ok(path.to_string_lossy().to_string())
}

/// The variables that send Ansible where `connection` goes, as Verbinden opens it: address,
/// port other than 22, user and key if set, and the other switches of the connection quoted for
/// the `shlex` split Ansible applies to `ansible_ssh_common_args`. None without a connection,
/// unless the run has `--ask-pass` (`ask_pass`, [`asks_password`]).
fn host_vars(connection: Option<&Connection>, ask_pass: bool) -> Map<String, Value> {
    let mut vars = Map::new();
    // With `--ask-pass` Ansible hands the one password to every host and sets no switch against
    // it, so a host that does not log in with a password must not be offered it.
    let password_off = ask_pass && !connection.is_some_and(logs_in_with_password);
    let Some(connection) = connection else {
        if password_off {
            vars.insert("ansible_ssh_common_args".into(), password_off_args().into());
        }
        return vars;
    };
    let host = connection.host.as_deref().unwrap_or_default().trim();
    // ssh takes an IPv6 address bare; the brackets only keep it apart from a port elsewhere.
    let host = host
        .strip_prefix('[')
        .and_then(|inner| inner.strip_suffix(']'))
        .unwrap_or(host);
    vars.insert("ansible_host".into(), host.into());
    // Like Verbinden's `-p`: port 22 stays unset, so a port from ~/.ssh/config still applies.
    if let Some(port) = connection.port.filter(|port| *port != 22) {
        vars.insert("ansible_port".into(), port.into());
    }
    let set = |value: &Option<String>| {
        value
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(Value::from)
    };
    if let Some(user) = set(&connection.username) {
        vars.insert("ansible_user".into(), user);
    }
    if let Some(key) = set(&connection.key_path) {
        vars.insert("ansible_ssh_private_key_file".into(), key);
    }
    let switches = crate::connection::ssh::option_switches(connection);
    let mut quoted: Vec<String> = switches.iter().map(|switch| shell_escape(switch)).collect();
    if password_off {
        quoted.push(password_off_args());
    }
    if !quoted.is_empty() {
        vars.insert("ansible_ssh_common_args".into(), quoted.join(" ").into());
    }
    vars
}

/// The ssh switches that refuse a password and keyboard-interactive login.
fn password_off_args() -> String {
    "-o PasswordAuthentication=no -o KbdInteractiveAuthentication=no".to_string()
}

fn logs_in_with_password(connection: &Connection) -> bool {
    connection
        .options
        .as_ref()
        .and_then(|options| options.ssh.as_ref())
        .is_some_and(|ssh| ssh.auth_method == Some(SshAuthMethod::Password))
}

/// Writes the playbook content to `dir/playbook_<name>` and returns the path. The prefix keeps
/// any name apart from `inventory.json`. Of `filename` only ASCII letters, digits, `.`, `_` and
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

/// The switches of a run besides its files: `check` for a dry run (`--check`), `ask_pass` when
/// a target logs in with a password (`--ask-pass`, [`asks_password`]).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct RunSwitches {
    pub check: bool,
    pub ask_pass: bool,
}

/// Whether one of `targets` logs in with a password. Ansible then asks for it once in the
/// terminal of the run, as Verbinden does for its session; it serves every target of the run.
pub fn asks_password(targets: &[AnsibleTarget]) -> bool {
    targets.iter().any(|target| {
        target
            .connection
            .as_ref()
            .is_some_and(logs_in_with_password)
    })
}

/// The arguments of `ansible-playbook` for a run: the switches come after the files, so the files
/// keep their places for both ways of starting it, and `--check` comes last.
pub fn playbook_args(
    inventory_path: &str,
    playbook_path: &str,
    switches: RunSwitches,
) -> Vec<String> {
    let mut args = vec![
        "-i".to_string(),
        inventory_path.to_string(),
        playbook_path.to_string(),
    ];
    if switches.ask_pass {
        args.push("--ask-pass".to_string());
    }
    if switches.check {
        args.push("--check".to_string());
    }
    args
}

/// Starts ansible-playbook in a native terminal with `switches`.
pub fn launch_ansible(
    inventory_path: &str,
    playbook_path: &str,
    switches: RunSwitches,
) -> Result<(), AppError> {
    launch_ansible_with(inventory_path, playbook_path, |inventory, playbook| {
        start_in_terminal(inventory, playbook, switches)
    })
}

/// Starts ansible-playbook through `open` (a session of the embedded terminal) and returns what
/// `open` returns. The session removes the run directory once ansible-playbook has ended
/// (`Spawn::cleanup`); a start that fails removes it here, as [`launch_ansible`] does.
pub fn launch_ansible_in_pty<T>(
    inventory_path: &str,
    playbook_path: &str,
    switches: RunSwitches,
    open: impl FnOnce(Spawn) -> Result<T, AppError>,
) -> Result<T, AppError> {
    launch_ansible_with(inventory_path, playbook_path, |inventory, playbook| {
        let program = which("ansible-playbook").ok_or_else(not_installed)?;
        open(pty_spawn(program, inventory, playbook, switches))
    })
}

/// The session of a run in the embedded terminal: `program` on the two files, the run
/// directory (the one the inventory lies in) to remove at the end.
fn pty_spawn(
    program: PathBuf,
    inventory_path: &str,
    playbook_path: &str,
    switches: RunSwitches,
) -> Spawn {
    Spawn {
        program,
        args: playbook_args(inventory_path, playbook_path, switches),
        env: vec![("TERM".to_string(), "xterm-256color".to_string())],
        cwd: None,
        cleanup: Path::new(inventory_path).parent().map(Path::to_path_buf),
        broadcast: false,
        control_path: None,
        sftp: None,
    }
}

fn not_installed() -> AppError {
    AppError::Connection(
        "ansible-playbook wurde nicht gefunden. Bitte Ansible installieren.".to_string(),
    )
}

/// `launch_ansible` with the start passed in. Both files must lie in the same run directory
/// ([`confined_run_dir`]). A start that fails takes that directory with it, as no run will; a
/// path that fails the check is never removed, it may not be ours.
fn launch_ansible_with<T>(
    inventory_path: &str,
    playbook_path: &str,
    start: impl FnOnce(&str, &str) -> Result<T, AppError>,
) -> Result<T, AppError> {
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

fn start_in_terminal(
    inventory_path: &str,
    playbook_path: &str,
    switches: RunSwitches,
) -> Result<(), AppError> {
    if which("ansible-playbook").is_none() {
        return Err(not_installed());
    }

    if cfg!(target_os = "windows") {
        open_windows_terminal(
            "ansible-playbook",
            &playbook_args(inventory_path, playbook_path, switches),
        )
    } else {
        let bash_args = vec![
            "-c".to_string(),
            linux_run_script(inventory_path, playbook_path, switches),
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
fn linux_run_script(inventory_path: &str, playbook_path: &str, switches: RunSwitches) -> String {
    let run_dir = shell_escape(
        Path::new(inventory_path)
            .parent()
            .and_then(Path::to_str)
            .unwrap_or_default(),
    );
    let args: Vec<String> = playbook_args(inventory_path, playbook_path, switches)
        .iter()
        .map(|arg| shell_escape(arg))
        .collect();
    let args = args.join(" ");
    format!(
        "ah_cleanup() {{ rm -rf -- {run_dir}; }}; \
         trap ah_cleanup EXIT; trap exit HUP TERM; \
         ansible-playbook {args}; ah_cleanup; \
         echo ''; echo 'Ansible beendet. Druecke Enter zum Schliessen.'; read"
    )
}

#[cfg(test)]
mod tests {
    use super::{
        asks_password, check_targets, confined_run_dir, create_run_dir, create_temp_file,
        fetch_playbook, generate_inventory, launch_ansible_in_pty, launch_ansible_with,
        playbook_args, pty_spawn, run, run_in, write_playbook_temp, AnsibleTarget, Playbook,
        RunSwitches,
    };
    use crate::error::AppError;
    use crate::models::{Connection, ConnectionKind};
    use crate::session::SessionState;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::sync::{Arc, Mutex};

    fn one_target() -> Vec<AnsibleTarget> {
        vec![AnsibleTarget {
            hostname: "web01".to_string(),
            groups: vec!["web".to_string()],
            connection: None,
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
        let result: Result<(), _> =
            run(&one_target(), &site("launch_fails.yml"), |inventory, _| {
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
        switches: RunSwitches,
    ) -> std::process::Command {
        use std::process::Stdio;
        let mut dirs = vec![stub_dir.to_path_buf()];
        dirs.extend(std::env::split_paths(
            &std::env::var_os("PATH").unwrap_or_default(),
        ));
        let mut command = std::process::Command::new("bash");
        command
            .arg("-c")
            .arg(super::linux_run_script(inventory, playbook, switches))
            .env("PATH", std::env::join_paths(dirs).unwrap())
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        command
    }

    #[cfg(unix)]
    #[test]
    fn linux_run_script_removes_both_files_when_ansible_playbook_ends() {
        let plain = RunSwitches::default();
        let check = RunSwitches {
            check: true,
            ..plain
        };
        let ask_pass = RunSwitches {
            ask_pass: true,
            ..plain
        };
        let both = RunSwitches {
            check: true,
            ask_pass: true,
        };
        for (code, switches) in [(0, plain), (2, plain), (0, check), (0, ask_pass), (0, both)] {
            let stub = stub_ansible_playbook(&format!("exit{code}"), "", &format!("exit {code}"));
            let dir = run_dir();
            let inventory = generate_inventory(&dir.0, &one_target()).unwrap();
            let playbook = write_playbook_temp(&dir.0, "it's a run.yml", "- hosts: all\n").unwrap();

            let status = run_script_command(&stub.0, &inventory, &playbook, switches)
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
                format!(
                    "-i {inventory} {playbook}{}{}\n",
                    if switches.ask_pass { " --ask-pass" } else { "" },
                    if switches.check { " --check" } else { "" }
                ),
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

        let mut child = run_script_command(&stub.0, &inventory, &playbook, RunSwitches::default())
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
    fn playbook_args_add_each_switch_only_when_set_and_check_last() {
        let args =
            |check, ask_pass| playbook_args("/r/inv", "/r/pb.yml", RunSwitches { check, ask_pass });
        assert_eq!(args(false, false), ["-i", "/r/inv", "/r/pb.yml"]);
        assert_eq!(args(true, false), ["-i", "/r/inv", "/r/pb.yml", "--check"]);
        assert_eq!(
            args(false, true),
            ["-i", "/r/inv", "/r/pb.yml", "--ask-pass"]
        );
        assert_eq!(
            args(true, true),
            ["-i", "/r/inv", "/r/pb.yml", "--ask-pass", "--check"]
        );
    }

    #[test]
    fn a_pty_run_removes_its_directory_when_the_session_does_not_start() {
        let dir = run_dir();
        let inventory = generate_inventory(&dir.0, &one_target()).unwrap();
        let playbook = write_playbook_temp(&dir.0, "no_session.yml", "- hosts: all\n").unwrap();

        // Without ansible-playbook on PATH it fails before `open`; both must leave nothing.
        let result: Result<u64, AppError> =
            launch_ansible_in_pty(&inventory, &playbook, RunSwitches::default(), |_| {
                Err(AppError::Connection(
                    "the session did not start".to_string(),
                ))
            });

        assert!(matches!(result, Err(AppError::Connection(_))), "{result:?}");
        assert!(!dir.0.exists(), "{:?} left after a failed start", dir.0);
    }

    #[cfg(unix)]
    #[test]
    fn a_pty_run_gets_its_switches_and_removes_its_directory_once_it_ends() {
        use crate::pty::{Output, PtyRegistry};
        use std::sync::mpsc;
        use std::time::Duration;

        let stub = stub_ansible_playbook("pty", "", "exit 0");
        let dir = run_dir();
        let inventory = generate_inventory(&dir.0, &one_target()).unwrap();
        let playbook = write_playbook_temp(&dir.0, "in_the_tab.yml", "- hosts: all\n").unwrap();
        let registry = PtyRegistry::default();
        let (tx, rx) = mpsc::channel();

        let mut seen = None;
        launch_ansible_with(&inventory, &playbook, |inv, pb| {
            seen = Some(format!("-i {inv} {pb} --ask-pass --check\n"));
            let switches = RunSwitches {
                check: true,
                ask_pass: true,
            };
            let spawn = pty_spawn(stub.0.join("ansible-playbook"), inv, pb, switches);
            assert!(!spawn.broadcast, "a run takes no broadcast");
            registry.open(spawn, 80, 24, "main", move |out| tx.send(out).is_ok())
        })
        .unwrap();
        let code = loop {
            match rx
                .recv_timeout(Duration::from_secs(20))
                .expect("the run ends in time")
            {
                Output::Exit(code) => break code,
                Output::Data(_) | Output::Replayed => {}
            }
        };

        assert_eq!(code, Some(0));
        let args = fs::read_to_string(stub.0.join("args")).unwrap_or_default();
        assert_eq!(
            Some(args),
            seen,
            "the stub did not run on both files with --ask-pass --check"
        );
        assert!(!dir.0.exists(), "{:?} left after the run ended", dir.0);
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
        let result: Result<(), _> = launch_ansible_with(&inventory, &playbook, |inv, pb| {
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
        let result: Result<(), _> =
            launch_ansible_with(&inventory, foreign.0.to_str().unwrap(), |_, _| {
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
        let result: Result<(), _> = launch_ansible_with(&inventory, &playbook, |_, _| {
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
        // 4.91: a hostname with a newline or a group name with [/] must be rejected; both stay
        // refused for the JSON inventory as they were for the INI one.
        let dir = run_dir();
        let bad_host = vec![AnsibleTarget {
            hostname: "host\nevil ansible_connection=local".to_string(),
            groups: vec![],
            connection: None,
        }];
        assert!(generate_inventory(&dir.0, &bad_host).is_err());

        let bad_group = vec![AnsibleTarget {
            hostname: "host".to_string(),
            groups: vec!["[evil]".to_string()],
            connection: None,
        }];
        assert!(generate_inventory(&dir.0, &bad_group).is_err());

        // A clean target still passes.
        let ok = vec![AnsibleTarget {
            hostname: "web01.example.com".to_string(),
            groups: vec!["web".to_string()],
            connection: None,
        }];
        assert!(generate_inventory(&dir.0, &ok).is_ok());
    }

    #[test]
    fn generate_inventory_builds_group_sections() {
        let targets = vec![
            AnsibleTarget {
                hostname: "web01".to_string(),
                groups: vec!["web".to_string()],
                connection: None,
            },
            AnsibleTarget {
                hostname: "db01".to_string(),
                groups: vec!["db".to_string()],
                connection: None,
            },
        ];
        let dir = run_dir();
        let path = generate_inventory(&dir.0, &targets).unwrap();
        assert_eq!(Path::new(&path), dir.0.join("inventory.json"));
        let inventory: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
        assert_eq!(
            inventory,
            serde_json::json!({ "all": {
                "hosts": { "web01": {}, "db01": {} },
                "children": {
                    "db": { "hosts": { "db01": {} } },
                    "web": { "hosts": { "web01": {} } }
                }
            } })
        );
    }

    /// An SSH connection to `host` at `port` with the options `ssh` (JSON as the UI sends it).
    fn ssh_connection(host: &str, port: Option<u16>, ssh: serde_json::Value) -> Connection {
        serde_json::from_value(serde_json::json!({
            "id": "c1", "name": "web01 ssh", "kind": "ssh", "host": host, "port": port,
            "username": "ops", "domain": null, "keyPath": "/home/me/.ssh/id ed25519",
            "url": null, "notes": null, "lastUsed": null, "options": { "ssh": ssh }
        }))
        .unwrap()
    }

    fn reached(hostname: &str, groups: &[&str], connection: Connection) -> AnsibleTarget {
        AnsibleTarget {
            hostname: hostname.to_string(),
            groups: groups.iter().map(|g| g.to_string()).collect(),
            connection: Some(connection),
        }
    }

    #[test]
    fn asks_password_only_when_a_target_logs_in_with_a_password() {
        let by = |auth: &str| {
            reached(
                "web01",
                &[],
                ssh_connection("192.0.2.5", None, serde_json::json!({ "authMethod": auth })),
            )
        };
        let no_method = || {
            reached(
                "db01",
                &[],
                ssh_connection("192.0.2.6", None, serde_json::json!({})),
            )
        };
        let hostname_only = || AnsibleTarget {
            hostname: "app01".to_string(),
            groups: vec![],
            connection: None,
        };

        assert!(!asks_password(&[]));
        assert!(!asks_password(&[
            by("key"),
            by("agent"),
            no_method(),
            hostname_only()
        ]));
        assert!(asks_password(&[by("password")]));
        assert!(asks_password(&[
            hostname_only(),
            by("key"),
            no_method(),
            by("password")
        ]));
    }

    #[test]
    fn generate_inventory_sends_ansible_where_the_connection_goes() {
        let targets = vec![
            reached(
                "web01.example",
                &["web", "all"],
                ssh_connection(
                    "127.0.0.1",
                    Some(23001),
                    serde_json::json!({ "jumpHost": "jump@192.0.2.10", "authMethod": "key" }),
                ),
            ),
            reached(
                "v6",
                &[],
                ssh_connection("[2001:db8::5]", None, serde_json::json!({})),
            ),
        ];
        let dir = run_dir();
        let path = generate_inventory(&dir.0, &targets).unwrap();
        let inventory: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
        assert_eq!(
            inventory,
            serde_json::json!({ "all": {
                "hosts": {
                    "web01.example": {
                        "ansible_host": "127.0.0.1",
                        "ansible_port": 23001,
                        "ansible_user": "ops",
                        "ansible_ssh_private_key_file": "/home/me/.ssh/id ed25519",
                        "ansible_ssh_common_args": "'-o' 'ProxyJump=jump@192.0.2.10' '-o' \
                            'PreferredAuthentications=publickey' '-o' 'IdentitiesOnly=yes'"
                    },
                    "v6": {
                        "ansible_host": "2001:db8::5",
                        "ansible_user": "ops",
                        "ansible_ssh_private_key_file": "/home/me/.ssh/id ed25519"
                    }
                },
                "children": { "web": { "hosts": { "web01.example": {} } } }
            } }),
            "the tag all is no child group of all"
        );
    }

    #[test]
    fn with_ask_pass_only_password_targets_are_offered_the_password() {
        let off = "-o PasswordAuthentication=no -o KbdInteractiveAuthentication=no";
        let targets = vec![
            reached(
                "pw",
                &[],
                ssh_connection(
                    "192.0.2.5",
                    None,
                    serde_json::json!({ "authMethod": "password" }),
                ),
            ),
            reached(
                "key",
                &[],
                ssh_connection(
                    "192.0.2.6",
                    None,
                    serde_json::json!({ "authMethod": "key" }),
                ),
            ),
            reached(
                "unset",
                &[],
                ssh_connection("192.0.2.7", None, serde_json::json!({})),
            ),
            AnsibleTarget {
                hostname: "bare".to_string(),
                groups: vec![],
                connection: None,
            },
        ];
        let common_args = |targets: &[AnsibleTarget]| {
            let dir = run_dir();
            let path = generate_inventory(&dir.0, targets).unwrap();
            let inventory: serde_json::Value =
                serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
            ["pw", "key", "unset", "bare"]
                .iter()
                .filter_map(|host| {
                    inventory["all"]["hosts"]
                        .get(*host)
                        .map(|vars| (*host, vars.clone()))
                })
                .map(|(host, vars)| {
                    (
                        host,
                        vars["ansible_ssh_common_args"].as_str().map(str::to_string),
                    )
                })
                .collect::<Vec<_>>()
        };

        let with_password = common_args(&targets);
        assert_eq!(
            with_password,
            [
                (
                    "pw",
                    Some(
                        "'-o' 'PreferredAuthentications=password,keyboard-interactive'".to_string()
                    )
                ),
                (
                    "key",
                    Some(format!(
                        "'-o' 'PreferredAuthentications=publickey' '-o' 'IdentitiesOnly=yes' {off}"
                    ))
                ),
                ("unset", Some(off.to_string())),
                ("bare", Some(off.to_string())),
            ]
        );

        let without_password = common_args(&targets[1..]);
        assert_eq!(
            without_password,
            [
                (
                    "key",
                    Some(
                        "'-o' 'PreferredAuthentications=publickey' '-o' 'IdentitiesOnly=yes'"
                            .to_string()
                    )
                ),
                ("unset", None),
                ("bare", None),
            ],
            "without --ask-pass the inventory stays as it was"
        );
    }

    #[test]
    fn generate_inventory_rejects_what_verbinden_would_not_open() {
        let dir = run_dir();
        let mut rdp = ssh_connection("192.0.2.7", None, serde_json::json!({}));
        rdp.kind = ConnectionKind::Rdp;
        let mut no_host = ssh_connection("192.0.2.7", None, serde_json::json!({}));
        no_host.host = Some("  ".to_string());
        let mut bad_user = ssh_connection("192.0.2.7", None, serde_json::json!({}));
        bad_user.username = Some("ops\nevil".to_string());
        let bad_option = ssh_connection(
            "192.0.2.7",
            None,
            serde_json::json!({ "jumpHost": "-oProxyCommand=evil" }),
        );
        let mut jinja_user = ssh_connection("192.0.2.7", None, serde_json::json!({}));
        jinja_user.username = Some("{{ lookup('pipe','id') }}".to_string());
        let mut jinja_key = ssh_connection("192.0.2.7", None, serde_json::json!({}));
        jinja_key.key_path = Some("/k/{% if 1 %}x{% endif %}".to_string());
        let mut brace_key = ssh_connection("192.0.2.7", None, serde_json::json!({}));
        brace_key.key_path = Some("/k/}".to_string());
        for connection in [
            rdp, no_host, bad_user, bad_option, jinja_user, jinja_key, brace_key,
        ] {
            let targets = vec![reached("web01", &[], connection)];
            assert!(
                check_targets(&targets).is_err(),
                "{:?}",
                targets[0].connection
            );
            assert!(generate_inventory(&dir.0, &targets).is_err());
        }
        assert!(
            fs::read_dir(&dir.0).unwrap().next().is_none(),
            "nothing was written"
        );
    }

    #[test]
    fn generate_inventory_rejects_one_name_reached_two_ways() {
        let dir = run_dir();
        let one = ssh_connection("192.0.2.7", None, serde_json::json!({}));
        let other = ssh_connection("192.0.2.8", None, serde_json::json!({}));
        let same = vec![
            reached("web01", &["a"], one.clone()),
            reached("web01", &["b"], one.clone()),
        ];
        assert!(generate_inventory(&dir.0, &same).is_ok());
        let fresh = run_dir();
        let split = vec![reached("web01", &[], one), reached("web01", &[], other)];
        assert!(generate_inventory(&fresh.0, &split).is_err());
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
