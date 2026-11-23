<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-deps-6 — Task-Ledger
Status: aktiv · Branch: feature/kern-deps-6 · Review: am Ende
Spec: docs/features/kern-deps-6.md (Roadmap R-1738)
Heavy: linux-full — Desktop-Binary (Cargo.lock); kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Tasks

### T1 — R-1738: url und cookie über die Advisory-Grenze heben  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.lock, changelog.d/kern-deps-6.md
Änderung: `cargo update -p url -p cookie` (url ≥ 2.5.9, cookie ≥ 0.18.3), keine Änderung an `Cargo.toml`;
`cargo audit` meldet keine Vulnerability mehr. Fragment `changelog.d/kern-deps-6.md` unter `### Security`.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: changelog.d/kern-deps-6.md

## Entscheidungen
