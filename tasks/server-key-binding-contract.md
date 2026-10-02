<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server: Key-Bindung, Import-422 und BIGINT-Grenze — Task-Ledger
Status: erledigt · Branch: feature/server-key-binding-contract · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Freigabe: Kevin, 2026-09-30 („alle freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: docs/features/server-key-binding-contract.md (Roadmap R-0055, R-0056, R-0069)
Heavy: none — alles in-process: Authz-Matrix über die Key-Routen, Import-Fehlerform gegen das deklarierte Schema, Snapshot und oasdiff; Gateway, Compose, Agent, Web und Desktop bleiben unverändert, kein Client im Repo ruft /import, die Agent-Pfade (provision config/config-hash) sind in der Matrix.
DoD je Task: CLAUDE.md (Tests grün, ruff check + ruff format sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-09-30 von der Aufsicht (adminhelper-ac); Entscheidungen Kevin 2026-09-30. Zeilenangaben main@8224e84c.

### T1 — Key-Bindung: Matrix über alle Key-Routen, Schreibpfade prüfen serverId  [x]
Komponente: server · Dateien: apps/server/tests/test_api_key_server_binding.py, apps/server/app/modules/connections/router.py, CHANGELOG.md, apps/server/app/modules/connections/schemas.py, apps/server/tests/test_connection_schemas.py
Evidenz: run.sh[quick]: 4 passed, 0 failed, 14 skipped @1fb94435 2026-09-30T17:27:15+02:00
Review: approve (opus, 2 Runden: snake_case-Feld nach Kevins Entscheidung in T1, Import-422 nach T2)
Änderung: Neue Testdatei (SPDX-Header), parametrisiert über (Route, Key, erwartet). Fixture: Server srv-a, srv-b;
Verbindungen c-a, c-b, c-null; Keys: an srv-a gebunden read, an srv-a gebunden read_write, global read; Übergabe als
Header und als `?api_key=`. Lesen: GET-Liste = {c-a}; touch c-b und c-null → 404, c-a → 200. Schreiben: PUT c-b → 404;
PUT c-a mit `serverId` srv-b oder `null` → 403; POST mit `serverId` srv-b oder `null` → 403; POST und PUT mit srv-a →
201/200. FRP: config und config-hash von srv-b → 403 für beide Berechtigungen. Admin-Routen (DELETE, export, import)
mit Key → 401. Wächter: die Menge der Routen mit `ApiKeyOrUser` (Enumeration wie
`tests/test_route_auth_gate.py:_collect_api_routes`) ist gleich der Menge der Matrix-Routen und nicht leer.
Fix: Helfer `_require_key_server(auth, server_id)` in `connections/router.py`: gebundener Key und `server_id` ungleich
seiner Bindung (auch `None`) → `HTTPException(403, "Kein Zugriff auf diesen Server")`. Aufruf in `create_connection`
(`:99`) und in `update_connection` (`:126`, dort nur wenn `"serverId" in connection.model_fields_set`), jeweils vor
`_reject_unknown_server` (`:105`, `:141`). Vor dem Fix rot: die vier Schreibzeilen mit fremder oder leerer `serverId`.
Mutationsprobe: den Zweig `:50–51` entfernen macht die Lese- und PUT-404-Zeilen rot; `_require_server_scope` entfernen
die FRP-Zeilen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_api_key_server_binding.py tests/test_connection_schemas.py tests/test_connections_isolation.py tests/test_connections_authz.py tests/test_frp_provision_authz.py tests/test_route_auth_gate.py
Doku: CHANGELOG (Security, neutral: „Server-gebundene API-Keys dürfen Verbindungen nur für ihren eigenen Server anlegen oder dorthin verschieben“); docs/ beschreibt die Key-Bindung nicht

### T2 — Import antwortet bei abgelehnten Einträgen in der deklarierten 422-Form  [x]
Komponente: server · Dateien: apps/server/app/modules/connections/router.py, apps/server/tests/test_connections_import.py, apps/server/tests/test_connections_isolation.py, apps/server/tests/schemathesis_exclude.toml, docs/developer/api-reference.html, docs/en/developer/api-reference.html, CHANGELOG.md
Evidenz: run.sh[quick]: 4 passed, 0 failed, 14 skipped @4292406d 2026-09-30T17:55:29+02:00
Review: approve (sonnet)
Änderung: `import_connections` (`:223`) wirft für abgelehnte Einträge `RequestValidationError` mit
`loc = ("body", "connections", <index>, *err.loc)`, dasselbe Muster wie `_reject_unknown_server` (`:55–81`), statt
`{"message", "rejected"}`; alles-oder-nichts bleibt. Der Ausschluss `response_schema_conformance` für den Import in
`schemathesis_exclude.toml` (um `:150–155`) fällt. Neuer Test: Einträge 1 und 3 ungültig → 422, Body validiert gegen
`HTTPValidationError`, `loc[2]` in Eintragsreihenfolge [1, 3], nichts geschrieben. Die zwei Tests der alten Form werden
ersetzt (unten). Zusatzbeleg: `bash scripts/dev/openapi-breaking.sh server` → Exit 0.
Nachtrag aus dem T1-Review (2026-09-30): Ein Import-Eintrag mit snake_case-Feld (etwa `server_id`) → 422 mit
`loc == ["body", "connections", <index>, "server_id"]`, nichts geschrieben (T1 lehnt es im Schema ab; erst die
422-Form aus T2 liefert es als 422 aus). Der Satz dazu gehört in den CHANGELOG-Eintrag von T2.
Test-Löschung: apps/server/tests/test_connections_isolation.py::test_import_with_unknown_server_is_rejected_per_entry — prüft die alte Form detail.rejected; der Ersatz prüft dieselbe Ablehnung in der FastAPI-Form; apps/server/tests/test_connections_import.py::test_import_rejects_mixed_errors_in_index_order — dito, Ersatz mit loc-Index statt rejected[].index
Verify: bash scripts/dev/verify.sh server --strict
Doku: docs/developer/api-reference.html DE+EN (:85): Fehlerform `detail[]` mit `loc` je Eintrag statt `detail.rejected`; CHANGELOG (Changed)

### T3 — Das veröffentlichte Schema trägt die exakte BIGINT-Grenze  [x]
Komponente: server · Dateien: apps/server/app/main.py, apps/server/app/core/bounds.py, apps/server/tests/test_bounds.py, apps/server/tests/openapi.snapshot.json, CHANGELOG.md, apps/server/app/core/openapi.py
Evidenz: run.sh[quick]: 4 passed, 0 failed, 14 skipped @788ad660 2026-09-30T18:16:29+02:00
Review: approve (sonnet)
Änderung: `app.openapi` überschreiben (nach FastAPI „Extending OpenAPI“, einmal erzeugen und cachen; bei Bedarf in
einem neuen `app/core/openapi.py`, dann mit SPDX): jedes `maximum`/`minimum`, das als Float gleich
`float(BIGINT_MAX)` bzw. dem Minimum ist, wird durch den int aus `bounds.py` ersetzt (neue Konstante `BIGINT_MAX`
neben `BigIntPk`, `:36`); Kommentar `bounds.py:29–35` nachziehen. Test: kein `maximum`/`minimum` ≥ 2⁵³ steht als Float
im ganzen Schema (heute ein Treffer, `MarkReadRequest.ids`), die Grenze ist exakt `9223372036854775807`. Snapshot neu
erzeugen; oasdiff meldet keine Änderung.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_bounds.py tests/test_openapi_snapshot.py tests/test_id_bounds.py
Doku: CHANGELOG (Fixed)

### T4 — Nachträge aus /code-review: API-Referenz, ungebundener Schreib-Key, voller Zustandsvergleich  [x]
Komponente: server · Dateien: apps/server/tests/test_api_key_server_binding.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html
Evidenz: run.sh[quick]: 4 passed, 0 failed, 14 skipped @9f1611d2 2026-09-30T18:53:46+02:00
Review: approve (sonnet)
Herkunft: /code-review über den Branch-Diff (2026-09-30)
Änderung: (1) API-Referenz DE+EN bei `POST`/`PUT /api/connections` (:80–81): ein an einen Server gebundener API-Key darf nur
`serverId` gleich seinem Server senden, sonst 403; die snake_case-Schreibweisen gemappter Felder ergeben 422.
(2) Matrix um einen ungebundenen read_write-Key erweitern: POST mit `serverId` srv-b und ohne → 201, PUT c-b mit
`serverId` srv-a → 200 (belegt „ungebundene Keys unverändert“; rot, wenn die Bindungsprüfung auch ohne Bindung greift).
(3) `_state` vergleicht die ganzen Zeilen (`to_dict()`), nicht nur `(id, name, server_id)`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_api_key_server_binding.py
Doku: API-Referenz DE+EN (Teil der Task)

Abschluss-Evidenz (2026-09-30):
- T1 in zwei Review-Runden (Opus). Nach Runde 1 kam auf Kevins Entscheidung Variante (a) hinzu: Schema-422 für die
  snake_case-Schreibweisen gemappter Felder. Dazu kamen Tests für die 403 vor der Existenzprüfung (srv-missing-Zeilen).
  Die Import-Hälfte des 422-Satzes ging nach T2.
- Ein voller Server-Lauf während T2 war verworfen, nicht rot: `UndefinedTable revoked_identities`, weil eine andere
  pytest-Session auf derselben Test-DB per `drop_all` abräumte. Der Nachlauf über task-close war grün (783 passed).
- Gesamt-Schnellcheck @9f1611d2: `run.sh[quick]: 18 passed, 0 failed, 0 skipped, 12 test-skips, 0 reruns`.
- /code-review über den Branch-Diff: acht Punkte, keiner eine Regression. Drei wurden T4, die übrigen gingen zur Einordnung
  an die Aufsicht.
- Heavy: none, am Diff bestätigt: nur connections-Router/-Schemas, das OpenAPI-Override und Tests. Gateway, Compose, Agent,
  Web und Desktop sind unberührt.
- Nach dem Merge von origin/main (0d656ff1, mit #62 logout-audit und #63): `verify.sh server --strict` → `798 passed,
  2 skipped` (Redis lokal), Schemathesis `288 passed`, `run.sh[quick]: 4 passed, 0 failed, 14 skipped, 2 test-skips,
  0 reruns`; `openapi-breaking.sh server` → no breaking changes.
