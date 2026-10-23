// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

mod ansible;
mod auth;
mod commands;
mod connection;
mod diagnostics;
mod enrollment;
mod error;
mod frpc;
mod http_client;
mod keyring_store;
mod launcher;
mod migration;
mod models;
mod notifications;
mod password;
mod port_registry;
mod proxy;
mod session;
mod storage;
mod sync;
mod terminal;
#[cfg(test)]
mod test_tls;
mod tofu;
mod tunnel;
mod validation;
mod workspace;

use commands::{
    ansible_run, api_proxy, check_server_cert, delete_password, delete_workspace, device_identity,
    enroll_with_token, export_browser_p12, fetch_connections_jwt, fetch_tunnels,
    generate_diagnostics, is_device_enrolled, list_workspaces, load_connections, load_settings,
    login, logout, open_connection, open_connection_stored, open_launcher, open_workspace,
    password_state, pinned_ca_fingerprint, refresh_tunnel, reset_device_identity,
    reset_server_cert_pin, resolve_connection, save_connections, save_password, save_settings,
    save_workspace, start_notification_stream, start_tunnel, stop_notification_stream, stop_tunnel,
    sync_connections, tunnel_status, workspace_context,
};
use tauri::plugin::TauriPlugin;
use tauri::{Emitter, Manager, WebviewUrl, WebviewWindowBuilder, Wry};
use tauri_plugin_log::{Target, TargetKind};
use workspace::{Mode, Plan};

/// The window of a workspace: as large as the one window before workspaces.
const WORKSPACE_WINDOW: (f64, f64) = (1440.0, 900.0);
/// The window of the launcher: the picker needs less room.
const LAUNCHER_WINDOW: (f64, f64) = (720.0, 560.0);

/// The log of this process: with `file`, stdout and a size-rotated `<file>.log` in the OS
/// app-log dir, which the diagnostics report of the process reads back; without, stderr alone.
/// The targets replace the plugin's own: its default file, named after the app, is the
/// launcher's log.
fn log_plugin(file: Option<String>) -> TauriPlugin<Wry> {
    let targets = match file {
        Some(file) => vec![
            Target::new(TargetKind::Stdout),
            Target::new(TargetKind::LogDir {
                file_name: Some(file),
            }),
        ],
        None => vec![Target::new(TargetKind::Stderr)],
    };
    tauri_plugin_log::Builder::new()
        .targets(targets)
        .level(log::LevelFilter::Info)
        .max_file_size(10_000_000)
        .build()
}

