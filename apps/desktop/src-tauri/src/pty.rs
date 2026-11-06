// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! Pseudo consoles of the embedded terminal (R-1069): one program per session, in a pty on Unix
//! and a ConPTY on Windows. Its output goes to a sink in blocks, then exactly one end. The
//! registry knows program, argv, environment and working directory only; SSH is one caller.
//!
//! A session outlives its sink (R-1070): a window that docks a session off or back attaches a
//! new one, which gets the last output from the session's ring buffer first. A session belongs
//! to the window that attached it last, so a window that loads anew ends only its own.

// Keystrokes pass through here, passwords among them: nothing in this module logs input or
// output, and none of it needs more than safe Rust.
#![forbid(unsafe_code)]

use std::collections::HashMap;
use std::io::{ErrorKind, Read, Write};
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{mpsc, Arc, Mutex, MutexGuard};

use portable_pty::{native_pty_system, ChildKiller, CommandBuilder, MasterPty, PtySize};

use crate::error::AppError;

/// The most a session reads, and so sends, at once.
const READ_BLOCK: usize = 64 * 1024;

/// The output a session keeps for the next sink: well over the default scrollback at 80 columns.
const RING: usize = 1024 * 1024;

/// On Windows the pseudo console asks its terminal where the cursor is (portable-pty creates it
/// with PSEUDOCONSOLE_INHERIT_CURSOR) and does not close before the answer: xterm.js answers in
/// the app, the session itself once nobody listens.
#[cfg(any(windows, test))]
const CURSOR_QUERY: &[u8] = b"\x1b[6n";
#[cfg(any(windows, test))]
const CURSOR_ANSWER: &[u8] = b"\x1b[1;1R";

#[cfg(any(windows, test))]
fn contains(haystack: &[u8], needle: &[u8]) -> bool {
    haystack.windows(needle.len()).any(|w| w == needle)
}

/// What a session sends, in this order: output as it comes, then one `Exit`, then nothing.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Output {
    Data(Vec<u8>),
    /// After the kept output an attached sink gets first: what came before is a replay, and
    /// the terminal queries in it were answered back then (a second answer would be input).
    Replayed,
    /// The exit code of the program; `None` when waiting for it failed.
    Exit(Option<u32>),
}

/// The program a session runs. No shell comes in between: `args` reach it as they are.
pub struct Spawn {
    pub program: PathBuf,
    pub args: Vec<String>,
    /// Set on top of the environment of this process.
    pub env: Vec<(String, String)>,
    pub cwd: Option<PathBuf>,
    /// A directory of the run, removed with all it holds once the program has ended; a start
    /// that fails leaves it to the caller.
    pub cleanup: Option<PathBuf>,
    /// Whether a broadcast of the snippet panel reaches the session ([`PtyRegistry::broadcast`]):
    /// an SSH session, not an Ansible run.
    pub broadcast: bool,
    /// The ControlMaster socket of an SSH session: its SFTP channel goes over it (R-1072).
    pub control_path: Option<PathBuf>,
}

/// The label of the main window, which may reach every session.
pub const MAIN: &str = "main";

/// Where the output of a session goes; false once nobody listens.
type Sink = Box<dyn FnMut(Output) -> bool + Send>;

/// What a session sent and to whom it sends now.
struct Stream {
    /// The last [`RING`] bytes of output.
    ring: std::collections::VecDeque<u8>,
    sink: Option<Sink>,
    /// The label of the window the session belongs to.
    owner: String,
    /// The exit code once the program ended, for a sink that attaches after the end.
    ended: Option<Option<u32>>,
}

impl Stream {
    fn keep(&mut self, bytes: &[u8]) {
        let bytes = &bytes[bytes.len().saturating_sub(RING)..];
        let over = (self.ring.len() + bytes.len()).saturating_sub(RING);
        self.ring.drain(..over);
        self.ring.extend(bytes);
    }

    /// Hands `out` to the sink and lets a sink go that nobody listens to; true when it took it.
    fn send(&mut self, out: Output) -> bool {
        let Some(sink) = self.sink.as_mut() else {
            return false;
        };
        if sink(out) {
            return true;
        }
        self.sink = None;
        false
    }
}

struct Session {
    stream: Mutex<Stream>,
    /// Set by a close: the session then leaves the registry at its end, listened to or not.
    closing: std::sync::atomic::AtomicBool,
    /// [`Spawn::broadcast`].
    broadcast: bool,
    /// [`Spawn::control_path`].
    #[cfg_attr(
        not(test),
        expect(dead_code, reason = "the SFTP commands (kern-terminal-2 T6) read it")
    )]
    control_path: Option<PathBuf>,
    writer: Mutex<Box<dyn Write + Send>>,
    /// Gone once the program exited: on Windows the pseudo console closes with it, and only
    /// then does the reader get its end.
    master: Mutex<Option<Box<dyn MasterPty + Send>>>,
    /// Gone once the program was waited for, so no signal goes to a process id the system may
    /// have handed on.
    killer: Mutex<Option<Box<dyn ChildKiller + Send + Sync>>>,
}

