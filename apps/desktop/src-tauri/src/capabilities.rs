// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! The command list of `build.rs`, the handler of `main.rs` and the capabilities agree: with
//! `AppManifest::commands` a command needs its `allow-<command>` in the calling window's
//! capability, so one left out fails in that window only, at run time.

use std::collections::BTreeSet;

use serde_json::Value;

/// Source text with CRLF made LF: the Windows checkout has CRLF.
fn source(text: &str) -> String {
    text.replace("\r\n", "\n")
}

/// The quoted names between `const COMMANDS: &[&str] = &[` and `];` of `build.rs`.
fn build_commands() -> BTreeSet<String> {
    let text = source(include_str!("../build.rs"));
    let start = text
        .find("const COMMANDS: &[&str] = &[")
        .expect("build.rs lists COMMANDS");
    let list = &text[start..];
    let list = &list[list.find("= &[").unwrap() + 4..list.find("];").unwrap()];
    list.split(',')
        .map(|name| name.trim().trim_matches('"').to_string())
        .filter(|name| !name.is_empty())
        .collect()
}

/// The command names in `generate_handler![…]` of `main.rs`, without their module path.
fn handler_commands() -> BTreeSet<String> {
    let text = source(include_str!("main.rs"));
    let start = text
        .find("generate_handler![")
        .expect("main.rs has the handler")
        + 18;
    let list = &text[start..start + text[start..].find(']').unwrap()];
    list.split(',')
        .map(|name| name.trim().rsplit("::").next().unwrap().to_string())
        .filter(|name| !name.is_empty())
        .collect()
}

fn capability(text: &str) -> Value {
    serde_json::from_str(text).expect("the capability is JSON")
}

fn strings(value: &Value, key: &str) -> BTreeSet<String> {
    value[key]
        .as_array()
        .unwrap_or_else(|| panic!("{key} is a list"))
        .iter()
        .map(|item| item.as_str().expect("a string").to_string())
        .collect()
}

fn allowed_commands(value: &Value) -> BTreeSet<String> {
    strings(value, "permissions")
        .iter()
        .filter_map(|permission| permission.strip_prefix("allow-"))
        .map(|command| command.replace('-', "_"))
        .collect()
}

#[test]
fn build_lists_every_command_of_the_handler() {
    let built = build_commands();
    assert!(built.len() > 40, "build.rs: {built:?}");
    assert_eq!(built, handler_commands());
}

#[test]
fn the_main_window_may_call_every_command() {
    let main = capability(include_str!("../capabilities/default.json"));
    assert_eq!(
        strings(&main, "windows"),
        BTreeSet::from(["main".to_string()])
    );
    assert_eq!(allowed_commands(&main), build_commands());
}

#[test]
fn a_detached_window_may_call_the_terminal_of_its_session_and_the_settings_only() {
    let detached = capability(include_str!("../capabilities/terminal-window.json"));
    assert_eq!(
        strings(&detached, "windows"),
        BTreeSet::from(["terminal-*".to_string()])
    );
    let expected: BTreeSet<String> = [
        "load_settings",
        "terminal_attach",
        "terminal_write",
        "terminal_resize",
        "terminal_close",
        "terminal_dock",
    ]
    .map(String::from)
    .into();
    assert_eq!(allowed_commands(&detached), expected);
    let others: BTreeSet<String> = strings(&detached, "permissions")
        .into_iter()
        .filter(|permission| !permission.starts_with("allow-"))
        .collect();
    // Listening only: with emit, a script in the window could raise app events in main, such as
    // session-expired.
    assert_eq!(
        others,
        BTreeSet::from([
            "core:event:allow-listen".to_string(),
            "core:event:allow-unlisten".to_string(),
        ])
    );
}
