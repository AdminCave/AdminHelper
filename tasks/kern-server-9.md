# /api/servers: 422 in der Form des Schemas — Task-Ledger
Status: geplant · Branch: feature/kern-server-9 · Review: am Ende
Spec: Roadmap R-1450
Heavy: linux-full — Server-API; der Fund kommt aus schemathesis im Sammellauf, der ihn nach dem Merge erneut prüft
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1450: Namensfehler von POST/PUT /api/servers als HTTPValidationError  [ ]
Komponente: server · Dateien: apps/server/app/modules/servers/router.py, apps/server/tests/test_servers_name_windows.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-server-9.md, tasks/kern-server-9.md
Änderung: `_check_new_name` (router.py:50) und die `name: null`-Prüfung im `PUT` (router.py:196) werfen
`RequestValidationError` mit `loc` `("body", "name")` und demselben Text statt `HTTPException(422, detail=<str>)`,
wie hooks, connections, frp und notifications seit R-0207. Die Tests prüfen `detail` als Liste mit diesem `loc`
statt als String (gewollte Verhaltensänderung, Kevin 2026-11-14); die API-Referenz DE+EN beschreibt die neue Form.
Beweis: weekly 2026-11-14 `.ah-out/weekly/2026-11-14-0130/all-rest.log:187-226` (schemathesis ST108, `POST /api/servers`
mit `name` `07:00` → 422, `detail` ein String, das Schema verlangt `HTTPValidationError`), main@aa198d6e1
Dedup-Key: bug:server:apps/server/app/modules/servers/router.py:422-detail-string
HEAD: e22349c81
Semantik: Kevin 2026-11-14 (Antwort auf die Semantik-Frage): „Array wie R-0207“; bisher stand in
docs/developer/api-reference.html:103 „&rarr; <code>422</code> mit einem Text als <code>detail</code>“, die Zeile ändert die Task.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_servers_name_windows.py tests/test_server_name_and_address.py tests/test_openapi_snapshot.py
Doku: docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-server-9.md

## Entscheidungen
- 2026-11-14 Kevin: Array-Form wie R-0207 statt Text-`detail` mit angepasstem Schema; Web (`client.ts` `errorDetail`) und Desktop (`error.rs` `detail_text`) lesen beide Formen, die UI zeigt denselben Text.
