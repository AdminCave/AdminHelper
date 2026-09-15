<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# rustls-Bump (RUSTSEC-2026-0285) — Task-Ledger (Kurz)
Status: erledigt (1/1) · Branch: fix/rustls-bump · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: tasks/dependency-refresh-2.md (gleiche Mechanik) — Kurz-Ledger, keine eigene Spec
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: keine; Beweis ist `gh workflow run audit.yml --ref fix/rustls-bump` (Kevin) mit grünem `cargo audit (desktop)` plus der PR-CI-Job `rust`
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: R-0041 · Hängt ab von: —
Beabsichtigte Semantik: keine Verhaltensänderung; nur der Lockfile-Stand. rustls ist direkte Dependency (`Cargo.toml` Zeile 42, TOFU-Verifier mit `ring`-Provider) und transitiv über reqwest/tokio-rustls — die Version muss für beide Pfade dieselbe bleiben (Kommentar in `Cargo.toml` Zeile 37–41).

### T1 — rustls ≥ 0.23.45 im Desktop-Lockfile  [x] (cargo update -p rustls --precise 0.23.45: rustls 0.23.45 + rustls-webpki 0.103.15, eine rustls-Version im Lock, cargo audit Exit 0 mit 12 erlaubten Warnungen. Befund aus dem Review: cargo 1.96 schreibt dabei fünf `windows-sys`-Dependency-Kanten (errno, os_pipe, rustix, tempfile, winapi-util; 0.52.0 → 0.59.0 bzw. 0.45.0, alle Versionen bereits im Lock) neu — reproduziert mit `--precise`, also Resolver-Verhalten, kein breiteres Update; Paketversionen unverändert; Beweis für Windows: CI-Job `rust-windows`. verify.sh desktop-rs --strict: PASS)
Komponente: apps/desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.lock
Änderung: `cargo update -p rustls` (Dry-Run 2026-09-15: rustls 0.23.40 → 0.23.45, rustls-webpki 0.103.13 → 0.103.15). Danach prüfen, dass `Cargo.lock` genau **eine** rustls-0.23-Version enthält (kein Duplikat durch reqwest). `cargo audit` in `apps/desktop/src-tauri` meldet keine Vulnerability mehr (die zwei „unmaintained"-Warnungen fxhash/proc-macro-error bleiben Warnungen, kein Fehler). CHANGELOG Unreleased/Security ein Satz.
Verify: bash scripts/dev/verify.sh desktop-rs --strict   und   cargo audit   (in apps/desktop/src-tauri; Exit 0)
Doku: CHANGELOG (Security)
