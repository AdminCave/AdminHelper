# Server: wiederholter Skalar-Query-Parameter ergibt 422 — Task-Ledger
Status: geplant · Branch: feature/kern-server-8 · Review: am Ende
Spec: docs/features/kern-server-8.md (Roadmap R-1132)
Heavy: linux-full — Server-API: eine App-weite Abhängigkeit vor jeder Route
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Server lehnt einen wiederholten Skalar-Query-Parameter mit 422 ab (R-1132)  [ ]
Komponente: server · Dateien: apps/server/app/core/query_params.py, apps/server/app/main.py, apps/server/tests/test_repeated_query.py, changelog.d/kern-server-8.md
Änderung: Erst der rote Test (`GET /api/connections?offset=1&offset=2` → heute 200), dann `query_params.py` (SPDX) wie im Monitoring und die App-weite Abhängigkeit in `main.py`. Ein einzelner Wert und ein nicht deklarierter, wiederholter Parameter bleiben 200.
Beweis: feature/monitoring-repeated-query@b0dd4a2c (R-1131, gleiche Klasse); roter Test apps/server/tests/test_repeated_query.py
Dedup-Key: bug:server:apps/server/app/main.py:repeated-scalar-query
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_repeated_query.py tests/test_openapi_snapshot.py
Doku: changelog.d/kern-server-8.md

## Entscheidungen
- CA-Issuer bleibt unverändert: keine Route mit Query-Parameter (Spec).
