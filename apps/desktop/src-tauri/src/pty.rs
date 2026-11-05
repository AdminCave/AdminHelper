// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! Pseudo consoles of the embedded terminal (R-1069): one program per session, in a pty on Unix
//! and a ConPTY on Windows. Its output goes to a sink in blocks, then exactly one end. The
//! registry knows program, argv, environment and working directory only; SSH is one caller.

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

/// What a session sends, in this order: output as it comes, then one `Exit`, then nothing.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Output {
    Data(Vec<u8>),
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
}

struct Session {
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
}

type Sessions = Arc<Mutex<HashMap<u64, Arc<Session>>>>;

/// The running sessions of this process (managed state). A session leaves it after its end.
#[derive(Default)]
pub struct PtyRegistry {
    next: AtomicU64,
    sessions: Sessions,
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
    /// Starts `spawn` in a pseudo console of `cols`×`rows` and returns the id of the session.
    /// `sink` gets every block of output and then one `Exit`; when it returns false (nobody
    /// listens any more), the session ends the program and sends nothing more.
    pub fn open<F>(&self, spawn: Spawn, cols: u16, rows: u16, mut sink: F) -> Result<u64, AppError>
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
            writer: Mutex::new(writer),
            master: Mutex::new(Some(pair.master)),
            killer: Mutex::new(Some(child.clone_killer())),
        });
        let id = self.next.fetch_add(1, Ordering::Relaxed) + 1;
        lock(&self.sessions).insert(id, session.clone());

        let (exited, exit_code) = mpsc::channel();
        let waited = session.clone();
        std::thread::spawn(move || {
            let code = child.wait().ok().map(|status| status.exit_code());
            lock(&waited.killer).take();
            let master = lock(&waited.master).take();
            drop(master);
            let _ = exited.send(code);
        });

        let sessions = self.sessions.clone();
        std::thread::spawn(move || {
            let mut block = vec![0u8; READ_BLOCK];
            let mut listening = true;
            loop {
                match reader.read(&mut block) {
                    Ok(0) => break,
                    Ok(n) => {
                        // Read on to the end even when nobody listens: on Windows the pseudo
                        // console may only close once its output is drained.
                        if listening && !sink(Output::Data(block[..n].to_vec())) {
                            listening = false;
                            session.kill();
                        }
                    }
                    Err(e) if e.kind() == ErrorKind::Interrupted => {}
                    // Linux answers EIO, not 0, once the slave side is closed.
                    Err(_) => break,
                }
            }
            let code = exit_code.recv().ok().flatten();
            if listening {
                sink(Output::Exit(code));
            }
            lock(&sessions).remove(&id);
        });
        Ok(id)
    }

    fn session(&self, id: u64) -> Option<Arc<Session>> {
        lock(&self.sessions).get(&id).cloned()
    }

    /// Writes `data` to the program of session `id` as typed. May wait while the program does
    /// not read: not on the main thread.
    pub fn write(&self, id: u64, data: &[u8]) -> Result<(), AppError> {
        let session = self
            .session(id)
            .ok_or_else(|| AppError::Connection("the terminal session has ended".to_string()))?;
        let mut writer = lock(&session.writer);
        writer.write_all(data)?;
        writer.flush()?;
        Ok(())
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
    /// follows through the sink. Nothing for a session that has ended.
    pub fn close(&self, id: u64) {
        if let Some(session) = self.session(id) {
            session.kill();
        }
    }

    /// Ends the programs of all sessions: those of a webview that reloaded have nobody left to
    /// listen and would wait for input forever.
    pub fn close_all(&self) {
        let sessions: Vec<Arc<Session>> = lock(&self.sessions).values().cloned().collect();
        for session in sessions {
            session.kill();
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

    /// ConPTY asks its terminal where the cursor is and may hold the program's output until the
    /// answer comes; xterm.js answers it in the app, the tests answer it here.
    const CURSOR_QUERY: &[u8] = b"\x1b[6n";
    const CURSOR_ANSWER: &[u8] = b"\x1b[1;1R";

    #[cfg(unix)]
    fn shell(script: &str) -> Spawn {
        Spawn {
            program: PathBuf::from("/bin/sh"),
            args: vec!["-c".to_string(), script.to_string()],
            env: Vec::new(),
            cwd: None,
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
        let (tx, rx) = mpsc::channel();
        let id = registry
            .open(spawn, 80, 24, move |out| tx.send(out).is_ok())
            .expect("the session starts");
        (id, rx)
    }

    fn contains(haystack: &[u8], needle: &[u8]) -> bool {
        haystack.windows(needle.len()).any(|w| w == needle)
    }

    /// The next message, answering a cursor query in it; fails when none comes in time.
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
    fn a_sink_nobody_listens_to_ends_the_program() {
        let registry = PtyRegistry::default();
        #[cfg(unix)]
        let script = "printf x; sleep 30";
        #[cfg(windows)]
        let script = "echo x & ping -n 31 127.0.0.1 >nul";
        let (tx, rx) = mpsc::channel::<()>();
        registry
            .open(shell(script), 80, 24, move |_| {
                let _ = tx.send(());
                false
            })
            .expect("the session starts");
        rx.recv_timeout(WAIT).expect("the first output comes");
        // Without the kill the program would run its 30 s and keep the session.
        let started = Instant::now();
        until_gone(&registry);
        assert!(
            started.elapsed() < Duration::from_secs(10),
            "the kill ends it"
        );
        // The sink was called once: not again for output, not for the end.
        assert_eq!(
            rx.recv_timeout(WAIT),
            Err(mpsc::RecvTimeoutError::Disconnected)
        );
    }

    #[test]
    fn a_program_that_does_not_start_is_refused() {
        let registry = PtyRegistry::default();
        let spawn = Spawn {
            program: std::env::temp_dir().join("ah-pty-no-such-program"),
            args: Vec::new(),
            env: Vec::new(),
            cwd: None,
        };
        let refused = registry.open(spawn, 80, 24, |_| true);
        assert!(refused.is_err());
        assert_eq!(registry.len(), 0);
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
