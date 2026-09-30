<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server: Key-Bindung, Import-422 und BIGINT-Grenze — Task-Ledger
Status: freigegeben · Branch: feature/server-key-binding-contract · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Freigabe: Kevin, 2026-09-30 („alle freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: docs/features/server-key-binding-contract.md (Roadmap R-0055, R-0056, R-0069)
Heavy: none — alles in-process: Authz-Matrix über die Key-Routen, Import-Fehlerform gegen das deklarierte Schema, Snapshot und oasdiff; Gateway, Compose, Agent, Web und Desktop bleiben unverändert, kein Client im Repo ruft /import, die Agent-Pfade (provision config/config-hash) sind in der Matrix.
DoD je Task: CLAUDE.md (Tests grün, ruff check + ruff format sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-09-30 von der Aufsicht (adminhelper-ac); Entscheidungen Kevin 2026-09-30. Zeilenangaben main@8224e84c.

### T1 — Key-Bindung: Matrix über alle Key-Routen, Schreibpfade prüfen serverId  [ ]
Komponente: server · Dateien: apps/server/tests/test_api_key_server_binding.py, apps/server/app/modules/connections/router.py, CHANGELOG.md
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
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_api_key_server_binding.py tests/test_connections_isolation.py tests/test_connections_authz.py tests/test_frp_provision_authz.py tests/test_route_auth_gate.py
Doku: CHANGELOG (Security, neutral: „Server-gebundene API-Keys dürfen Verbindungen nur für ihren eigenen Server anlegen oder dorthin verschieben“); docs/ beschreibt die Key-Bindung nicht

### T2 — Import antwortet bei abgelehnten Einträgen in der deklarierten 422-Form  [ ]
Komponente: server · Dateien: apps/server/app/modules/connections/router.py, apps/server/tests/test_connections_import.py, apps/server/tests/test_connections_isolation.py, apps/server/tests/schemathesis_exclude.toml, docs/developer/api-reference.html, docs/en/developer/api-reference.html, CHANGELOG.md
Änderung: `import_connections` (`:223`) wirft für abgelehnte Einträge `RequestValidationError` mit
`loc = ("body", "connections", <index>, *err.loc)`, dasselbe Muster wie `_reject_unknown_server` (`:55–81`), statt
`{"message", "rejected"}`; alles-oder-nichts bleibt. Der Ausschluss `response_schema_conformance` für den Import in
`schemathesis_exclude.toml` (um `:150–155`) fällt. Neuer Test: Einträge 1 und 3 ungültig → 422, Body validiert gegen
`HTTPValidationError`, `loc[2]` in Eintragsreihenfolge [1, 3], nichts geschrieben. Die zwei Tests der alten Form werden
ersetzt (unten). Zusatzbeleg: `bash scripts/dev/openapi-breaking.sh server` → Exit 0.
Test-Löschung: apps/server/tests/test_connections_isolation.py::test_import_with_unknown_server_is_rejected_per_entry — prüft die alte Form detail.rejected; der Ersatz prüft dieselbe Ablehnung in der FastAPI-Form; apps/server/tests/test_connections_import.py::test_import_rejects_mixed_errors_in_index_order — dito, Ersatz mit loc-Index statt rejected[].index
Verify: bash scripts/dev/verify.sh server --strict
Doku: docs/developer/api-reference.html DE+EN (:85): Fehlerform `detail[]` mit `loc` je Eintrag statt `detail.rejected`; CHANGELOG (Changed)

### T3 — Das veröffentlichte Schema trägt die exakte BIGINT-Grenze  [ ]
Komponente: server · Dateien: apps/server/app/main.py, apps/server/app/core/bounds.py, apps/server/tests/test_bounds.py, apps/server/tests/openapi.snapshot.json, CHANGELOG.md
Änderung: `app.openapi` überschreiben (nach FastAPI „Extending OpenAPI“, einmal erzeugen und cachen; bei Bedarf in
einem neuen `app/core/openapi.py`, dann mit SPDX): jedes `maximum`/`minimum`, das als Float gleich
`float(BIGINT_MAX)` bzw. dem Minimum ist, wird durch den int aus `bounds.py` ersetzt (neue Konstante `BIGINT_MAX`
neben `BigIntPk`, `:36`); Kommentar `bounds.py:29–35` nachziehen. Test: kein `maximum`/`minimum` ≥ 2⁵³ steht als Float
im ganzen Schema (heute ein Treffer, `MarkReadRequest.ids`), die Grenze ist exakt `9223372036854775807`. Snapshot neu
erzeugen; oasdiff meldet keine Änderung.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_bounds.py tests/test_openapi_snapshot.py tests/test_id_bounds.py
Doku: CHANGELOG (Fixed)
