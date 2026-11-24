<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-Crates mit Advisory nachziehen (kern-deps-6)

Roadmap: R-1738. Kevin 2026-11-23: angenommen.

## Problem

Der Dependency Audit vom 2026-11-23 ist rot: `cargo audit` meldet im Desktop-`Cargo.lock` zwei Advisories,
`url` 2.5.8 (behoben ab 2.5.9) und `cookie` 0.18.2 (behoben ab 0.18.3). Beide sind transitiv und liegen im
semver-Rahmen von `Cargo.toml`.

## Ziel und Nicht-Ziele

Ziel: `cargo update -p url -p cookie`, `cargo audit` ohne Vulnerability. Nicht-Ziel: weitere Crates, die erlaubten
Warnungen (`.cargo/audit.toml`), `Cargo.toml`.

## Betroffene Dateien

`apps/desktop/src-tauri/Cargo.lock`, `changelog.d/kern-deps-6.md`.

## Risiken und Rollback

Patch-Versionen; Build, Clippy und Tests des Desktop-Backends prüfen sie. Rollback: Revert des Commits.

## Doku-Impact

Nur der CHANGELOG-Eintrag (`### Security`).
