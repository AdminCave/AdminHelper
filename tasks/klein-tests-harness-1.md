<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-harness-1 — Task-Ledger
Status: bereit · Branch: feature/klein-tests-harness-1 · Review: am Ende
Spec: docs/features/klein-tests-harness-1.md (Roadmap R-1005)
Heavy: none — reine Test-Änderung unter scripts/dev/tests
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1005: Timeout des Umgebungs-Tests unter Last  [x]
Komponente: scripts · Dateien: scripts/dev/tests/test_lock_pins.py
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @974fceae 2026-11-02T09:39:53+01:00
Review: am Ende (Branch-Review)
Beweis: Session klein 2026-10-30 · task-close klein-tests-stack-2 T2, erster Lauf verify-red (Timeout), zweiter Lauf grün bei Last ~8
Dedup-Key: bug:scripts-dev:test_lock_pins.py:running-environment-timeout
Änderung: `run()` bekommt einen `timeout`-Parameter (Default 30); `test_the_running_environment_is_read_by_default` übergibt 120, weil sie die ganze Umgebung über `importlib.metadata` liest. Beide Assertions bleiben. Der Fund zeigt sich nur unter Last und ließ sich nicht erzeugen; Nachweis ist nur der grüne Lauf (Gegenprobe des Prüfers mit Timeout 30 ebenfalls grün, nicht reproduziert).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (interne Testkonstante)