fn main() {
    // Route panics through the log sink (file + stdout) so a crash leaves a
    // trace in the diagnostics log, while keeping the default stderr/backtrace.
    let default_panic = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        log::error!("panic: {info}");
        default_panic(info);
    }));

    let mode = match Mode::from_args(std::env::args_os().skip(1)) {
        Ok(mode) => mode,
        Err(e) => {
            // No log yet: arguments that name no workspace name no log either.
            eprintln!("{e}");
            std::process::exit(workspace::EXIT_UNKNOWN);
        }
    };
    let launcher = mode == Mode::Launcher;

    let frpc_state = frpc::new_frpc_state();
    let frpc_state_exit = frpc_state.clone();
    let stream_state = notifications::new_stream_state();
    let stream_state_exit = stream_state.clone();

    let mut builder = tauri::Builder::default();
    if launcher {
        // Registered first so a second launch hands over and exits before any other
        // plugin or the setup runs. On Linux this needs `enableGTKAppId: false`:
        // with a GTK app id, GApplication forwards the launch itself and makes this
        // instance re-run its setup, which aborts on the existing `main` window.
        // Only in the launcher: a workspace runs in a process of its own beside the
        // others, and its lock keeps it in one.
        #[cfg(desktop)]
        {
            builder = builder.plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.unminimize();
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }));
        }
        // A log file has one writer. The plugin above lets one launcher run, so its log is
        // its own from the start; a workspace process opens its log in `setup`, once it holds
        // the workspace.
        builder = builder.plugin(log_plugin(Some(mode.log_name())));
    }

    builder
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .manage(frpc_state)
        .manage(frpc::RefreshLock::default())
        .manage(stream_state)
        .manage(session::SessionState::default())
        .setup(move |app| {
            let base = storage::app_data_dir(app.handle()).map_err(|e| e.to_string())?;
            // The migration, the workspace's lock, then the workspace: nothing before this
            // touches a workspace (`workspace::current` fails until `set_current`).
            let plan = workspace::startup(mode, &base, workspace::acquire);
            if !launcher {
                // A workspace process that did not get its workspace writes stderr alone: the
                // log of that workspace may be another process's.
                app.handle().plugin(log_plugin(plan.log_name()))?;
            }
            let (title, (width, height)) = match plan {
                Plan::Exit { code, line } => {
                    log::error!("{line}");
                    log::logger().flush();
                    std::process::exit(code);
                }
                Plan::Purge(held, meta) => {
                    // The workspace of this process, as for its window: its keyring prefix is
                    // the one the purge deletes behind. Its exit code tells the launcher how
                    // the device identity went.
                    let id = held.workspace.id.clone();
                    workspace::set_current(held).map_err(|e| e.to_string())?;
                    let code = match launcher::purge(&base, meta.as_ref(), |url| {
                        tauri::async_runtime::block_on(enrollment::reset_identity(url))
                    }) {
                        Ok(outcome) => {
                            log::info!("the workspace {id} is deleted ({outcome:?})");
                            launcher::purge_exit_code(outcome)
                        }
                        Err(e) => {
                            // The purge names a file that does not load and where it breaks;
                            // serde would quote the value it rejects, and no value from a file
                            // goes to the log.
                            let reason = match &e {
                                error::AppError::Json(_) => workspace::failure(&e),
                                _ => e.to_string(),
                            };
                            log::error!("the workspace {id} was not deleted: {reason}");
                            workspace::EXIT_FAILED
                        }
                    };
                    log::logger().flush();
                    std::process::exit(code);
                }
                Plan::Launcher => {
                    // After the migration, which hands the entries from before workspaces on.
                    if let Err(e) = launcher::drop_orphan_ports(&base) {
                        log::warn!(
                            "the port map keeps the entries of removed workspaces: {}",
                            workspace::failure(&e)
                        );
                    }
                    (workspace::LAUNCHER_TITLE.to_string(), LAUNCHER_WINDOW)
                }
                Plan::Workspace(held) => {
                    let title = held.workspace.window_title();
                    workspace::set_current(held).map_err(|e| e.to_string())?;
                    (title, WORKSPACE_WINDOW)
                }
            };
            // The session lives in the process now; drop what earlier versions left in the
            // keyring. Off the main thread: a keyring that hangs must not hold the window.
            tauri::async_runtime::spawn_blocking(auth::forget_keyring_session);
            // A renewal that fails ends the session; the webview hears of it through this event.
            let handle = app.handle().clone();
            app.state::<session::SessionState>().on_expiry(move || {
                let _ = handle.emit("session-expired", ());
            });
            // A sign-in, a sign-out and a failed renewal end the frpc of the sign-in before, here
            // and not only through the UI. The stop retires its generation, so a reconciliation
            // under way for that sign-in starts nothing (`frpc::reconcile`).
            let frpc_state = app.state::<frpc::FrpcState>().inner().clone();
            app.state::<session::SessionState>()
                .on_sign_in_change(move || {
                    let _ = frpc::stop_frpc(&frpc_state);
                });
            // The window last, so its title is right from the first frame and a process that
            // does not start never shows one.
            let mut window = WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
                .title(title)
                .inner_size(width, height)
                .resizable(true);
            // Ensure a concrete runtime window icon in dev and production.
            if let Ok(icon) = tauri::image::Image::from_bytes(include_bytes!("../icons/icon.png")) {
                window = window.icon(icon)?;
            }
            window.build()?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            load_connections,
            load_settings,
            save_settings,
            password_state,
            save_password,
            delete_password,
            sync_connections,
            save_connections,
            open_connection,
            open_connection_stored,
            login,
            logout,
            fetch_connections_jwt,
            start_tunnel,
            refresh_tunnel,
            stop_tunnel,
            tunnel_status,
            fetch_tunnels,
            generate_diagnostics,
            resolve_connection,
            api_proxy,
            check_server_cert,
            reset_server_cert_pin,
            is_device_enrolled,
            device_identity,
            pinned_ca_fingerprint,
            reset_device_identity,
            enroll_with_token,
            export_browser_p12,
            ansible_run,
            start_notification_stream,
            stop_notification_stream,
            workspace_context,
            list_workspaces,
            save_workspace,
            delete_workspace,
            open_workspace,
            open_launcher
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(move |_app, event| {
            if let tauri::RunEvent::Exit = event {
                let _ = frpc::stop_frpc(&frpc_state_exit);
                notifications::stop(&stream_state_exit);
                // A `TERMSRV/…` entry whose time has not come goes now, not with the logon
                // session: its timer ends with the process.
                #[cfg(windows)]
                password::remove_pending_termsrv();
            }
        });
}
