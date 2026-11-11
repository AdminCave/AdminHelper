<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-monitoring-3 — Task-Ledger
Status: bereit · Branch: feature/klein-tests-monitoring-3 · Review: am Ende
Spec: docs/features/klein-tests-monitoring-3.md (Roadmap R-1146)
Heavy: none — nur eine Test-ID
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1146: Test-ID `alarm-after-cooldown` nennt, was der Fall prüft  [x]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_check_engine_concurrency.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @2c593156f 2026-11-11T13:33:55+01:00
Review: am Ende (Branch-Review)
Beweis: Session R-1079 T9 2026-11-05 · feature/arch-notify-incidents@14ad9215 apps/monitoring/tests/test_check_engine_concurrency.py:408 · Dedup-Key: REF:monitoring:test_check_engine_concurrency.py:alarm-after-cooldown
Änderung: Die parametrize-ID `alarm-after-cooldown` wird `alarm-after-ok-record` (der Fall: Alarm, dessen Glocken-Zeile vorher `ok` zeigte); Parameter und Verhalten bleiben gleich.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_engine_concurrency.py
Doku: keine (Test-ID)