impl Session {
    fn kill(&self) {
        if let Some(killer) = lock(&self.killer).as_mut() {
            let _ = killer.kill();
        }
    }

    /// Ends the program, and the session with it once its end is in.
    fn close(&self) {
        self.closing.store(true, Ordering::SeqCst);
        self.kill();
    }
}

type Sessions = Arc<Mutex<HashMap<u64, Arc<Session>>>>;

/// The running sessions of this process (managed state). A session leaves it after its end.
#[derive(Default)]
pub struct PtyRegistry {
    next: AtomicU64,
    sessions: Sessions,
    /// The broadcast of the snippet panel, off at the start: held here, so that every window
    /// shows the warning while it is on ([`PtyRegistry::broadcast`] sends nothing while off).
    broadcasting: std::sync::atomic::AtomicBool,
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|e| e.into_inner())
}

fn size(cols: u16, rows: u16) -> PtySize {
    PtySize {
        rows: rows.max(1),
        cols: cols.max(1),
        pixel_width: 0,
        pixel_height: 0,
    }
}

fn failed(what: &str, err: impl std::fmt::Display) -> AppError {
    AppError::Connection(format!("the terminal {what}: {err}"))
}

impl PtyRegistry {
    /// Starts `spawn` in a pseudo console of `cols`×`rows` for the window `owner` and returns
    /// the id of the session. `sink` gets every block of output and then one `Exit`; when it
    /// returns false (nobody listens any more), it is let go and the program runs on, its output
    /// kept for the next sink ([`PtyRegistry::attach`]).
    pub fn open<F>(
        &self,
        spawn: Spawn,
        cols: u16,
        rows: u16,
        owner: &str,
        sink: F,
    ) -> Result<u64, AppError>
    where
        F: FnMut(Output) -> bool + Send + 'static,
    {
        let pair = native_pty_system()
            .openpty(size(cols, rows))
            .map_err(|e| failed("did not open", e))?;
        // Reader and writer first: once the program runs, nothing may fail without ending it.
        let mut reader = pair
            .master
            .try_clone_reader()
            .map_err(|e| failed("did not open", e))?;
        let writer = pair
            .master
            .take_writer()
            .map_err(|e| failed("did not open", e))?;
        let mut cmd = CommandBuilder::new(&spawn.program);
        cmd.args(&spawn.args);
        for (key, value) in &spawn.env {
            cmd.env(key, value);
        }
        if let Some(cwd) = &spawn.cwd {
            cmd.cwd(cwd);
        }
        let mut child = pair
            .slave
            .spawn_command(cmd)
            .map_err(|e| failed("did not start", e))?;
        // While this side of the slave stays open, the reader never gets its end on Unix.
        drop(pair.slave);

        let session = Arc::new(Session {
            stream: Mutex::new(Stream {
                ring: std::collections::VecDeque::new(),
                sink: Some(Box::new(sink)),
                owner: owner.to_string(),
                ended: None,
            }),
            closing: std::sync::atomic::AtomicBool::new(false),
            broadcast: spawn.broadcast,
            control_path: spawn.control_path,
            writer: Mutex::new(writer),
            master: Mutex::new(Some(pair.master)),
            killer: Mutex::new(Some(child.clone_killer())),
        });
        let id = self.next.fetch_add(1, Ordering::Relaxed) + 1;
        lock(&self.sessions).insert(id, session.clone());

        let (exited, exit_code) = mpsc::channel();
        let waited = session.clone();
        let cleanup = spawn.cleanup;
        std::thread::spawn(move || {
            let code = child.wait().ok().map(|status| status.exit_code());
            if let Some(dir) = &cleanup {
                let _ = std::fs::remove_dir_all(dir);
            }
            lock(&waited.killer).take();
            let master = lock(&waited.master).take();
            drop(master);
            let _ = exited.send(code);
        });

        let sessions = self.sessions.clone();
        std::thread::spawn(move || {
            let mut block = vec![0u8; READ_BLOCK];
            loop {
                match reader.read(&mut block) {
                    Ok(0) => break,
                    Ok(n) => {
                        let listening = {
                            let mut stream = lock(&session.stream);
                            stream.keep(&block[..n]);
                            stream.send(Output::Data(block[..n].to_vec()))
                        };
                        #[cfg(not(windows))]
                        let _ = listening;
                        #[cfg(windows)]
                        if !listening && contains(&block[..n], CURSOR_QUERY) {
                            let mut writer = lock(&session.writer);
                            let _ = writer
                                .write_all(CURSOR_ANSWER)
                                .and_then(|()| writer.flush());
                        }
                    }
                    Err(e) if e.kind() == ErrorKind::Interrupted => {}
                    // Linux answers EIO, not 0, once the slave side is closed.
                    Err(_) => break,
                }
            }
            let code = exit_code.recv().ok().flatten();
            let delivered = {
                let mut stream = lock(&session.stream);
                stream.ended = Some(code);
                stream.send(Output::Exit(code))
            };
            // An end nobody heard waits for the next sink, unless the session was closed.
            if delivered || session.closing.load(Ordering::SeqCst) {
                lock(&sessions).remove(&id);
            }
        });
        Ok(id)
    }

