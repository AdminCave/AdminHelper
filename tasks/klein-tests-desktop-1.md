<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-1 — flaky PTY-Tests (R-1177, R-1182) — Task-Ledger
Status: aktiv · Branch: feature/klein-tests-desktop-1 · Review: am Ende
Spec: docs/features/klein-tests-desktop-1.md (Roadmap R-1177, R-1182)
Heavy: windows — `rust-windows` (`cargo test --locked`) ist der CI-Job, der R-1177 zeigt; die PR-CI fährt ihn, lokal ist nur Linux verifizierbar
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@f8b5364f5`.

### T1 — PTY-Tests: nothing_after räumt Altdaten ab, Längenprüfung wartet auf das Entfernen (R-1177, R-1182)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/pty.rs
Beweis R-1177: ci.yml run 42339223796 job 128302958497, pty.rs:618 (Windows, `Data ESC[?9001h ESC[?1004h` statt `Disconnected`); weitere Läufe in der Roadmap-Notiz
Beweis R-1182: ci.yml run 42355226719 job 128351748771, pty.rs:814 (Linux, `registry.len()` 2 statt 1)
Dedup-Key: bug:desktop:apps/desktop/src-tauri/src/pty.rs:a_window_that_is_gone_hands_its_sessions_back_to_main (R-1182: bug:desktop:apps/desktop/src-tauri/src/pty.rs:close_all_of_a_window_leaves_the_others_running)
Änderung: `nothing_after` liest `Data` ab und verlangt danach `Disconnected` (`Exit`/`Replayed` panic); in `close_all_of_a_window_leaves_the_others_running` wartet ein Helfer mit Frist auf `registry.len() == 1`, statt es sofort zu prüfen. Der Linux-Fehler wird vorher mit einem `sleep` in der Entfernung (nur Probe, nicht committet) rot gezeigt.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- pty
Doku: keine (Test-only, kein dokumentiertes Verhalten)
