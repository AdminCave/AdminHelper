<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-server-2 — Task-Ledger
Status: erledigt · Branch: feature/klein-tests-server-2 · Review: am Ende
Spec: docs/features/klein-tests-server-2.md (Roadmap R-0852)
Heavy: none — Unit-Test im Server, kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — test_mtls_scope: TimeoutExpired ohne Traceback abfangen (R-0852)  [x]
Komponente: server · Dateien: apps/server/tests/test_mtls_scope.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @9bda637a 2026-10-30T00:05:53+01:00
Review: am Ende (Branch-Review)
Änderung: Der Unterprozess-Aufruf in `test_mtls_enforce_defaults_to_enforced_without_the_env` fängt `subprocess.TimeoutExpired` und ruft `pytest.fail("...", pytrace=False)` wie `test_conftest_app_engine.py`, weil die Frames von `subprocess.run` die Umgebung tragen. Gegenprobe: mit einem Timeout von 0.001 s zeigt der Lauf die Meldung ohne Traceback (danach zurückgenommen).
Beweis: R-0852 Code-Lesung apps/server/tests/test_mtls_scope.py:231
Dedup-Key: ref:server:test_mtls_scope.py:timeout-pytrace
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_mtls_scope.py
Doku: keine (Test)

## Entscheidungen