    fn session(&self, id: u64) -> Option<Arc<Session>> {
        lock(&self.sessions).get(&id).cloned()
    }

    /// Makes `sink` the sink of session `id`, for the window `owner`: it gets the kept output as
    /// one block (none when nothing was kept), then `Replayed`, then what follows; for a session
    /// that has ended, its end after `Replayed`. The sink before is let go.
    pub fn attach<F>(&self, id: u64, owner: &str, mut sink: F) -> Result<(), AppError>
    where
        F: FnMut(Output) -> bool + Send + 'static,
    {
        let session = self
            .session(id)
            .ok_or_else(|| AppError::Connection("the terminal session has ended".to_string()))?;
        let mut stream = lock(&session.stream);
        stream.owner = owner.to_string();
        let kept =
            stream.ring.is_empty() || sink(Output::Data(stream.ring.iter().copied().collect()));
        if !kept || !sink(Output::Replayed) {
            stream.sink = None;
            return Ok(());
        }
        if let Some(code) = stream.ended {
            stream.sink = None;
            if sink(Output::Exit(code)) {
                drop(stream);
                lock(&self.sessions).remove(&id);
            }
            return Ok(());
        }
        stream.sink = Some(Box::new(sink));
        Ok(())
    }

    /// Writes `data` to the program of session `id` as typed. May wait while the program does
    /// not read: not on the main thread.
    pub fn write(&self, id: u64, data: &[u8]) -> Result<(), AppError> {
        let session = self
            .session(id)
            .filter(|session| lock(&session.stream).ended.is_none())
            .ok_or_else(|| AppError::Connection("the terminal session has ended".to_string()))?;
        let mut writer = lock(&session.writer);
        writer.write_all(data)?;
        writer.flush()?;
        Ok(())
    }

    /// Writes `data` to the program of every running session that takes a broadcast, whichever
    /// window shows it, and returns how many it reached. A session whose write fails is not
    /// counted and does not stop the others. May wait like [`PtyRegistry::write`]: not on the
    /// main thread.
    pub fn broadcast(&self, data: &[u8]) -> u32 {
        if !self.broadcasting() {
            return 0;
        }
        // Collected first: a write may wait, and the registry stays free for the readers.
        let sessions: Vec<Arc<Session>> = lock(&self.sessions)
            .values()
            .filter(|session| session.broadcast)
            .cloned()
            .collect();
        let mut reached = 0;
        for session in sessions {
            if lock(&session.stream).ended.is_some() {
                continue;
            }
            let mut writer = lock(&session.writer);
            if writer.write_all(data).and_then(|()| writer.flush()).is_ok() {
                reached += 1;
            }
        }
        reached
    }

    /// Whether the broadcast is on.
    pub fn broadcasting(&self) -> bool {
        self.broadcasting.load(Ordering::SeqCst)
    }

    /// Switches the broadcast on or off; true when that changed it.
    pub fn set_broadcasting(&self, on: bool) -> bool {
        self.broadcasting.swap(on, Ordering::SeqCst) != on
    }

    /// Tells the program of session `id` its new size; nothing for a session that has ended.
    pub fn resize(&self, id: u64, cols: u16, rows: u16) -> Result<(), AppError> {
        let Some(session) = self.session(id) else {
            return Ok(());
        };
        if let Some(master) = lock(&session.master).as_ref() {
            master
                .resize(size(cols, rows))
                .map_err(|e| failed("did not resize", e))?;
        }
        Ok(())
    }

    /// Ends the program of session `id` (SIGHUP on Unix, as when a terminal closes); its end
    /// follows through the sink. A session whose end nobody heard leaves the registry.
    pub fn close(&self, id: u64) {
        let Some(session) = self.session(id) else {
            return;
        };
        session.close();
        if lock(&session.stream).ended.is_some() {
            lock(&self.sessions).remove(&id);
        }
    }

