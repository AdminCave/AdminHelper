<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-server-1 — Task-Ledger
Status: erledigt · Branch: feature/klein-tests-server-1 · Review: pro Task
Spec: docs/features/klein-tests-server-1.md (Roadmap R-0925, R-0889, R-0892)
Heavy: none — nur Server-Unit-Tests und eine CLI-Argumentprüfung, kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Route-Gate sieht Include-Abhängigkeiten (R-0925)  [x]
Komponente: server · Dateien: apps/server/tests/test_route_auth_gate.py, apps/server/tests/test_stream.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @42cc2b48 2026-10-29T16:16:13+01:00
Review: approve (.ah-out/review/klein-tests-server-1/T1.verdict.json)
Änderung: `_include_dependency_qualnames` aus `test_stream.py` nach `test_route_auth_gate.py` verschieben, `_dependency_qualnames` bezieht die Include-Abhängigkeiten der Route ein; `test_stream.py` importiert den Helfer. Positivprobe: ein Router, der nur am Include einen Guard trägt, gilt als geschützt.
Beweis: HEAD · `bash scripts/dev/verify.sh server --strict -- apps/server/tests/test_route_auth_gate.py` → Probe-Test mit Guard allein am Include rot vor der Änderung
Dedup-Key: bug:server:tests/test_route_auth_gate.py:include-deps
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_route_auth_gate.py tests/test_stream.py
Doku: keine (nur Tests)

### T2 — Refresh-Token ohne jti/exp ist Reuse (R-0889)  [x]
Komponente: server · Dateien: apps/server/tests/test_auth_token_lifecycle.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @60ed4083 2026-10-29T16:18:37+01:00
Review: approve (.ah-out/review/klein-tests-server-1/T2.verdict.json)
Änderung: Test, dass ein sonst gültiges Refresh-Token ohne `jti`/`exp` am Rotationsschritt (`blacklist_token` False) 401 liefert und die Familie beendet (Watermark gesetzt).
Dedup-Key: ref:server:auth_router.py:refresh-no-jti-test
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_auth_token_lifecycle.py
Doku: keine (nur Tests)

### T3 — Hook-Worker `-s`, gemeinsame Deadline, CLI-Flag-Kombination (R-0892)  [x]
Komponente: server · Dateien: apps/server/tests/test_hook_isolation.py, apps/server/tests/test_cli.py, apps/server/app/cli.py, changelog.d/klein-tests-server-1.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @9e89a1a8 2026-10-29T16:27:42+01:00
Review: approve (.ah-out/review/klein-tests-server-1/T3.verdict.json)
Änderung: (a) Test, dass der Worker mit `-s` startet, unabhängig von `PYTHONNOUSERSITE` (Popen-Argv); (b) Test, der die gemeinsame Reader-Deadline pinnt (zwei gehaltene Streams enden nach einer Grace, nicht zwei); (c) `create-admin`/`reset-admin` lehnen `--password` zusammen mit `--password-stdin` per `parser.error` ab, Test dazu.
Dedup-Key: ref:server:cli.py:password-flag-combo
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hook_isolation.py tests/test_cli.py
Doku: changelog.d/klein-tests-server-1.md; README.md und docs/admin/troubleshooting.html (DE+EN) nur, wenn sie die Kombination beschreiben

### T4 — Include-Walk ordnet Guards der Route zu, nicht dem Pfad (Abschlussprüfung)  [x]
Komponente: server · Dateien: apps/server/tests/test_route_auth_gate.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @cead49e9 2026-10-29T16:38:29+01:00
Review: approve (.ah-out/review/klein-tests-server-1/T4.verdict.json)
Änderung: `_dependency_qualnames` sucht den Include, dessen Router genau diese Route enthält (`is`), statt über den Pfad; Probe-Test mit Pfad-Kollision (GET mit Include-Guard, POST ohne Guard am selben Pfad) muss rot werden, wenn der Walk wieder über den Pfad geht. Modul-Docstring (FastAPI >= 0.138) nachziehen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_route_auth_gate.py tests/test_stream.py
Doku: keine (nur Tests)

## Entscheidungen
