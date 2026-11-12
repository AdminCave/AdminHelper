<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-server-6 — Task-Ledger
Status: geplant · Branch: feature/klein-tests-server-6 · Review: am Ende
Spec: docs/features/klein-tests-server-6.md (Roadmap R-1308)
Heavy: none — nur eine Test-Frist
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1308: der Unreadable-Test wartet auf die Übernahme bis 30 s  [ ]
Komponente: server · Dateien: apps/server/tests/test_frps_supervisor.py
Beweis: CI run 42985691597 job 130406190098 (PR #462) 2026-11-11 · Dedup-Key: BUG:server:test_frps_supervisor.py:turns_unreadable-wait
Änderung: In `test_an_input_that_turns_unreadable_is_rejected_and_logged_once` bekommen `wait_state("degraded")` (Z. 1197) und `wait_state("running")` (Z. 1212) die Frist `3 * WAIT`. Der Dauerlauf (50×) steht im Commit-Body.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_supervisor.py -k turns_unreadable
Doku: keine (Test-Frist)
