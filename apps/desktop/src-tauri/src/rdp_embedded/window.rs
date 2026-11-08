// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! A detached RDP tab (R-1101): session `rdp-<n>` opens in a window of the same label, at the UI
//! route `#/detached-rdp/<id>`; that window logs in at the session's WebSocket itself
//! (`rdp_session_attach`). The session lives in the backend all along, so the window gets the
//! whole picture at once. The capability of `rdp-*` windows limits the commands, `may_reach` the
//! sessions: main reaches every session, a detached window its own one only.

use tauri::{Emitter, Manager};

use super::RdpSessions;
use crate::error::AppError;
use crate::pty::MAIN;

/// The session a detached window's `label` shows; `None` for any other window.
fn detached_session(label: &str) -> Option<&str> {
    let n = label.strip_prefix("rdp-")?;
    // Only the labels `RdpSessions::add` hands out: `rdp-` and a number without a sign.
    (!n.is_empty() && n.bytes().all(|b| b.is_ascii_digit())).then_some(label)
}

pub(super) fn may_reach(label: &str, session_id: &str) -> Result<(), AppError> {
    if label == MAIN || detached_session(label) == Some(session_id) {
        Ok(())
    } else {
        Err(AppError::Validation(format!(
            "this window cannot reach RDP session {session_id}"
        )))
    }
}

#[derive(Clone, serde::Serialize)]
struct RdpWindow {
    session_id: String,
}

/// Opens session `session_id` in a window of its own; an open one comes to the front. Async: on
/// Windows a window built from a sync command waits on the event loop it runs in.
#[tauri::command]
pub(crate) async fn rdp_detach(
    window: tauri::Window,
    session_id: String,
    title: String,
) -> Result<(), AppError> {
    if window.label() != MAIN {
        return Err(AppError::Validation(
            "only the main window detaches a session".into(),
        ));
    }
    let app = window.app_handle();
    // The label is the session id; a started session is one `add` named.
    app.state::<RdpSessions>().info(&session_id)?;
    if let Some(open) = app.get_webview_window(&session_id) {
        return open.set_focus().map_err(window_error);
    }
    let url = tauri::WebviewUrl::App(format!("index.html#/detached-rdp/{session_id}").into());
    tauri::WebviewWindowBuilder::new(app, &session_id, url)
        .title(title)
        .inner_size(1024.0, 640.0)
        .resizable(true)
        .build()
        .map(|_| ())
        .map_err(window_error)
}

/// Closes the detached window of session `session_id` and tells main, which logs in again as its
/// tab.
#[tauri::command]
pub(crate) fn rdp_dock(window: tauri::Window, session_id: String) -> Result<(), AppError> {
    may_reach(window.label(), &session_id)?;
    let app = window.app_handle();
    if let Some(detached) = app.get_webview_window(&session_id) {
        // destroy raises no CloseRequested, so main hears of it through rdp-docked only.
        detached.destroy().map_err(window_error)?;
    }
    app.emit_to(MAIN, "rdp-docked", RdpWindow { session_id })
        .map_err(window_error)
}

/// Closing a detached window through its title bar is reported to main (`rdp-window-closed`),
/// which takes the session back as a tab; the session itself keeps running.
pub(crate) fn on_window_event(window: &tauri::Window, event: &tauri::WindowEvent) {
    let Some(session_id) = detached_session(window.label()) else {
        return;
    };
    if let tauri::WindowEvent::CloseRequested { .. } = event {
        let session_id = session_id.to_string();
        let _ = window.emit_to(MAIN, "rdp-window-closed", RdpWindow { session_id });
    }
}

fn window_error(error: tauri::Error) -> AppError {
    AppError::Io(std::io::Error::other(error.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_detached_window_is_named_after_its_session() {
        assert_eq!(detached_session("rdp-1"), Some("rdp-1"));
        assert_eq!(detached_session("rdp-42"), Some("rdp-42"));
        for label in [
            "main",
            "rdp-",
            "rdp-+1",
            "rdp-1a",
            "terminal-1",
            "rdp-1-2",
            " rdp-1",
        ] {
            assert_eq!(detached_session(label), None, "{label}");
        }
    }

    #[test]
    fn main_reaches_every_session_and_a_detached_window_its_own_one() {
        assert!(may_reach(MAIN, "rdp-1").is_ok());
        assert!(may_reach(MAIN, "rdp-7").is_ok());
        assert!(may_reach("rdp-1", "rdp-1").is_ok());
        assert!(may_reach("rdp-1", "rdp-2").is_err());
        assert!(may_reach("rdp-1", "rdp-10").is_err());
        assert!(may_reach("terminal-1", "rdp-1").is_err());
        assert!(may_reach("launcher", "rdp-1").is_err());
        // A session id that is no label `add` hands out reaches nothing but from main.
        assert!(may_reach("rdp-x", "rdp-x").is_err());
    }

    // The commands an `rdp-*` window may call check which session it calls for; the capability
    // alone would let it reach every session.
    #[test]
    fn the_commands_of_a_detached_window_check_the_calling_window() {
        let source = [include_str!("mod.rs"), include_str!("window.rs")]
            .concat()
            .replace("\r\n", "\n");
        let body = |name: &str| -> String {
            let start = [
                format!("pub(crate) fn {name}("),
                format!("pub(crate) async fn {name}("),
            ]
            .iter()
            .find_map(|head| source.find(head.as_str()))
            .unwrap_or_else(|| panic!("{name} is not a command"));
            let body = &source[start..];
            body[..body.find("\n}\n").expect("end of the command")].to_string()
        };
        for name in ["rdp_session_attach", "rdp_session_stop", "rdp_dock"] {
            assert!(
                body(name).contains("may_reach(window.label(), &session_id)?;"),
                "{name} does not check the calling window"
            );
        }
        assert!(body("rdp_detach").contains("if window.label() != MAIN {"));
        assert!(body("rdp_dock").contains(".destroy()"));
    }
}
