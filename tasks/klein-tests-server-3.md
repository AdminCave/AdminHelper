<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-server-3 — Task-Ledger
Status: geplant · Branch: feature/klein-tests-server-3 · Review: am Ende
Spec: docs/features/klein-tests-server-3.md (Roadmap R-1084)
Heavy: none — nur ein Server-Unit-Test, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Grace-Timing-Test robust gegen Host-Last (R-1084)  [ ]
Komponente: server · Dateien: apps/server/tests/test_hook_isolation.py
Beweis: task-close kern-laufzeit-1 T2 2026-11-02, Log .ah-out/logs/verify-20261102-123710-3892926.log (extra 0.794 s < 0.8·grace, Host-Last ~20-30)
Dedup-Key: bug:server:test_hook_isolation:grace-timing-flaky
Änderung: `plain` und `held` in `test_hook_reader_grace_is_one_deadline_for_both_streams` (`test_hook_isolation.py:230`) sind je das Minimum von drei Läufen statt eines Einzellaufs; Schranken bleiben 0.8·grace ≤ extra < 1.6·grace. Gegenprobe: Grace-Verdopplung im Runner lässt den Test rot werden.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hook_isolation.py
Doku: keine (Test-Interna)
