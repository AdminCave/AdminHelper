// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! License gates for the embedded RDP client (conditions 7 and 8 of docs/features/arch-rdp-embedded.md):
//! packages that must never be compiled into the desktop. aws-lc-rs/aws-lc-sys: the desktop runs
//! one TLS provider, ring, and keeps aws-lc's C build out. openh264-sys2 with its feature `source`:
//! OpenH264 built from source carries no patent licence, so Linux loads Cisco's binary at runtime
//! (`libloading`, R-1102) instead. IronRDP offers all of them behind features (`rustls`, `udp`,
//! `openh264`), so one feature flip in Cargo.toml would pull them in silently. Cargo.lock may still list them as optional entries; what counts is the resolved build
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

/// Normal and build dependencies for the host target, from the committed lockfile only; each
/// package line ends in ` [<features>]`.
fn tree(package: &str) -> Result<(Presence, String), String> {
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
            "-f",
            "{p} [{f}]",
            "-i",
            package,
        ])
        .output()
        .map_err(|e| format!("cannot start {cargo}: {e}"))?;
    let stdout = String::from_utf8_lossy(&out.stdout).into_owned();
    let presence = classify(
        out.status.success(),
        &stdout,
        &String::from_utf8_lossy(&out.stderr),
    )?;
    Ok((presence, stdout))
}

fn presence(package: &str) -> Result<Presence, String> {
    tree(package).map(|(presence, _)| presence)
}

/// The features the build turns on for `package`, from the first line of the inverted tree (the
/// package itself); `None` when it is not built at all.
fn features(package: &str) -> Result<Option<Vec<String>>, String> {
    let (presence, stdout) = tree(package)?;
    if presence == Presence::Absent {
        return Ok(None);
    }
    parse_features(&stdout).map(Some)
}

fn parse_features(stdout: &str) -> Result<Vec<String>, String> {
    let first = stdout.lines().next().unwrap_or_default();
    let list = first
        .rsplit_once(" [")
        .and_then(|(_, rest)| rest.strip_suffix(']'))
        .ok_or_else(|| format!("no feature list in {first:?}"))?;
    Ok(list
        .split(',')
        .filter(|feature| !feature.is_empty())
        .map(str::to_string)
        .collect())
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

// R-1102: Linux needs openh264-sys2 to load Cisco's binary; `source` would compile OpenH264's C
// sources into the desktop. Elsewhere the package stays out of the build.
#[test]
fn license_gate_openh264_is_never_built_from_source() {
    let features = features("openh264-sys2").expect("cargo tree");
    if cfg!(target_os = "linux") {
        assert_eq!(
            features,
            Some(vec!["libloading".to_string()]),
            "openh264-sys2 loads Cisco's binary and builds nothing from source"
        );
    } else {
        assert_eq!(features, None, "openh264-sys2 is built off Linux");
    }
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

#[test]
fn license_gate_parse_features_reads_the_first_line_only() {
    assert_eq!(
        parse_features("openh264-sys2 v0.9.9 [libloading]\n└── openh264 v0.9.9 [source]\n"),
        Ok(vec!["libloading".to_string()])
    );
    assert_eq!(
        parse_features("openh264-sys2 v0.9.9 [libloading,source]\n"),
        Ok(vec!["libloading".to_string(), "source".to_string()])
    );
    assert_eq!(parse_features("ring v0.17.14 []\n"), Ok(vec![]));
    assert!(parse_features("ring v0.17.14\n").is_err());
    assert!(parse_features("").is_err());
}
