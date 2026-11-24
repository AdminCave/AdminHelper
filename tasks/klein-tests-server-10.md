<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-server-10 — Test-Zeit und Testname — Task-Ledger
Status: aktiv · Branch: feature/klein-tests-server-10 · Review: am Ende
Spec: docs/features/klein-tests-server-10.md (Roadmap R-1718, R-1741)
Heavy: none — zwei Test-Änderungen ohne Produktcode
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@4c8173e06`.

### T1 — Server-Test: kurzer Timeout für den Dashboard-Hänger (R-1718)  [ ]
Komponente: server · Dateien: apps/server/tests/test_frps_supervisor.py
Beweis: ci.yml Lauf 44997618373, Server (pytest, py3.14, shard 1/2): 90.50s call, test_frps_supervisor.py:1612
Dedup-Key: ref:server:tests/test_frps_supervisor.py:ninety-second-helper-timeout-test
Änderung: `_with_dashboard` nimmt `timeout: float = 3 * WAIT` und reicht ihn an `wait_until` weiter; der Hänger-Test ruft ihn mit 6 s. Dauer vorher/nachher (`--durations`) in den Commit-Body.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_supervisor.py::test_a_dashboard_that_never_answers_is_named_in_the_failure_of_the_wait
Doku: keine (Test)

### T2 — Monitoring-Test: Name (R-1741)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_auth.py
Dedup-Key: ref:monitoring:tests/test_auth.py:test_correctkey_matches
Änderung: `test_correctkey_matches` → `test_correct_key_matches`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_auth.py
Doku: keine (Testname)

## Entscheidungen
