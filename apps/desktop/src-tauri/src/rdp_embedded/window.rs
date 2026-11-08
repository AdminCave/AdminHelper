// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! A detached RDP tab (R-1101): session `rdp-<n>` opens in a window of the same label, at the UI
//! route `#/detached-rdp/<id>`; that window logs in at the session's WebSocket itself
//! (`rdp_session_attach`). The session lives in the backend all along, so the window gets the
//! whole picture at once. The capability of `rdp-*` windows limits the commands, `may_reach` the
//! sessions: main reaches every session, a detached window its own one only. A session across two
//! monitors shows its second one in window `rdp-<n>-1`, at `#/detached-rdp/<id>/1`.

use tauri::{Emitter, Manager};

use super::RdpSessions;
use crate::error::AppError;
use crate::pty::MAIN;

/// The session a detached window's `label` shows, and its screen; `None` for any other window.
fn detached_session(label: &str) -> Option<(&str, usize)> {
    let rest = label.strip_prefix("rdp-")?;
    let (n, screen) = match rest.split_once('-') {
        None => (rest, 0),
        Some((n, "1")) => (n, 1),
        Some(_) => return None,
    };
    // Only the labels `RdpSessions::add` hands out: `rdp-` and a number without a sign.
    (!n.is_empty() && n.bytes().all(|b| b.is_ascii_digit()))
        .then(|| (&label[..4 + n.len()], screen))
}

/// The label of the window that shows `screen` of session `session_id`.
fn window_label(session_id: &str, screen: usize) -> String {
    match screen {
        0 => session_id.to_string(),
        _ => format!("{session_id}-{screen}"),
    }
}

pub(super) fn may_reach(label: &str, session_id: &str) -> Result<(), AppError> {
    if label == MAIN || detached_session(label).map(|(session, _)| session) == Some(session_id) {
        Ok(())
    } else {
        Err(AppError::Validation(format!(
            "this window cannot reach RDP session {session_id}"
        )))
    }
}

/// A detached window logs in for the screen it shows only; main for either.
pub(super) fn may_show(label: &str, screen: usize) -> Result<(), AppError> {
    match detached_session(label) {
        Some((_, shown)) if shown != screen => Err(AppError::Validation(format!(
            "this window cannot show screen {screen}"
        ))),
        _ => Ok(()),
    }
}

#[derive(Clone, serde::Serialize)]
struct RdpWindow {
    session_id: String,
}

/// Opens session `session_id` in a window of its own; an open one comes to the front. `screen` 1
/// opens the window of its second monitor, on another monitor of the system than main's if
/// there is one. Async: on Windows a window built from a sync command waits on the event loop it
/// runs in.
#[tauri::command]
pub(crate) async fn rdp_detach(
    window: tauri::Window,
    session_id: String,
    title: String,
    screen: Option<u8>,
) -> Result<(), AppError> {
    if window.label() != MAIN {
        return Err(AppError::Validation(
            "only the main window detaches a session".into(),
        ));
    }
    let screen = usize::from(screen.unwrap_or(0));
    if screen >= super::frame_ws::SCREENS {
        return Err(AppError::Validation(format!("no screen {screen}")));
    }
    let app = window.app_handle();
    // The label is the session id; a started session is one `add` named.
    app.state::<RdpSessions>().info(&session_id)?;
    let label = window_label(&session_id, screen);
    if let Some(open) = app.get_webview_window(&label) {
        return open.set_focus().map_err(window_error);
    }
    let route = match screen {
        0 => format!("index.html#/detached-rdp/{session_id}"),
        _ => format!("index.html#/detached-rdp/{session_id}/{screen}"),
    };
    let mut builder =
        tauri::WebviewWindowBuilder::new(app, &label, tauri::WebviewUrl::App(route.into()))
            .title(title)
            .inner_size(1024.0, 640.0)
            .resizable(true);
    if screen == 1 {
        if let Some((x, y)) = other_monitor(&window) {
            builder = builder.position(x, y);
        }
    }
    builder.build().map(|_| ()).map_err(window_error)
}

