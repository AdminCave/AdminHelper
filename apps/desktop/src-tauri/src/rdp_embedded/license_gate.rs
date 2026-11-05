// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! License gates for the embedded RDP client (conditions 7 and 8 of docs/features/arch-rdp-embedded.md):
//! packages that must never be compiled into the desktop. aws-lc-rs/aws-lc-sys: the desktop runs
//! one TLS provider, ring, and keeps aws-lc's C build out. openh264-sys2: OpenH264 built from source
//! carries no patent licence, so H.264 stays off on Linux. IronRDP offers all of them behind
//! features (`rustls`, `udp`, `openh264`), so one feature flip in Cargo.toml would pull them in
//! silently. Cargo.lock may still list them as optional entries; what counts is the resolved build
//! graph, which `cargo tree` shows.

use std::path::Path;
use std::process::Command;

/// What `cargo tree -i <package>` says about one package in the build graph of this crate.
#[derive(Debug, PartialEq)]
enum Presence {
    Absent,
    Present,
}

/// Classifies one `cargo tree --invert` run. Anything that is not a clear answer is an error, so a
/// cargo that fails to start or a changed message never passes the gate.
fn classify(exit_ok: bool, stdout: &str, stderr: &str) -> Result<Presence, String> {
    if exit_ok {
        if stdout.trim().is_empty() {
            return Ok(Presence::Absent);
        }
        return Ok(Presence::Present);
    }
    if stderr.contains("did not match any packages") {
        return Ok(Presence::Absent);
    }
    Err(format!("cargo tree failed: {}", stderr.trim()))
}

/// Normal and build dependencies for the host target, from the committed lockfile only.
fn presence(package: &str) -> Result<Presence, String> {
    let cargo = std::env::var("CARGO").map_err(|e| format!("CARGO not set: {e}"))?;
    let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    let out = Command::new(&cargo)
        .current_dir(manifest_dir)
        .args([
            "tree",
            "--locked",
            "--offline",
            "-e",
            "normal,build",
            "-i",
            package,
        ])
        .output()
        .map_err(|e| format!("cannot start {cargo}: {e}"))?;
    classify(
        out.status.success(),
        &String::from_utf8_lossy(&out.stdout),
        &String::from_utf8_lossy(&out.stderr),
    )
}

fn assert_absent(package: &str) {
    assert_eq!(
        presence(package),
        Ok(Presence::Absent),
        "{package} is in the desktop build graph; check the IronRDP features in Cargo.toml"
    );
}

#[test]
fn license_gate_aws_lc_rs_is_not_built() {
    assert_absent("aws-lc-rs");
}

#[test]
fn license_gate_aws_lc_sys_is_not_built() {
    assert_absent("aws-lc-sys");
}

#[test]
fn license_gate_openh264_sys2_is_not_built() {
    assert_absent("openh264-sys2");
}

// The counter-probe: the same query finds a package that is in the graph, so an empty answer
// above means "absent" and not "the query never looked".
#[test]
fn license_gate_finds_a_package_that_is_built() {
    assert_eq!(presence("ring"), Ok(Presence::Present));
}

// RUSTSEC-2023-0071 (rsa through IronRDP, no fixed release) is accepted in .cargo/audit.toml,
// which `cargo audit` reads in audit.yml. The whole file stays that one exception: a second
// ignore or any other setting there would silence advisories nobody accepted.
#[test]
fn license_gate_audit_ignores_only_the_accepted_rsa_advisory() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join(".cargo/audit.toml");
    let text = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));
    let config: toml::Table = toml::from_str(&text).expect("audit.toml is not valid TOML");
    let expected: toml::Table =
        toml::from_str("[advisories]\nignore = [\"RUSTSEC-2023-0071\"]\n").expect("expected table");
    assert_eq!(
        config, expected,
        "audit.toml must ignore exactly RUSTSEC-2023-0071 and set nothing else"
    );
}

#[test]
fn license_gate_classify_rejects_unclear_answers() {
    assert_eq!(classify(true, "", ""), Ok(Presence::Absent));
    assert_eq!(classify(true, "ring v0.17.14\n", ""), Ok(Presence::Present));
    assert_eq!(
        classify(
            false,
            "",
            "error: package ID specification `x` did not match any packages"
        ),
        Ok(Presence::Absent)
    );
    assert!(classify(false, "", "error: failed to load manifest").is_err());
    assert!(classify(false, "", "").is_err());
}
