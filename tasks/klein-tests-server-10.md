<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-server-10 — Test-Zeit und Testname — Task-Ledger
Status: bereit · Branch: feature/klein-tests-server-10 · Review: am Ende
Spec: docs/features/klein-tests-server-10.md (Roadmap R-1718, R-1741)
Heavy: none — zwei Test-Änderungen ohne Produktcode
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@4c8173e06`.

### T1 — Server-Test: kurzer Timeout für den Dashboard-Hänger (R-1718)  [x]
Komponente: server · Dateien: apps/server/tests/test_frps_supervisor.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @41999f9b3 2026-11-24T16:10:56+01:00
Review: am Ende (Branch-Review)
Beweis: ci.yml Lauf 44997618373, Server (pytest, py3.14, shard 1/2): 90.50s call, test_frps_supervisor.py:1612
Dedup-Key: ref:server:tests/test_frps_supervisor.py:ninety-second-helper-timeout-test
Änderung: `_with_dashboard` nimmt `timeout: float = 3 * WAIT` und reicht ihn an `wait_until` weiter; der Hänger-Test ruft ihn mit 10 s. Dauer vorher/nachher (`--durations`) in den Commit-Body.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_supervisor.py::test_a_dashboard_that_never_answers_is_named_in_the_failure_of_the_wait
Doku: keine (Test)

### T2 — Monitoring-Test: Name (R-1741)  [x]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_auth.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @eefc31cfb 2026-11-24T16:11:08+01:00
Review: am Ende (Branch-Review)
Dedup-Key: ref:monitoring:tests/test_auth.py:test_correctkey_matches
Änderung: `test_correctkey_matches` → `test_correct_key_matches`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_auth.py
Doku: keine (Testname)

### T3 — Fund der Abschlussprüfung: Frist kommentieren (R-1718)  [x]
Komponente: server · Dateien: apps/server/tests/test_frps_supervisor.py, docs/features/klein-tests-server-10.md, tasks/klein-tests-server-10.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @32999fce7 2026-11-24T16:17:46+01:00
Review: am Ende (Branch-Review)
Änderung: Kommentar am Aufruf (der Test prüft das Ablaufen des Wartens selbst, `testing.md` Fristen) und Frist 10 s statt 6 s für mehr Spielraum bei Last.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_supervisor.py::test_a_dashboard_that_never_answers_is_named_in_the_failure_of_the_wait
Doku: keine (Test)

## Entscheidungen
