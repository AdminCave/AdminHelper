<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ref-server-4 — Task-Ledger
Status: aktiv · Branch: feature/klein-ref-server-4 · Review: am Ende
Spec: docs/features/klein-ref-server-4.md (Roadmap R-1025, R-1124)
Heavy: none — Test-Dependency und eine Query-Schreibweise ohne Änderung von API oder Gateway
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1025: expiry.agents mit postgresql.distinct_on  [ ]
Komponente: server · Dateien: apps/server/app/modules/enrollment/expiry.py, apps/server/tests/test_certificate_expiry.py
Review: am Ende (Branch-Review)
Beweis: reviewer branch kern-ca-4 2026-10-31 · apps/server/app/modules/enrollment/expiry.py:74 · Verify-Log: SADeprecationWarning bei `tests/test_certificate_expiry.py`
Änderung: `.distinct(IssuedCertificate.line_id)` durch `postgresql.distinct_on` ersetzen, gleiche `ORDER BY`. Der Test hält fest, dass je Linie die Zeile mit dem größten `not_after` (bei Gleichstand kleinster Fingerprint) kommt und der Lauf keine `SADeprecationWarning` auslöst (`pytest.warns`-Gegenstück: `warnings.simplefilter("error", SADeprecationWarning)`).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_certificate_expiry.py tests/test_certificate_expiry_watch.py
Doku: keine (internes Refactoring)

### T2 — R-1124: Server-TestClient auf httpx2  [ ]
Komponente: server · Dateien: apps/server/requirements-dev.txt, DEVELOPMENT.md
Review: am Ende (Branch-Review)
Beweis: reviewer kern-deps-2 T1 2026-11-04 · Verify-Log server (StarletteDeprecationWarning)
Änderung: `httpx2` in `requirements-dev.txt` aufnehmen, ein Satz in `DEVELOPMENT.md`. Danach läuft die Server-Suite ohne `StarletteDeprecationWarning`; Beleg: gezielter Lauf mit `-W error::starlette.exceptions.StarletteDeprecationWarning` auf Tests, die den `TestClient` nutzen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_certificate_expiry.py tests/test_mtls_scope.py tests/test_openapi_snapshot.py
Doku: DEVELOPMENT.md (die Änderung selbst)
