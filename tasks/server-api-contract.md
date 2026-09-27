<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# REF-Bündel server: API-Vertrag (R-0043, R-0054, R-0068) — Task-Ledger
Status: aktiv · Branch: feature/server-api-contract · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Freigabe: Kevin, 2026-09-27 („alle freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: Roadmap R-0043, R-0054, R-0068
Heavy: none — die Antwort-Bytes bleiben gleich (Differential-Test je Route), Header-Namen, Gateway, Compose und Agent unverändert; die Auth-Dependency läuft in-process in den Authz-Tests und in Schemathesis in allen vier Kontexten. Den Stack deckt der nächste Wochenlauf (Kevin, 2026-09-27).
DoD je Task: CLAUDE.md (Tests grün, ruff/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-09-27 von der Aufsicht (adminhelper-ac) auf Kevins Wort (`/feature-plan --bundle server`). Kevins
Entscheidungen: Logout-Schema ehrlich machen (Verhalten bleibt); die sechs Routen aus R-0043 plus die zwei
Geschwister mit demselben Builder; `Heavy: none`, Bau als Lane parallel zu Stufe 5c. Von der Aufsicht gewählt:
`created_at` der Users-Antwort als `Optional[str]` aus `isoformat()` im Builder (dieselben Bytes wie heute, kein
`format: date-time`-Versprechen, kein neuer Schemathesis-Ausschluss; die datetime-Frage bleibt bei R-0064);
`?api_key=` wird nicht als `APIKeyQuery` deklariert (der Server warnt schon bei Nutzung, core/auth.py:202–207).

Regeln für diesen Bau:
- Modelle **vollständig** zum Builder anlegen und je Route ein Differential-Test „Antwort == bisheriges
  Builder-Dict": Pydantic schneidet fehlende Schlüssel still ab.
- Typen nach der **DB-Nullbarkeit**, nicht nach dem TS-Typ. Einmal typisiert, sind
  `response-property-became-optional` und `became-nullable` im oasdiff-Gate Fehler.
- Jede typisierte Fixture-Route hebt den Zähler in `apps/web/src/lib/api/mocks.contract.test.ts:145`
  (`toBe(8)`); jede R-0043-Task zieht ihn mit, sonst ist `web-vitest` rot.
- Verify-Zeilen mit zwei Komponenten fährt `task-close` heute nur als Suite der Task-Komponente (R-0104): der
  Bau fährt `run.sh quick --strict --only server web` vor dem Close selbst und nennt beide Summary-Zeilen.
- Findet Schemathesis nach T4 in den Key-Kontexten Neues: `[?]`, keinen Ausschluss schreiben.
- R-0056 (BUG, geplant) ändert dieselbe Funktion `import_connections` wie T6: seriell dazu bauen.

### T1 — R-0043: Users-Antworten typisieren (GET/POST, dazu PUT)  [ ]
Komponente: server · Dateien: apps/server/app/modules/users/schemas.py, apps/server/app/modules/users/router.py, apps/server/tests/test_users.py, apps/server/tests/openapi.snapshot.json, apps/web/src/lib/api/mocks.contract.test.ts
Änderung: `UserResponse` (id, username, is_admin, server_ids, created_at als `Optional[str]`) in `users/schemas.py`;
`response_model` an users/router.py:37, :43 und :96; `_user_response` (:27) bleibt der Builder und liefert
`created_at` als `isoformat()`. Snapshot neu (`--update-openapi-snapshot`, generiert).
`mocks.contract.test.ts:145` von 8 auf 10, Kommentar :138–144 nachziehen. Test: Antwort-JSON ==
`jsonable_encoder(_user_response(u))` für GET, POST und PUT, mit und ohne Server.
Beweis: origin/main@70e91718 · leere 2xx-application/json-Schemas in apps/server/tests/openapi.snapshot.json → 52; mocks.contract.test.ts:145 → `toBe(8)`
Orakel: contract — der Mock-Contract prüft GET/POST /api/users erstmals; Mutations-Stichprobe: ein Feld in makeUser umbenennen ⇒ rot
Metrik: untypisierte 2xx-Operationen 52 → 49 (python3 3.13.5, json)
HEAD: 70e91718
Verify: bash scripts/tests/run.sh quick --strict --only server web
Doku: keine (Antwort-Bytes unverändert; CHANGELOG in T3)

### T2 — R-0043: FRP-Server-Config typisieren (Liste, POST, PUT, dazu GET-Detail)  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/schemas.py, apps/server/app/modules/frp/config_router.py, apps/server/tests/test_frp_config.py, apps/server/tests/openapi.snapshot.json, apps/web/src/lib/api/mocks.contract.test.ts, docs/developer/api-reference.html, docs/en/developer/api-reference.html
Änderung: `FrpServerConfigOut` mit den 14 camelCase-Schlüsseln aus `FrpServerConfig.to_dict` (frp/models.py:41–65);
optional nach DB-Nullbarkeit: bindPort, authToken, dashboard*, extraConfig, createdAt, updatedAt (Zeiten als str,
wie to_dict sie liefert). `FrpTunnelOut` für die Tunnel der Detail-Antwort (models.py:111–129), Detail = Out plus
`tunnels`. `response_model` an config_router.py:27, :33, :89 und :99. Zähler 10 → 13. Test: Differential je Route,
dazu eine Zeile mit `bind_port` NULL und gesetztem `extraConfig`. Doku: api-reference DE+EN nennt
`?include_tunnels=true`, das es nicht gibt (die Detail-Antwort liefert die Tunnel immer, config_router.py:96).
Orakel: contract — der Mock-Contract prüft die FRP-Config-Routen erstmals
Metrik: untypisierte 2xx-Operationen 49 → 45
HEAD: 70e91718
Verify: bash scripts/tests/run.sh quick --strict --only server web
Doku: docs/developer/api-reference.html + docs/en/developer/api-reference.html (`?include_tunnels` streichen)
Abhängt von: T1

### T3 — R-0043: FRP-Status typisieren  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/schemas.py, apps/server/app/modules/frp/status_router.py, apps/server/tests/test_frp_status.py, apps/server/tests/openapi.snapshot.json, apps/web/src/lib/api/mocks.contract.test.ts, CHANGELOG.md
Änderung: `FrpStatus{proxies, total, error?}` und `FrpStatusProxy` mit den neun Feldern aus `_collect_proxies`
(status_router.py:20–35; int/str laut frps 0.69.1 `ProxyStatsInfo`, nie null). Das Feld `tunnel` bleibt ein
**offenes Objekt** (`Optional[dict[str, Any]]`), nicht `FrpTunnelOut`: sein Inhalt wird hier nicht eingefroren,
das ist eine eigene Entscheidung (Kevin, 2026-09-27). `response_model_exclude_unset=True`, damit `error` im
Erfolgszweig fehlt wie heute. Zähler 13 → 14. Test: gestubbtes Dashboard (pytest-httpx) mit einem Proxy, einem
zugeordneten Tunnel und dem Unerreichbar-Fall; Antwort == bisheriges Dict.
Orakel: contract — der Mock-Contract prüft GET /api/frp/status erstmals
Metrik: untypisierte 2xx-Operationen 45 → 44
HEAD: 70e91718
Verify: bash scripts/tests/run.sh quick --strict --only server web
Doku: CHANGELOG.md `[Unreleased]` / Changed (typisierte Antworten für users und frp im OpenAPI)
Abhängt von: T2

### T4 — R-0054: X-API-Key und X-Internal-Key als Security-Schemes, `ignored_auth` in allen Kontexten  [ ]
Komponente: server · Dateien: apps/server/app/core/auth.py, apps/server/app/modules/notifications/router.py, apps/server/tests/test_schemathesis.py, apps/server/tests/openapi.snapshot.json, docs/developer/api-reference.html, docs/en/developer/api-reference.html, CHANGELOG.md
Änderung: `APIKeyHeader(name="X-API-Key", scheme_name="ApiKey", auto_error=False)` als Security-Parameter in
`ApiKeyOrUser.__call__`; der Wert geht an `_get_api_key` (core/auth.py:188), der Query-Fallback bleibt.
`require_internal_key` (notifications/router.py:159) nimmt `APIKeyHeader("X-Internal-Key", scheme_name="InternalKey",
auto_error=False)`, der `or ""`-Guard bleibt. Zwei verschiedene `scheme_name`, sonst kollidieren beide als
„APIKeyHeader". `_BEARER_CONTEXTS` (test_schemathesis.py:149) auf alle vier Kontexte, Kommentar :141–148 neu.
Zusatzbeleg: `bash scripts/dev/openapi-breaking.sh server` → 0 error, 2 warning (der optionale Header-Parameter
`x-internal-key` entfällt), Exit 0.
Beweis: origin/main@70e91718 · `components.securitySchemes` im Snapshot → nur `HTTPBearer`; test_schemathesis.py:149 `_BEARER_CONTEXTS = {"admin_jwt"}`
Orakel: contract — Mutations-Stichprobe: ApiKeyOrUser lässt einen fehlenden Key durch ⇒ Schemathesis im Kontext read_key rot (heute grün, weil ignored_auth dort ausgenommen ist)
Metrik: Security-Schemes 1 → 3; Kontexte mit ignored_auth 1/4 → 4/4
HEAD: 70e91718
Verify: bash scripts/dev/verify.sh server --strict
Doku: api-reference DE+EN, Abschnitt Authentifizierung (X-Internal-Key nennen; Swagger „Authorize" kennt beide) · CHANGELOG Changed

### T5 — R-0054: Logout-Schema ehrlich machen  [ ]
Komponente: server · Dateien: apps/server/app/modules/users/auth_router.py, apps/server/tests/test_auth.py, apps/server/tests/schemathesis_exclude.toml, apps/server/tests/openapi.snapshot.json, docs/developer/api-reference.html, docs/en/developer/api-reference.html
Änderung: Das Verhalten von `POST /api/auth/logout` (auth_router.py:220) bleibt; das Schema deklariert die Auth als
**optional** (`security: [{"HTTPBearer": []}, {}]`, etwa über `openapi_extra`). Vorher nachlesen und im Commit
zitieren, ob FastAPI die `security`-Liste bei `openapi_extra` anhängt oder ersetzt, und wie Schemathesis 4.x ein
`{}`-Alternativ-Requirement liest. Der Ausschluss in `schemathesis_exclude.toml` (:150–155): `ignored_auth` streichen,
wenn Schemathesis `{}` als optional liest, sonst mit neuem Grund stehen lassen. Test: Logout nur mit
Refresh-Cookie, ohne Bearer → 200, Cookie gelöscht; danach `/api/auth/refresh` mit dem alten Token → 401.
Semantik: docs/developer/api-reference.html:57 — „Blacklisted den aktuellen Access-Token (und optional einen mitgesendeten Refresh-Token)." · apps/server/tests/test_route_auth_gate.py:53 `("POST", "/api/auth/logout"),  # clears the refresh cookie`
Orakel: contract
HEAD: 70e91718
Verify: bash scripts/dev/verify.sh server --strict
Doku: api-reference DE+EN :56–57 (Auth optional, das Cookie wird gelöscht); nebenbei :49 korrigieren (Login liefert `token_type`, nicht `user`)
Abhängt von: T4

### T6 — R-0068: der Import prüft alle serverIds mit einer Abfrage  [x]
Komponente: server · Dateien: apps/server/app/modules/connections/router.py, apps/server/tests/test_connections_import.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html
Evidenz: run.sh[quick]: 4 passed, 0 failed, 14 skipped @1922085f 2026-09-27T15:48:12+02:00
Review: approve (sonnet)
Änderung: Die Abfrage je Eintrag (connections/router.py:248–250, `db.query(Server.id).filter(Server.id ==
payload["serverId"]).first()`) wandert aus der Schleife: erst alle Einträge validieren, dann die verschiedenen
`serverId` sammeln und einmal `SELECT id FROM servers WHERE id IN (…)`, danach die Mitgliedschaft prüfen. Die Liste
`rejected` bleibt nach `index` sortiert, auch wenn Validierungs- und Server-Fehler gemischt auftreten. Tests:
`test_import_checks_server_ids_with_one_query` (Listener `before_cursor_execute` auf `db_session.connection()`,
gezählt nur um den Import-POST, Login vorher; N=20 Einträge mit je eigener, existierender `serverId` → genau ein
Statement `FROM servers`) und ein Mischfall (Eintrag 1 ungültig, Eintrag 3 mit unbekanntem Server →
`rejected[*].index == [1, 3]`). Den Vorher-Wert zuerst auf HEAD messen und in die Metrik schreiben.
Orakel: metric — Mutations-Stichprobe: Abfrage zurück in die Schleife ⇒ Zähltest rot; Suite vor und nach dem Diff grün (beide Summary-Zeilen)
Metrik: SELECTs auf servers bei N=20: 20 (aus dem Code gelesen, auf HEAD zu messen) → 1 (SQLAlchemy before_cursor_execute)
HEAD: 70e91718
Verify: bash scripts/dev/verify.sh server --strict
Doku: api-reference DE+EN :82 — `?mode=replace|merge` ist falsch, `mode` steht im Body (ImportRequest.mode)
