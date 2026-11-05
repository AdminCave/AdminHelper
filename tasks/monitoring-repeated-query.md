<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: wiederholter Skalar-Query-Parameter → 422 — Task-Ledger
Status: geplant · Branch: feature/monitoring-repeated-query · Review: am Ende
Spec: Roadmap R-1131
Heavy: linux-full — der Schritt schemathesis ist im Sammellauf 2026-11-04 rot; der Fix beweist sich auf einer Box (`bash scripts/tests/run.sh all --strict --step schemathesis`, 100 Beispiele)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Entscheidung Kevin 2026-11-05: den Fehler beheben (ablehnen mit 422), kein Waiver in `schemathesis_exclude.toml`.

### T1 — Wiederholte Skalar-Query-Parameter mit 422 ablehnen (R-1131)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/main.py, apps/monitoring/app/core/query_params.py, apps/monitoring/tests/test_repeated_query.py, changelog.d/monitoring-repeated-query.md
Änderung: Eine App-weite Abhängigkeit liest für die getroffene Route aus `app.openapi()` die Query-Parameter, deren Schema kein Array ist, und lehnt einen solchen Parameter, der mehrfach im Query steht, mit `RequestValidationError` ab (422, `loc` `["query", <name>]`); FastAPI nahm bisher still den letzten Wert. Der OpenAPI-Snapshot bleibt unverändert. Neue Dateien mit SPDX-Header; Test zuerst rot.
Semantik: `docs/developer/cicd.html:356` — Schema-Fuzzing gegen „<code>app.openapi()</code> je Dienst“ prüft „die Antworten der eigenen Routen unter jedem Auth-Kontext“; das Schema deklariert `offset` (und jeden anderen Query-Parameter des Monitorings) als einzelnen Wert, nicht als Array.
Beweis: main@de42e484 · `AH_SCHEMATHESIS_EXAMPLES=100 python3 -m pytest -q -m schemathesis -p no:randomly` in apps/monitoring → `1 failed, 137 passed`, `test_api_under_every_auth_context[GET /checks][internal_key]` ST201 „parameter `offset` in query - violates `type` (was integer, became array)“, Antwort 200 `[]`
Dedup-Key: bug:monitoring:apps/monitoring/app/routers/checks.py:list_checks.offset
HEAD: de42e484
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_repeated_query.py tests/test_openapi_snapshot.py
Doku: changelog.d/monitoring-repeated-query.md (API-Doku beschreibt Query-Parameter nicht als wiederholbar)

## Entscheidungen