/// The top left corner, in logical pixels, of a monitor of the system other than the one
/// `window` is on; `None` with one monitor only.
fn other_monitor(window: &tauri::Window) -> Option<(f64, f64)> {
    let current = window.current_monitor().ok().flatten();
    let monitors = window.available_monitors().ok()?;
    let other = monitors.iter().find(|monitor| {
        current
            .as_ref()
            .is_none_or(|current| monitor.position() != current.position())
    })?;
    let position = other.position().to_logical::<f64>(other.scale_factor());
    // A margin keeps the title bar clear of a panel at the monitor's edge.
    Some((position.x + 40.0, position.y + 40.0))
}

/// Closes the detached windows of session `session_id`, of both its screens, and tells main,
/// which logs in again as its tab.
#[tauri::command]
pub(crate) fn rdp_dock(window: tauri::Window, session_id: String) -> Result<(), AppError> {
    may_reach(window.label(), &session_id)?;
    let app = window.app_handle();
    for screen in 0..super::frame_ws::SCREENS {
        if let Some(detached) = app.get_webview_window(&window_label(&session_id, screen)) {
            // destroy raises no CloseRequested, so main hears of it through rdp-docked only.
            detached.destroy().map_err(window_error)?;
        }
    }
    app.emit_to(MAIN, "rdp-docked", RdpWindow { session_id })
        .map_err(window_error)
}

/// Closing a detached window through its title bar is reported to main, which takes the session
/// back as a tab (`rdp-window-closed`, the second monitor's window goes with it) or shows it on
/// one monitor again (`rdp-monitor-closed`); the session itself keeps running.
pub(crate) fn on_window_event(window: &tauri::Window, event: &tauri::WindowEvent) {
    let Some((session_id, screen)) = detached_session(window.label()) else {
        return;
    };
    if let tauri::WindowEvent::CloseRequested { .. } = event {
        let event = if screen == 0 {
            if let Some(second) = window
                .app_handle()
                .get_webview_window(&window_label(session_id, 1))
            {
                let _ = second.destroy();
            }
            "rdp-window-closed"
        } else {
            "rdp-monitor-closed"
        };
        let session_id = session_id.to_string();
        let _ = window.emit_to(MAIN, event, RdpWindow { session_id });
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
        assert_eq!(detached_session("rdp-1"), Some(("rdp-1", 0)));
        assert_eq!(detached_session("rdp-42"), Some(("rdp-42", 0)));
        assert_eq!(detached_session("rdp-11"), Some(("rdp-11", 0)));
        assert_eq!(detached_session("rdp-3-1"), Some(("rdp-3", 1)));
        assert_eq!(window_label("rdp-3", 0), "rdp-3");
        assert_eq!(window_label("rdp-3", 1), "rdp-3-1");
        for label in [
            "main",
            "rdp-",
            "rdp--1",
            "rdp-+1",
            "rdp-1a",
            "terminal-1",
            "rdp-1-2",
            "rdp-1-1-1",
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
        assert!(may_reach("rdp-1-1", "rdp-1").is_ok());
        assert!(may_reach("rdp-1-1", "rdp-2").is_err());
        assert!(may_reach("rdp-1-1", "rdp-1-1").is_err());
        assert!(may_reach("terminal-1", "rdp-1").is_err());
        assert!(may_reach("launcher", "rdp-1").is_err());
        // A session id that is no label `add` hands out reaches nothing but from main.
        assert!(may_reach("rdp-x", "rdp-x").is_err());
        assert!(may_show(MAIN, 0).is_ok() && may_show(MAIN, 1).is_ok());
        assert!(may_show("rdp-1", 0).is_ok());
        assert!(may_show("rdp-1", 1).is_err());
        assert!(may_show("rdp-1-1", 1).is_ok());
        assert!(may_show("rdp-1-1", 0).is_err());
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
        assert!(body("rdp_session_attach").contains("window::may_show(window.label(), screen)?;"));
        assert!(body("rdp_detach").contains("if window.label() != MAIN {"));
        assert!(body("rdp_dock").contains(".destroy()"));
    }
}
