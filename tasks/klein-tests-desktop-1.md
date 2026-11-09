<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-1 — flaky PTY-Tests (R-1177, R-1182) — Task-Ledger
Status: erledigt · Branch: feature/klein-tests-desktop-1 · Review: am Ende
Spec: docs/features/klein-tests-desktop-1.md (Roadmap R-1177, R-1182)
Heavy: windows — `rust-windows` (`cargo test --locked`) ist der CI-Job, der R-1177 zeigt; die PR-CI fährt ihn, lokal ist nur Linux verifizierbar
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@f8b5364f5`.

### T1 — PTY-Tests: nothing_after räumt Altdaten ab, Längenprüfung wartet auf das Entfernen (R-1177, R-1182)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/pty.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @50b18688e 2026-11-09T12:53:34+01:00
Review: am Ende (Branch-Review)
Beweis R-1177: ci.yml run 42339223796 job 128302958497, pty.rs:618 (Windows, `Data ESC[?9001h ESC[?1004h` statt `Disconnected`); weitere Läufe in der Roadmap-Notiz
Beweis R-1182: ci.yml run 42355226719 job 128351748771, pty.rs:814 (Linux, `registry.len()` 2 statt 1)
Dedup-Key: bug:desktop:apps/desktop/src-tauri/src/pty.rs:a_window_that_is_gone_hands_its_sessions_back_to_main (R-1182: bug:desktop:apps/desktop/src-tauri/src/pty.rs:close_all_of_a_window_leaves_the_others_running)
Änderung: `nothing_after` liest `Data` ab und verlangt danach `Disconnected` (`Exit`/`Replayed` panic); in `close_all_of_a_window_leaves_the_others_running` wartet ein Helfer mit Frist auf `registry.len() == 1`, statt es sofort zu prüfen. Der Linux-Fehler wird vorher mit einem `sleep` in der Entfernung (nur Probe, nicht committet) rot gezeigt.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- pty
Doku: keine (Test-only, kein dokumentiertes Verhalten)

### T2 — nothing_after bleibt streng, Senkenwechsel bekommen nothing_after_handover (R-1177)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/pty.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @029b76258 2026-11-09T13:08:49+01:00
Review: am Ende (Branch-Review)
Änderung: Korrektur nach der Abschlussprüfung (wichtig, `pty.rs:633`): das abräumende `nothing_after` schwächte auch die Prüfung „nichts nach `Exit`“. `nothing_after` ist wieder der strenge Helfer; nur die drei Stellen nach `attach`/`hand_back` nutzen den neuen `nothing_after_handover`, der vor dem Loslassen gesendete `Data` abliest.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- pty
Doku: keine (Test-only)
Abhängt von: T1