    /// Ends the sessions of the window `owner`: those of a webview that reloaded have nobody
    /// left to listen and would wait for input forever. Those of other windows run on.
    pub fn close_all_of(&self, owner: &str) {
        let ids: Vec<u64> = lock(&self.sessions)
            .iter()
            .filter(|(_, session)| lock(&session.stream).owner == owner)
            .map(|(id, _)| *id)
            .collect();
        for id in ids {
            self.close(id);
        }
    }

    /// The ControlMaster socket of session `id` ([`Spawn::control_path`]); `None` for a session
    /// without one or one that is not there.
    #[cfg_attr(
        not(test),
        expect(dead_code, reason = "the SFTP commands (kern-terminal-2 T6) read it")
    )]
    pub fn control_path(&self, id: u64) -> Option<PathBuf> {
        lock(&self.sessions)
            .get(&id)
            .and_then(|session| session.control_path.clone())
    }

    /// Whether session `id` is there.
    pub fn has(&self, id: u64) -> bool {
        lock(&self.sessions).contains_key(&id)
    }

    /// Gives the sessions of a window that is gone to `main`, without a sink: their programs
    /// run on and the ring keeps their output until `main` attaches or closes them.
    pub fn hand_back(&self, owner: &str) {
        for session in lock(&self.sessions).values() {
            let mut stream = lock(&session.stream);
            if stream.owner == owner {
                stream.owner = MAIN.to_string();
                stream.sink = None;
            }
        }
    }

    /// Ends the programs of all sessions, as the app exits and as the user signs out; ended
    /// ones nobody listens to go at once.
    pub fn close_all(&self) {
        let ids: Vec<u64> = lock(&self.sessions).keys().copied().collect();
        for id in ids {
            self.close(id);
        }
    }

    #[cfg(test)]
    fn len(&self) -> usize {
        lock(&self.sessions).len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{Duration, Instant};

    const WAIT: Duration = Duration::from_secs(20);

    #[cfg(unix)]
    fn shell(script: &str) -> Spawn {
        Spawn {
            program: PathBuf::from("/bin/sh"),
            args: vec!["-c".to_string(), script.to_string()],
            env: Vec::new(),
            cwd: None,
            cleanup: None,
            broadcast: false,
            control_path: None,
        }
    }

    #[cfg(windows)]
    fn shell(script: &str) -> Spawn {
        let root = std::env::var("SystemRoot").unwrap_or_else(|_| r"C:\Windows".to_string());
        Spawn {
            program: PathBuf::from(root).join("System32").join("cmd.exe"),
            args: vec!["/v:on".to_string(), "/c".to_string(), script.to_string()],
            env: Vec::new(),
            cwd: None,
            cleanup: None,
            broadcast: false,
            control_path: None,
        }
    }

    #[cfg(unix)]
    fn long_running() -> Spawn {
        shell("sleep 30")
    }

    #[cfg(windows)]
    fn long_running() -> Spawn {
        shell("ping -n 31 127.0.0.1 >nul")
    }

    fn open(registry: &PtyRegistry, spawn: Spawn) -> (u64, mpsc::Receiver<Output>) {
        open_for(registry, spawn, "main")
    }

    fn open_for(
        registry: &PtyRegistry,
        spawn: Spawn,
        owner: &str,
    ) -> (u64, mpsc::Receiver<Output>) {
        let (tx, rx) = mpsc::channel();
        let id = registry
            .open(spawn, 80, 24, owner, move |out| tx.send(out).is_ok())
            .expect("the session starts");
        (id, rx)
    }

    /// A new sink for session `id`: the kept output up to `Replayed`, its queries unanswered as
    /// they were answered back then, and the receiver of what follows.
    fn attach(registry: &PtyRegistry, id: u64, owner: &str) -> (Vec<u8>, mpsc::Receiver<Output>) {
        let (tx, rx) = mpsc::channel();
        registry
            .attach(id, owner, move |out| tx.send(out).is_ok())
            .expect("the session takes the sink");
        let mut kept = Vec::new();
        loop {
            match rx.recv_timeout(WAIT).expect("the replay ends in time") {
                Output::Data(bytes) => kept.extend_from_slice(&bytes),
                Output::Replayed => return (kept, rx),
                Output::Exit(code) => panic!("an end before the replay ended: {code:?}"),
            }
        }
    }

    /// The output that comes until `needle` is in it.
    fn until_text(
        registry: &PtyRegistry,
        id: u64,
        rx: &mpsc::Receiver<Output>,
        needle: &str,
    ) -> String {
        let mut text = Vec::new();
        while !String::from_utf8_lossy(&text).contains(needle) {
            match next(registry, id, rx) {
                Output::Data(bytes) => text.extend_from_slice(&bytes),
                Output::Exit(code) => panic!("ended before {needle:?}: {code:?}"),
                Output::Replayed => panic!("a replay to a sink that did not attach"),
            }
        }
        String::from_utf8_lossy(&text).into_owned()
    }

    /// The next message, answering a cursor query in it as xterm.js would; fails when none
    /// comes in time.
    fn next(registry: &PtyRegistry, id: u64, rx: &mpsc::Receiver<Output>) -> Output {
        let out = rx.recv_timeout(WAIT).expect("the session answers in time");
        if let Output::Data(bytes) = &out {
            if contains(bytes, CURSOR_QUERY) {
                let _ = registry.write(id, CURSOR_ANSWER);
            }
        }
        out
    }

    /// Windows: the output up to the answered cursor query, or until the pseudo console is
    /// quiet for a moment. Unix asks nothing, and a program that waits for input prints
    /// nothing first.
    fn until_ready(registry: &PtyRegistry, id: u64, rx: &mpsc::Receiver<Output>) -> Vec<u8> {
        let mut text = Vec::new();
        if cfg!(windows) {
            while !contains(&text, CURSOR_QUERY) {
                match rx.recv_timeout(Duration::from_secs(3)) {
                    Ok(Output::Data(bytes)) => {
                        if contains(&bytes, CURSOR_QUERY) {
                            let _ = registry.write(id, CURSOR_ANSWER);
                        }
                        text.extend_from_slice(&bytes);
                    }
                    Ok(Output::Exit(code)) => panic!("ended before any input: {code:?}"),
                    Ok(Output::Replayed) => panic!("a replay on a sink that was never swapped"),
                    Err(_) => break,
                }
            }
        }
        text
    }

    /// The output up to the end, after `text`, and the end.
    fn until_exit(
        registry: &PtyRegistry,
        id: u64,
        rx: &mpsc::Receiver<Output>,
        mut text: Vec<u8>,
    ) -> (String, Option<u32>) {
        loop {
            match next(registry, id, rx) {
                Output::Data(bytes) => text.extend_from_slice(&bytes),
                Output::Exit(code) => return (String::from_utf8_lossy(&text).into_owned(), code),
                Output::Replayed => panic!("a replay to a sink that did not attach"),
            }
        }
    }

    fn until_gone(registry: &PtyRegistry) {
        let deadline = Instant::now() + WAIT;
        while registry.len() > 0 {
            assert!(
                Instant::now() < deadline,
                "the session stays in the registry"
            );
            std::thread::sleep(Duration::from_millis(20));
        }
    }

    /// Nothing comes after the end, and the sink is let go.
    fn nothing_after(rx: &mpsc::Receiver<Output>) {
        assert_eq!(
            rx.recv_timeout(WAIT),
            Err(mpsc::RecvTimeoutError::Disconnected)
        );
    }

    #[test]
    fn output_comes_before_one_end_with_the_exit_code() {
        let registry = PtyRegistry::default();
        #[cfg(unix)]
        let script = "printf ah-pty-ok; exit 3";
        #[cfg(windows)]
        let script = "echo ah-pty-ok & exit 3";
        let (id, rx) = open(&registry, shell(script));
        let (text, code) = until_exit(&registry, id, &rx, Vec::new());
        assert!(text.contains("ah-pty-ok"), "output: {text:?}");
        assert_eq!(code, Some(3));
        nothing_after(&rx);
        until_gone(&registry);
    }

    #[test]
    fn input_reaches_the_program() {
        let registry = PtyRegistry::default();
        #[cfg(unix)]
        let (script, line) = ("read x; printf got:%s \"$x\"", "hello\n");
        #[cfg(windows)]
        let (script, line) = ("set /p x=&echo got:!x!", "hello\r");
        let (id, rx) = open(&registry, shell(script));
        let text = until_ready(&registry, id, &rx);
        registry
            .write(id, line.as_bytes())
            .expect("the input goes in");
        let (text, _) = until_exit(&registry, id, &rx, text);
        assert!(text.contains("got:hello"), "output: {text:?}");
        until_gone(&registry);
        assert!(registry.write(id, b"late").is_err());
    }

    #[cfg(unix)]
    #[test]
    fn resize_reaches_the_program() {
        let registry = PtyRegistry::default();
        let (id, rx) = open(&registry, shell("read x; stty size"));
        registry
            .resize(id, 101, 37)
            .expect("the resize goes through");
        registry.write(id, b"\n").expect("the input goes in");
        let (text, _) = until_exit(&registry, id, &rx, Vec::new());
        assert!(text.contains("37 101"), "output: {text:?}");
        until_gone(&registry);
    }

    #[test]
    fn close_ends_the_program_with_one_end() {
        let registry = PtyRegistry::default();
        let (id, rx) = open(&registry, long_running());
        registry
            .resize(id, 101, 37)
            .expect("a running session resizes");
        let started = Instant::now();
        registry.close(id);
        let (_, code) = until_exit(&registry, id, &rx, Vec::new());
        assert!(started.elapsed() < Duration::from_secs(10), "close ends it");
        assert_ne!(code, Some(0));
        nothing_after(&rx);
        until_gone(&registry);
        // A session that has ended takes a resize and a close without complaint.
        registry.resize(id, 80, 24).expect("nothing to resize");
        registry.close(id);
    }

    #[test]
    fn close_all_ends_every_session() {
        let registry = PtyRegistry::default();
        let (first, first_rx) = open(&registry, long_running());
        let (second, second_rx) = open(&registry, long_running());
        assert_eq!(registry.len(), 2);
        registry.close_all();
        until_exit(&registry, first, &first_rx, Vec::new());
        until_exit(&registry, second, &second_rx, Vec::new());
        until_gone(&registry);
    }

    #[test]
    fn a_sink_nobody_listens_to_is_let_go_and_the_program_runs_on() {
        let registry = PtyRegistry::default();
        #[cfg(unix)]
        let script = "printf x; read y; printf got:%s \"$y\"";
        #[cfg(windows)]
        let script = "echo x & set /p y=&echo got:!y!";
        let (tx, rx) = mpsc::channel::<()>();
        let id = registry
            .open(shell(script), 80, 24, "main", move |_| {
                let _ = tx.send(());
                false
            })
            .expect("the session starts");
        rx.recv_timeout(WAIT).expect("the first output comes");
        // The sink was called once and let go: not again for output.
        assert_eq!(
            rx.recv_timeout(Duration::from_millis(500)),
            Err(mpsc::RecvTimeoutError::Disconnected)
        );
        // The program waits for input, and a new sink gets it to the end; on Windows the
        // session answered the cursor query itself while nobody listened.
        let line: &[u8] = if cfg!(windows) {
            b"hello\r"
        } else {
            b"hello\n"
        };
        registry.write(id, line).expect("the session runs on");
        let (kept, rx) = attach(&registry, id, "main");
        let (text, _) = until_exit(&registry, id, &rx, kept);
        assert!(text.contains("got:hello"), "output: {text:?}");
        until_gone(&registry);
    }

    #[test]
    fn a_new_sink_gets_the_kept_output_then_what_follows() {
        let registry = PtyRegistry::default();
        #[cfg(unix)]
        let script = "printf before; read y; printf after";
        #[cfg(windows)]
        let script = "echo before & set /p y=&echo after";
        let (id, first) = open(&registry, shell(script));
        until_text(&registry, id, &first, "before");
        let (kept, second) = attach(&registry, id, "terminal-1");
        // The first sink is let go as the second takes over.
        nothing_after(&first);
        let kept = String::from_utf8_lossy(&kept);
        assert!(kept.contains("before"), "kept: {kept:?}");
        let line: &[u8] = if cfg!(windows) { b"\r" } else { b"\n" };
        registry.write(id, line).expect("the input goes in");
        let (text, _) = until_exit(&registry, id, &second, Vec::new());
        assert!(text.contains("after"), "output: {text:?}");
        assert!(
            !text.contains("before"),
            "the kept output came twice: {text:?}"
        );
        nothing_after(&second);
        until_gone(&registry);
    }

    #[test]
    fn an_end_nobody_heard_reaches_the_next_sink() {
        let registry = PtyRegistry::default();
        #[cfg(unix)]
        let script = "printf done; exit 4";
        #[cfg(windows)]
        let script = "echo done & exit 4";
        let (tx, rx) = mpsc::channel::<()>();
        let id = registry
            .open(shell(script), 80, 24, "main", move |_| {
                let _ = tx.send(());
                false
            })
            .expect("the session starts");
        rx.recv_timeout(WAIT).expect("the first output comes");
        // The program ends without a listener; the session waits in the registry for one.
        let deadline = Instant::now() + WAIT;
        while registry.write(id, b"").is_ok() {
            assert!(Instant::now() < deadline, "the program does not end");
            std::thread::sleep(Duration::from_millis(20));
        }
        assert_eq!(registry.len(), 1);
        let (kept, late) = attach(&registry, id, "main");
        let (text, code) = until_exit(&registry, id, &late, kept);
        assert!(text.contains("done"), "output: {text:?}");
        assert_eq!(code, Some(4));
        nothing_after(&late);
        assert_eq!(registry.len(), 0);
    }

    #[test]
    fn closing_an_ended_session_nobody_listens_to_removes_it() {
        let registry = PtyRegistry::default();
        let id = registry
            .open(shell("exit 0"), 80, 24, "main", |_| false)
            .expect("the session starts");
        let deadline = Instant::now() + WAIT;
        while registry.write(id, b"").is_ok() {
            assert!(Instant::now() < deadline, "the program does not end");
            std::thread::sleep(Duration::from_millis(20));
        }
        registry.close(id);
        assert_eq!(registry.len(), 0);
    }

    #[test]
    fn close_all_of_a_window_leaves_the_others_running() {
        let registry = PtyRegistry::default();
        let (mine, mine_rx) = open_for(&registry, long_running(), "main");
        let (theirs, theirs_rx) = open_for(&registry, long_running(), "terminal-9");
        registry.close_all_of("main");
        until_exit(&registry, mine, &mine_rx, Vec::new());
        assert_eq!(registry.len(), 1);
        assert!(registry.write(theirs, b"").is_ok(), "the other one runs on");
        // A session taken over by a window belongs to it.
        let (_, theirs_rx2) = attach(&registry, theirs, "main");
        nothing_after(&theirs_rx);
        registry.close_all_of("main");
        until_exit(&registry, theirs, &theirs_rx2, Vec::new());
        until_gone(&registry);
    }

    #[test]
    fn a_window_that_is_gone_hands_its_sessions_back_to_main() {
        let registry = PtyRegistry::default();
        let (theirs, theirs_rx) = open_for(&registry, long_running(), "terminal-3");
        let (mine, mine_rx) = open_for(&registry, long_running(), "terminal-4");
        // Windows: a pseudo console whose cursor query a listening sink never answered does
        // not close; the windows have answered it, as xterm.js does. Theirs last, right before
        // the hand back, so that no output of it waits in its sink.
        until_ready(&registry, mine, &mine_rx);
        until_ready(&registry, theirs, &theirs_rx);
        registry.hand_back("terminal-3");
        nothing_after(&theirs_rx);
        // Main's close takes the handed back session, not the other window's.
        registry.close_all_of(MAIN);
        let deadline = Instant::now() + WAIT;
        while registry.write(theirs, b"").is_ok() || registry.len() != 1 {
            assert!(
                Instant::now() < deadline,
                "the handed back session does not end"
            );
            std::thread::sleep(Duration::from_millis(20));
        }
        assert!(
            registry.write(mine, b"").is_ok(),
            "the other window's runs on"
        );
        registry.close_all();
        until_gone(&registry);
    }

    #[test]
    fn a_broadcast_reaches_the_running_sessions_that_take_it() {
        let registry = PtyRegistry::default();
        #[cfg(unix)]
        let (script, line, own_line) = ("read x; printf got:%s \"$x\"", "hello\n", "mine\n");
        #[cfg(windows)]
        let (script, line, own_line) = ("set /p x=&echo got:!x!", "hello\r", "mine\r");
        let to_all = |spawn: Spawn, owner: &str| {
            let mut spawn = spawn;
            spawn.broadcast = true;
            open_for(&registry, spawn, owner)
        };
        let (first, first_rx) = to_all(shell(script), "main");
        // A detached window's session is reached all the same.
        let (second, second_rx) = to_all(shell(script), "terminal-5");
        // Like an Ansible run: it takes no broadcast.
        let (own, own_rx) = open(&registry, shell(script));
        // Ended, but kept: nobody heard its end.
        let mut ended = shell("exit 0");
        ended.broadcast = true;
        let ended = registry
            .open(ended, 80, 24, "main", |_| false)
            .expect("the session starts");
        let deadline = Instant::now() + WAIT;
        while registry
            .session(ended)
            .is_some_and(|session| lock(&session.stream).ended.is_none())
        {
            assert!(Instant::now() < deadline, "the session does not end");
            std::thread::sleep(Duration::from_millis(20));
        }
        assert!(registry.has(ended), "an end nobody heard keeps the session");
        let first_text = until_ready(&registry, first, &first_rx);
        let second_text = until_ready(&registry, second, &second_rx);
        let own_text = until_ready(&registry, own, &own_rx);

        // Off, as at the start: nothing goes out, the line read would be this one.
        assert!(!registry.broadcasting());
        assert_eq!(
            registry.broadcast(line.replace("hello", "off").as_bytes()),
            0
        );
        assert!(registry.set_broadcasting(true));
        assert!(!registry.set_broadcasting(true), "it was on already");
        assert_eq!(registry.broadcast(line.as_bytes()), 2);

        let (text, _) = until_exit(&registry, first, &first_rx, first_text);
        assert!(text.contains("got:hello"), "output: {text:?}");
        let (text, _) = until_exit(&registry, second, &second_rx, second_text);
        assert!(text.contains("got:hello"), "output: {text:?}");
        registry
            .write(own, own_line.as_bytes())
            .expect("the input goes in");
        let (text, _) = until_exit(&registry, own, &own_rx, own_text);
        assert!(text.contains("got:mine"), "output: {text:?}");
        assert!(
            !text.contains("hello"),
            "the broadcast reached it: {text:?}"
        );
        registry.close(ended);
        until_gone(&registry);
        assert_eq!(registry.broadcast(line.as_bytes()), 0, "nobody is left");
        assert!(registry.set_broadcasting(false));
        assert!(!registry.broadcasting());
    }

    #[test]
    fn the_ring_keeps_the_last_output() {
        let mut stream = Stream {
            ring: std::collections::VecDeque::new(),
            sink: None,
            owner: String::new(),
            ended: None,
        };
        stream.keep(&vec![b'a'; RING - 1]);
        stream.keep(b"bcd");
        assert_eq!(stream.ring.len(), RING);
        assert_eq!(stream.ring.front(), Some(&b'a'));
        assert!(stream.ring.iter().rev().take(3).eq(b"dcb".iter()));
        stream.keep(&vec![b'z'; RING + 5]);
        assert_eq!(stream.ring.len(), RING);
        assert!(stream.ring.iter().all(|b| *b == b'z'));
    }

    #[test]
    fn a_program_that_does_not_start_is_refused() {
        let registry = PtyRegistry::default();
        let spawn = Spawn {
            program: std::env::temp_dir().join("ah-pty-no-such-program"),
            args: Vec::new(),
            env: Vec::new(),
            cwd: None,
            cleanup: None,
            broadcast: false,
            control_path: None,
        };
        let refused = registry.open(spawn, 80, 24, "main", |_| true);
        assert!(refused.is_err());
        assert_eq!(registry.len(), 0);
    }

    /// A fresh directory with one file in it, for `Spawn::cleanup`.
    fn run_dir(case: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("ah-pty-{case}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir(&dir).unwrap();
        std::fs::write(dir.join("inventory.ini"), "x\n").unwrap();
        dir
    }

    #[test]
    fn the_run_directory_goes_once_the_program_has_ended() {
        let registry = PtyRegistry::default();
        let dir = run_dir("cleanup-end");
        let mut spawn = shell("exit 0");
        spawn.cleanup = Some(dir.clone());
        let (id, rx) = open(&registry, spawn);
        let (_, code) = until_exit(&registry, id, &rx, Vec::new());
        assert_eq!(code, Some(0));
        assert!(!dir.exists(), "the run directory is left after the end");
    }

    #[test]
    fn a_start_that_fails_leaves_the_run_directory_to_the_caller() {
        let registry = PtyRegistry::default();
        let dir = run_dir("cleanup-refused");
        let spawn = Spawn {
            program: std::env::temp_dir().join("ah-pty-no-such-program"),
            args: Vec::new(),
            env: Vec::new(),
            cwd: None,
            cleanup: Some(dir.clone()),
            broadcast: false,
            control_path: None,
        };
        assert!(registry.open(spawn, 80, 24, "main", |_| true).is_err());
        assert!(dir.exists());
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn a_session_keeps_its_control_path() {
        let registry = PtyRegistry::default();
        let path = std::env::temp_dir().join("ah-pty-control").join("c");
        let mut spawn = long_running();
        spawn.control_path = Some(path.clone());
        let (id, _rx) = open(&registry, spawn);
        let (other, _rx_other) = open(&registry, long_running());
        assert_eq!(registry.control_path(id), Some(path));
        assert_eq!(registry.control_path(other), None);
        assert_eq!(registry.control_path(other + 1), None);
        registry.close_all();
    }

    #[test]
    fn the_environment_reaches_the_program() {
        let registry = PtyRegistry::default();
        #[cfg(unix)]
        let mut spawn = shell("printf %s \"$AH_PTY_PROBE\"");
        #[cfg(windows)]
        let mut spawn = shell("echo %AH_PTY_PROBE%");
        spawn.env = vec![("AH_PTY_PROBE".to_string(), "ah-env-ok".to_string())];
        let (id, rx) = open(&registry, spawn);
        let (text, _) = until_exit(&registry, id, &rx, Vec::new());
        assert!(text.contains("ah-env-ok"), "output: {text:?}");
    }
}
