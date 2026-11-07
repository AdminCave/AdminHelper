// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! The Windows clipboard of an embedded RDP session. `WinClipboard` listens through a hidden
//! window, whose messages arrive only on the thread that created it and only while that thread
//! pumps them; the session thread runs a tokio `LocalSet` and pumps none. So the clipboard gets a
//! thread of its own with a message loop, for as long as one connection attempt lives.

use std::sync::mpsc;
use std::thread::JoinHandle;

use ironrdp_client::rdp::{CliprdrBackendFactory, RdpInputSender};
use ironrdp_cliprdr::backend::{ClipboardMessage, ClipboardMessageProxy};
use ironrdp_cliprdr_native::WinClipboard;
use windows::Win32::Foundation::{LPARAM, WPARAM};
use windows::Win32::System::Threading::GetCurrentThreadId;
use windows::Win32::UI::WindowsAndMessaging::{
    DispatchMessageW, GetMessageW, PostThreadMessageW, TranslateMessage, MSG, WM_QUIT,
};

/// Hands what the local clipboard offers to the session, as IronRDP's own proxy does.
#[derive(Debug)]
struct Proxy(RdpInputSender);

impl ClipboardMessageProxy for Proxy {
    fn send_clipboard_message(&self, message: ClipboardMessage) {
        if self.0.send_clipboard(message).is_err() {
            log::debug!("the RDP session closed; dropped a clipboard message");
        }
    }
}

/// The clipboard thread of one attempt; dropping it ends the loop and releases the clipboard on
/// its own thread.
pub(crate) struct ClipboardThread {
    thread_id: u32,
    join: Option<JoinHandle<()>>,
}

impl ClipboardThread {
    /// Starts the thread and returns the backend factory for `RdpClient`. Without file transfer:
    /// the session carries text and pictures only (docs/features/kern-rdp-2.md).
    pub(crate) fn start(
        input: RdpInputSender,
    ) -> Result<(Self, Box<dyn CliprdrBackendFactory + Send>), String> {
        let (ready, started) = mpsc::channel();
        let join = std::thread::Builder::new()
            .name("rdp-clipboard".into())
            .spawn(move || {
                let clipboard = match WinClipboard::new(Proxy(input)) {
                    Ok(clipboard) => clipboard,
                    Err(error) => {
                        let _ = ready.send(Err(format!("{error}")));
                        return;
                    }
                };
                // SAFETY: always safe to call. The window above gave this thread its message
                // queue, so a WM_QUIT posted from now on is not lost.
                let thread_id = unsafe { GetCurrentThreadId() };
                if ready
                    .send(Ok((thread_id, clipboard.backend_factory())))
                    .is_err()
                {
                    return;
                }
                let mut message = MSG::default();
                // SAFETY: `message` is valid for writes. GetMessageW returns 0 on WM_QUIT and -1
                // on an error; both end the loop.
                while unsafe { GetMessageW(&mut message, None, 0, 0) }.0 > 0 {
                    // SAFETY: `message` was filled by GetMessageW above.
                    unsafe {
                        let _ = TranslateMessage(&message);
                        DispatchMessageW(&message);
                    }
                }
                // The window, its subclass and the listener belong to this thread.
                drop(clipboard);
            })
            .map_err(|error| format!("{error}"))?;
        match started.recv() {
            Ok(Ok((thread_id, factory))) => Ok((
                Self {
                    thread_id,
                    join: Some(join),
                },
                factory,
            )),
            Ok(Err(error)) => {
                let _ = join.join();
                Err(error)
            }
            Err(_) => {
                let _ = join.join();
                Err("the clipboard thread ended before it started".into())
            }
        }
    }
}

impl Drop for ClipboardThread {
    fn drop(&mut self) {
        // SAFETY: posting to a thread is safe from any thread.
        let posted = unsafe { PostThreadMessageW(self.thread_id, WM_QUIT, WPARAM(0), LPARAM(0)) };
        if let Err(error) = posted {
            log::warn!("could not end the RDP clipboard thread: {error}");
            return;
        }
        // A paste the server is still answering holds the loop until IronRDP gives up on it
        // (ten seconds at f96f664), since the answer would come through the session thread that
        // waits here.
        if let Some(join) = self.join.take() {
            let _ = join.join();
        }
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;

    #[test]
    fn clipboard_thread_starts_and_ends_when_dropped() {
        let (input, _events) = RdpInputSender::channel(8);
        let (thread, factory) = match ClipboardThread::start(input) {
            Ok(started) => started,
            // A runner without a desktop clipboard: start reports it, the session goes on
            // without one (start_attempt), and nothing is left to end.
            Err(error) => {
                assert!(!error.is_empty());
                return;
            }
        };
        drop(factory);
        let (ended, end) = mpsc::channel();
        std::thread::spawn(move || {
            drop(thread);
            let _ = ended.send(());
        });
        end.recv_timeout(Duration::from_secs(5))
            .expect("the clipboard thread did not end after its drop");
    }
}
