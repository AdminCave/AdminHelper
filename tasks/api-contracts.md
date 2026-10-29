<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# API-Verträge: Antwortmodelle für Server und Monitoring, Client-Typen gegen den Snapshot — Task-Ledger
Status: aktiv · Branch: feature/api-contracts · Review: pro Task
Spec: docs/features/api-contracts.md (Roadmap R-0684, R-0685, R-0686, R-0687; R-0407 erledigt T10 mit)
Heavy: linux-full + scenario --agents 1 --tunnel --desktop --moncheck + windows — Server-API: 33 Routen bekommen ein `response_model`, darunter die Antworten, die nur echte Clients lesen: Activate und `config-hash` (Agent), Tunnels und `visitor-bundle` (Desktop, S4), Enrollment-Grant (Desktop, S3), dazu die Monitoring-Antworten hinter dem Proxy (S5). Laut Gleichheitstests bleiben die Antworten byte-gleich; ein zu strenges Modell wäre eine 500, die nur der echte Datenpfad mit Altdaten zeigt. `linux-full` im Sammellauf über `main` (`/feature-build` §5); `scenario` vor dem Merge (ask-first, Kevins Ja); `windows` sind die Windows-Jobs der PR-CI (keine Windows-Box im Pool). Kein Agent- und kein Rust-Code im Diff
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Jede JSON-Route des Servers außer den Nicht-Zielen der Spec deklariert ein `response_model`, das die heutige
Antwort Schlüssel für Schlüssel abbildet (R-0684). (2) Dasselbe für Monitoring außer `/health` und dem Agent-Report
(R-0685). (3) Web- und Desktop-`types.ts` werden je von einem Vertragstest gegen die Snapshots geprüft, die Drift ist
behoben, auch das fehlende Datum eines neuen API-Schlüssels (R-0686, R-0687). (4) Die Monitoring-Sektionen der
Desktop-UI lesen `state.details` über Narrowing-Funktionen statt über `as` (R-0687). Keine Antwort ändert sich;
`scripts/dev/openapi-breaking.sh` meldet je Task 0 ERR. Zeilenangaben: origin/main@b25c65a6; der builder greppt sie
vor dem Schreiben neu.

Für alle Tasks:
- Blöcke und Reihenfolge: A Server T1–T12 (T2 nach T1, T11 vor T12), B Monitoring T13–T17, C Web T18–T19, D Desktop-UI
  T20–T25. A und B sind unabhängig. T18 und T23 gehen jederzeit. T19 nach T2, T9, T10, T12. T20 nach Block A und T19.
  T21 und T22 nach Block B und T20. T24 und T25 nach T23. Eine Teilung in die Teil-Ledger `api-contracts-server`
  (T1–T12), `api-contracts-monitoring` (T13–T17) und `api-contracts-clients` (T18–T25) ist Kevins Wort (Spec,
  Trade-off 8).
- Hängt ab von `fehlervertrag` (freigegeben, eigener Branch). Geteilte Dateien: `CHANGELOG.md` (hier T12, T17, T18),
  `apps/web/src/lib/api/types.ts` (hier T18, T19; dort die Klasse `ApiError`); über Folgeänderungen möglich
  `apps/desktop/ui/src/lib/stores/monitoring.ts` und `apps/desktop/ui/src/components/monitoring/BuiltinUpdateModal.svelte`.
  Ist `fehlervertrag` gemergt, vor der ersten Task, die eine dieser Dateien berührt, `origin/main` hineinmergen.
- Antwortmodelle nach den Regeln 1–7 der Spec („Datenmodell“): Schlüssel wie der Produzent, Feldname = JSON-Schlüssel,
  Zeitstempel `str`/`Optional[str]`, kein Typ enger als Spalte und alle Schreiber, die es je gab (bei JSON in einer
  Textspalte belegt `git log -S` an der Validierung, seit wann sie gilt; älter als die Spalte → `list[str]`, sonst
  `list[Any]`), bedingte Schlüssel als Feld mit Default `None` plus `response_model_exclude_unset=True` an jeder Route,
  die das Modell auch verschachtelt liefert, keine Validatoren, keine Grenzen. Ein Routen-Docstring ist die
  OpenAPI-description und bleibt unverändert.
- Testmuster je Server- und Monitoring-Task in `tests/test_response_shapes.py` der Komponente (T1 bzw. T13 legt die
  Datei an, SPDX per `reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later <datei>`): (a) das
  2xx-Schema der Operation im laufenden `app.openapi()` verweist auf das neue Modell (rot auf HEAD); (b) Gleichheit über
  die echte Route, `resp.json() == jsonable_encoder(<Produzent>)`, mit einer vollen Zeile und einer dünnen (alle
  nullbaren Spalten `NULL`), Muster `TestConfigResponseShape` (`apps/server/tests/test_frp_config.py:581-680`);
  (c) jede bedingte Variante (Schlüssel fehlt / ist da). Danach den Snapshot neu schreiben
  (`pytest tests/test_openapi_snapshot.py --update-openapi-snapshot` im Komponenten-Verzeichnis) und
  `bash scripts/dev/openapi-breaking.sh <server|monitoring>` fahren: 0 ERR, Ausgabe-Zusammenfassung in den Commit-Body.
- `security` zusätzlich (`scripts/dev/review-risk.txt`): T1–T10, T12–T17, T19–T22.
- Platzhalter in Tests: Hosts unter `.example`, Adressen aus RFC 5737.

### T1 — connections: `ConnectionOut` und `ConnectionImportResult` (R-0684)  [ ]
Komponente: server · Dateien: apps/server/app/modules/connections/schemas.py, apps/server/app/modules/connections/router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json
Änderung: Vorher die offizielle FastAPI-Doku zu Response Model und `response_model_exclude_unset` lesen (WebFetch), Ergebnis in den Commit-Body. Neu in `connections/schemas.py`: `ConnectionOut` mit `model_config = ConfigDict(extra="allow")` und den Schlüsseln von `Connection.to_dict` (`apps/server/app/modules/connections/models.py:66-90`): `id`, `name`, `kind` als `str` (Spalte `:49` nicht eingeschränkt, die Import-Validierung gibt es erst seit v0.36.0, Commit `84d4eaa8`), `host`, `username`, `domain`, `keyPath`, `url`, `notes` als `str` (`or ""`), `port: Optional[int]`, `tags: list[Any]`, `trustCert: bool`, `lastUsed: Optional[str]`, `serverId: Optional[str] = None` (nur gesetzt, wenn es einen Server gibt). `ConnectionImportResult` `{imported: int, mode: str}` (`router.py:306`). Routen `GET ''` (`router.py:95`, `list[ConnectionOut]`), `POST ''` (`:110`), `PUT /{conn_id}` (`:138`), `POST /{conn_id}/touch` (`:173`) mit `response_model_exclude_unset=True`; `POST /import` (`:237`). Neue Datei `tests/test_response_shapes.py` mit dem Testmuster; (c) Verbindung ohne Server → kein `serverId`; Verbindung mit `extra_data` `{"proxyJump": "jump.example"}` → der Schlüssel steht in der Antwort (prüft, dass `extra="allow"` mit `exclude_unset` Extras behält); Altzeile direkt per ORM mit `kind="vnc"` und `tags='[1, "a"]'` → 200 und gleich `to_dict()`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_connections_isolation.py tests/test_connections_import.py
Doku: keine (das Schema steht unter `/api/docs`; CHANGELOG sammelt T12)
Beweis: origin/main@b25c65a6 · Snapshot-Probe (python3, `apps/server/tests/openapi.snapshot.json`): das 2xx-Schema von GET/POST `/api/connections`, PUT `/api/connections/{conn_id}`, POST `/{conn_id}/touch` und POST `/import` nennt keine `properties` (Objekt mit `additionalProperties: true` bzw. Array davon)
Orakel: contract — das Modell gegen `Connection.to_dict` über die echte Route, volle, dünne und Altzeile
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T2 — servers: `ServerOut` und `InternalServerOut` (R-0684)  [ ]
Komponente: server · Dateien: apps/server/app/modules/servers/schemas.py, apps/server/app/modules/servers/router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json
Änderung: `ServerOut` wie `Server.to_dict` (`apps/server/app/modules/servers/models.py:41-55`): `id`, `name`, `hostname: str`, `osType: Optional[str]`, `tags` (Regel 3, Validierung `servers/schemas.py:39`, `:50`), `notes: str`, `createdAt: Optional[str]`, `connections: list[ConnectionOut]` (`include_connections` ist überall `True`, kein Aufrufer setzt es), `frpTunnels: list[FrpTunnelOut]` (`apps/server/app/modules/frp/schemas.py:312`). `InternalServerOut` `{id, hostname, name, tags}` (`servers/router.py:78-86`). Routen `GET ''` (`:90`), `POST ''` (`:103`), `GET /{server_id}` (`:136`), `PUT /{server_id}` (`:144`) mit `response_model_exclude_unset=True` (verschachtelt `serverId` der Verbindungen); intern `GET /servers` (`:70`, `list[InternalServerOut]`). Tests nach Muster; (b) Server mit einer Verbindung und einem Tunnel, Server ohne beides und ohne `os_type`, `tags`, `notes`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_internal_servers.py tests/test_servers_authz.py
Doku: keine
Abhängt von: T1
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: GET/POST `/api/servers`, GET/PUT `/api/servers/{server_id}`, GET `/api/internal/servers` ohne `properties`
Orakel: contract — das Modell gegen `Server.to_dict` über die echte Route
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T3 — frp: Tunnel-Routen mit dem vorhandenen `FrpTunnelOut` (R-0684)  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/tunnel_router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json
Änderung: `response_model=list[FrpTunnelOut]` an `GET /tunnels` (`apps/server/app/modules/frp/tunnel_router.py:26`), `FrpTunnelOut` an `POST /tunnels` (`:67`), `GET /tunnels/{tunnel_id}` (`:153`), `PUT /tunnels/{tunnel_id}` (`:161`). Das Modell (`frp/schemas.py:312-328`) bildet `FrpTunnel.to_dict(mask_secrets=True)` (`frp/models.py:111-131`) schon ab und bleibt unverändert (es steht seit R-0043 im Snapshot unter `FrpServerConfigDetail`); `tags: list[str]` vorher nach Regel 3 an den Schreibern prüfen, bei einem Widerspruch `[?]` statt das Modell zu ändern. Tests nach Muster, `secretKey` ist in jeder Antwort `null`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_frp_tunnels.py
Doku: keine
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: die vier Tunnel-Operationen ohne `properties`; `FrpTunnelOut` steht im Snapshot nur unter `FrpServerConfigDetail.tunnels`
Orakel: contract — `FrpTunnelOut` gegen `FrpTunnel.to_dict(mask_secrets=True)` über die echte Route
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T4 — frp: `VisitorBundleOut` und `ConfigHashOut` (R-0684)  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/schemas.py, apps/server/app/modules/frp/generate_router.py, apps/server/app/modules/frp/provision_router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json
Änderung: In `frp/schemas.py` unter „Responses“: `VisitorBundleOut` `{toml: str, pki: dict[str, Any]}` (`apps/server/app/modules/frp/generate_router.py:159`, `pki` ist heute `{}`), `ConfigHashOut` `{hash: Optional[str]}` (`apps/server/app/modules/frp/provision_router.py:89`, `:92`). Routen `GET /generate/visitor-bundle` (`generate_router.py:137`) und `GET /provision/{server_id}/config-hash` (`provision_router.py:76`). Tests nach Muster; (c) `config-hash` mit und ohne Tunnel (`hash` null bzw. String). Die Nicht-JSON-Routen derselben Dateien bleiben (Spec, Nicht-Ziele).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_frp_tunnels.py tests/test_frp_provision_authz.py
Doku: keine
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: GET `/api/frp/generate/visitor-bundle` und GET `/api/frp/provision/{server_id}/config-hash` ohne `properties`
Orakel: contract — die Modelle gegen die Dict-Literale über die echte Route
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T5 — ansible: `PlaybookOut` und `PlaybookContentOut` (R-0684)  [ ]
Komponente: server · Dateien: apps/server/app/modules/ansible/schemas.py, apps/server/app/modules/ansible/router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json
Änderung: `PlaybookOut` wie `Playbook.to_dict` (`apps/server/app/modules/ansible/models.py:25-34`): `id`, `name`, `filename: str`, `description: str` (`or ""`), `tags` (Regel 3), `createdAt`, `updatedAt: Optional[str]`. `PlaybookContentOut` `{content: str}` (`apps/server/app/modules/ansible/router.py:118`). Routen `GET ''` (`:40`), `POST ''` (`:46`), `GET /{playbook_id}` (`:94`), `GET /{playbook_id}/content` (`:104`), `PUT /{playbook_id}` (`:122`). Tests nach Muster.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_ansible.py
Doku: keine
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: die fünf Playbook-Operationen ohne `properties`
Orakel: contract — das Modell gegen `Playbook.to_dict` über die echte Route
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T6 — provisioning: Token- und Activate-Antworten (R-0684)  [ ]
Komponente: server · Dateien: apps/server/app/modules/provisioning/schemas.py, apps/server/app/modules/provisioning/router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json
Änderung: Neue Datei `provisioning/schemas.py` (SPDX) mit `ProvisionTokenCreatedOut` `{token, expiresAt, serverId, serverName}` (`apps/server/app/modules/provisioning/router.py:83-88`), `ProvisionTokenOut` wie `ProvisionToken.to_dict` (`provisioning/models.py:49-57`: `id`, `serverId`, `expiresAt`, `usedAt: Optional[str]`, `isValid: bool`, `createdAt`), `ActivateOut` (`router.py:209-226`): `serverName`, `apiKey: str`, `monitorApiKey: Optional[str]`, `monitorUrl: Optional[str]`, `frp: Optional[FrpBundleOut]` (`provisioning/helpers.py:77-110`: `None` oder `{config: str, pkiBundle: str}`), `enrollment: ActivateEnrollmentOut` `{token, subjectId, scope: str, enrollPort: int}`. Routen `POST /{server_id}/provision/token` (`router.py:59`), `GET /{server_id}/provision/tokens` (`:92`), `POST /{server_id}/provision/activate` (`:109`). Tests nach Muster; (c) Activate mit und ohne FRP-Konfiguration, mit und ohne erreichbaren Monitoring-Dienst (`monitorApiKey`/`monitorUrl` null). Der Go-Spiegel im Agent bleibt (R-0688).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_provisioning.py
Doku: keine
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: POST `…/provision/token`, GET `…/provision/tokens`, POST `…/provision/activate` ohne `properties`
Orakel: contract — die Modelle gegen die Dict-Literale und `ProvisionToken.to_dict` über die echte Route
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T7 — notifications: Feed, Zähler, Prefs, Ingest (R-0684)  [ ]
Komponente: server · Dateien: apps/server/app/modules/notifications/schemas.py, apps/server/app/modules/notifications/router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json
Änderung: In `notifications/schemas.py`: `NotificationOut` wie `Notification.to_dict` (`apps/server/app/modules/notifications/models.py:104-117`), `NotificationSubscriptionOut` wie `NotificationSubscription.to_dict` (`:68-79`; `categories: Optional[str]`, roher JSON-Text), `NotificationPrefsOut` `{email, telegramChatId: Optional[str], subscriptions: list[NotificationSubscriptionOut]}` (`apps/server/app/modules/notifications/router.py:103-114`), `UnreadCountOut` `{count: int}` (`:76`), `MarkReadOut` `{updated: int}` (`:91`, `:97`), `EventsAcceptedOut` `{notified: int}` (`:217`). Routen `GET ''` (`:48`, heute `list[dict[str, Any]]`), `GET /unread-count` (`:66`), `POST /read` (`:80`), `GET`/`PUT /notification-prefs` (`:118`, `:126`), `POST /events` (`:183`, 202). Nullbarkeit je Spalte aus `models.py`. Tests nach Muster; der SSE-Stream bleibt.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_notifications.py
Doku: keine
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: GET `/api/notifications` (Array offener Objekte), `/unread-count`, `/read`, GET/PUT `/api/users/me/notification-prefs`, POST `/api/internal/events` ohne `properties`
Orakel: contract — die Modelle gegen die `to_dict`-Methoden und Dict-Literale über die echte Route
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T8 — users: `LogoutOut` und `MyServerOut` (R-0684)  [ ]
Komponente: server · Dateien: apps/server/app/modules/users/schemas.py, apps/server/app/modules/users/auth_router.py, apps/server/app/modules/users/router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json
Änderung: `LogoutOut` `{detail: str}` (`apps/server/app/modules/users/auth_router.py:275`) an `POST /logout` (`:243`); `MyServerOut` `{id, name, hostname: str}` (`apps/server/app/modules/users/router.py:243-245`) an `GET /me/servers` (`:243`, `list[MyServerOut]`). Tests nach Muster; für `/me/servers` gibt es heute keinen Test, (b) mit einem Nutzer mit und einem ohne zugeordneten Server.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_auth.py
Doku: keine
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: POST `/api/auth/logout` und GET `/api/users/me/servers` ohne `properties`
Orakel: contract — die Modelle gegen die Dict-Literale über die echte Route
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T9 — hooks: `HookTokenOut` für rotate (R-0684)  [ ]
Komponente: server · Dateien: apps/server/app/modules/hooks/schemas.py, apps/server/app/modules/hooks/router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json
Änderung: `HookTokenOut` `{token: str}` (`apps/server/app/modules/hooks/router.py:334`) an `POST /{hook_id}/rotate` (`:320`). Trigger und `/run` bleiben (Spec, Nicht-Ziele). Tests nach Muster; für rotate gibt es heute keinen Test der Antwortform.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_hooks.py
Doku: keine
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: POST `/api/hooks/{hook_id}/rotate` ohne `properties`
Orakel: contract — das Modell gegen das Dict-Literal über die echte Route
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T10 — enrollment: `EnrollmentGrantOut` (R-0684, R-0407)  [ ]
Komponente: server · Dateien: apps/server/app/modules/enrollment/schemas.py, apps/server/app/modules/enrollment/router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json, apps/web/src/lib/api/mocks.contract.test.ts
Änderung: Neue Datei `enrollment/schemas.py` (SPDX) mit `EnrollmentGrantOut` `{token: str, subjectId: str, scope: str, browser: bool, enrollPort: int, expiresAt: Optional[str]}` wie `_mint_token` (`apps/server/app/modules/enrollment/router.py:44-65`) an `POST /token` (`:79`) und `POST /token/for` (`:108`). Tests nach Muster (Browser- und Nicht-Browser-Grant). Der Web-Mock `makeEnrollmentGrant` (`apps/web/tests/e2e/mocks.ts:123-133`) hat genau diese Schlüssel; damit prüft `apps/web/src/lib/api/mocks.contract.test.ts` die Fixture `enrollment/token/for`: Pin `:146` von 16 auf 17, Kommentar `:142-145` nennt nur noch `audit` als offen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_enrollment_mint.py  und bash scripts/dev/verify.sh web --strict -- src/lib/api/mocks.contract.test.ts
Doku: keine
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: POST `/api/enrollment/token` und `/token/for` ohne `properties`; `mocks.contract.test.ts:142-146` nennt die Fixture als ungeprüft
Orakel: contract — das Modell gegen `_mint_token` über die echte Route; der Web-Mock gegen den Snapshot
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T11 — web: Audit-Mock in der vollen Antwortform  [ ]
Komponente: web · Dateien: apps/web/tests/e2e/mocks.ts
Änderung: Die zwei Zeilen von `AUDIT_ROWS` (`apps/web/tests/e2e/mocks.ts:57-76`) bekommen die fehlenden Schlüssel von `AuditLog.to_dict` (`apps/server/app/modules/audit/models.py:39-53`): `actorId: null`, `objectId: null`, `sourceIp: null`, `status: 'success'`, `detail: null`. Vorbereitung für T12: danach prüft `mocks.contract.test.ts` die Audit-Fixture gegen die required-Liste. `status` ändert die Statuszelle der Audit-Seite (`apps/web/src/pages/Audit.svelte:137`) im Bildvergleich `tests/e2e/smoke.spec.ts-snapshots/audit-chromium-linux.png` (Toleranz 2 %); `smoke.spec.ts` headless fahren, Summary in den Commit-Body. Liegt die Abweichung über der Toleranz: `[?]` (ein neues Referenzbild ist eine sichtbare Teständerung).
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/api/mocks.contract.test.ts
Doku: keine
Beweis: origin/main@b25c65a6 · `mocks.ts:57-76` ohne `actorId`, `objectId`, `sourceIp`, `status`, `detail`; `AuditLog.status` ist `nullable=False` (`audit/models.py:36`)
Orakel: contract — der Mock gegen die Antwortform von `GET /api/audit`
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T12 — audit: `AuditLogOut` (R-0684)  [ ]
Komponente: server · Dateien: apps/server/app/modules/audit/schemas.py, apps/server/app/modules/audit/router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json, apps/web/src/lib/api/mocks.contract.test.ts, CHANGELOG.md
Änderung: Neue Datei `audit/schemas.py` (SPDX) mit `AuditLogOut` wie `AuditLog.to_dict` (`apps/server/app/modules/audit/models.py:39-53`): `id: int`, `timestamp: Optional[str]`, `actorType`, `action`, `status: str`, die übrigen `Optional[str]`. `GET ''` (`apps/server/app/modules/audit/router.py:25`) von `list[dict[str, Any]]` auf `list[AuditLogOut]`. Tests nach Muster. `mocks.contract.test.ts:146` von 17 auf 18, der Kommentar `:142-145` sagt, dass alle 18 Fixtures geprüft werden.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_audit_api.py  und bash scripts/dev/verify.sh web --strict -- src/lib/api/mocks.contract.test.ts
Doku: CHANGELOG.md (Changed, umlautfrei: die OpenAPI-Beschreibung des Servers nennt die Felder aller JSON-Antworten; die Antworten selbst bleiben gleich)
Abhängt von: T11
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: GET `/api/audit` ist ein Array offener Objekte ohne `properties`
Orakel: contract — das Modell gegen `AuditLog.to_dict` über die echte Route; der Web-Mock gegen den Snapshot
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T13 — Monitoring: Checks, Status, Summary, Metriken (R-0685)  [x] (gebaut im Teil-Ledger tasks/api-contracts-monitoring.md, gemergt in 6523be96)
Komponente: monitoring · Dateien: apps/monitoring/app/schemas.py, apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_response_shapes.py, apps/monitoring/tests/openapi.snapshot.json
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @4256d779 2026-10-29T22:12:10+01:00
Review: approve (.ah-out/review/api-contracts-monitoring/T13.verdict.json im Teil-Worktree)
Änderung: In `app/schemas.py`: `MonitorStateOut` wie `MonitorState.to_dict` (`apps/monitoring/app/models.py:125-135`; `details: Any`), `MonitorCheckOut` wie `MonitorCheck.to_dict` (`:77-100`; `config: Any`, nullbare Spalten `Optional`, `state: Optional[MonitorStateOut] = None` nur mit Zustandszeile `:98-99`), `StatusSummaryOut` (sechs `int`, `apps/monitoring/app/routers/checks.py:406-418`), `CheckMetricsOut` `{checkId, checkType, period, data: Any, statusHistory: Any}` (VictoriaMetrics-Durchreiche). Routen in `checks.py`: `127` (list), `146` (201), `187`, `197`, `291` (toggle), `311` (reset), `341` (run), `374` (status), `387` (status/server), `399` (summary), `427` (metrics); alle mit `MonitorCheckOut` mit `response_model_exclude_unset=True`. Neue Datei `tests/test_response_shapes.py` (SPDX) mit dem Testmuster; (c) Check mit und ohne Zustandszeile; Gegenprobe zu `test_stored_json_numbers.py`: Zahlen in `config`/`details` bleiben Zahlen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_checks_crud.py tests/test_checks_metrics.py tests/test_pagination.py tests/test_stored_json_numbers.py
Doku: keine
Beweis: origin/main@b25c65a6 · Snapshot-Probe (python3, `apps/monitoring/tests/openapi.snapshot.json`): alle 37 JSON-Antworten der 44 Operationen haben das Schema `{}`, die übrigen sieben sind 204
Orakel: contract — die Modelle gegen die `to_dict`-Methoden und Dict-Literale über die echte Route
Dedup-Key: ref:cross:openapi:response-side-blind
HEAD: b25c65a6

### T14 — Monitoring: Alert-Regeln und Alert-Log (R-0685)  [x] (gebaut im Teil-Ledger tasks/api-contracts-monitoring.md, gemergt in 6523be96)
Komponente: monitoring · Dateien: apps/monitoring/app/schemas.py, apps/monitoring/app/routers/alerts.py, apps/monitoring/tests/test_response_shapes.py, apps/monitoring/tests/openapi.snapshot.json
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @f96b1028 2026-10-29T22:21:14+01:00
Review: approve (.ah-out/review/api-contracts-monitoring/T14.verdict.json im Teil-Worktree)
Änderung: `AlertRuleOut` wie `MonitorAlertRule.to_dict` (`apps/monitoring/app/models.py:154-173`; `channelConfig: dict[str, Any]` frei, das maskierte `smtp_password` bleibt `***`; `cooldownMinutes`, `enabled` nullbar), `AlertLogOut` wie `MonitorAlertLog.to_dict` (`:201-211`; `id: int`, Spalte `:188`). Routen in `apps/monitoring/app/routers/alerts.py`: `27`, `42` (201), `66` (log), `73`, `82`, `142` (toggle). Tests nach Muster; (b) mit einer Regel mit SMTP-Passwort (maskiert) und einer ohne `channelConfig`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_alert_secrets.py tests/test_stored_json_numbers.py
Doku: keine
Abhängt von: T13
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T13: die sechs Alert-Operationen mit `{}`
Orakel: contract — die Modelle gegen die `to_dict`-Methoden über die echte Route
Dedup-Key: ref:cross:openapi:response-side-blind
HEAD: b25c65a6

### T15 — Monitoring: Wartung und Admin (R-0685)  [x] (gebaut im Teil-Ledger tasks/api-contracts-monitoring.md, gemergt in 6523be96)
Komponente: monitoring · Dateien: apps/monitoring/app/schemas.py, apps/monitoring/app/routers/maintenance.py, apps/monitoring/app/routers/admin.py, apps/monitoring/tests/test_response_shapes.py, apps/monitoring/tests/openapi.snapshot.json
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @725d48b0 2026-10-29T22:24:53+01:00
Review: approve (.ah-out/review/api-contracts-monitoring/T15.verdict.json im Teil-Worktree)
Änderung: `MaintenanceOut` wie `MonitorMaintenance.to_dict` (`apps/monitoring/app/models.py:398-412`; `weekdays: list[Any]`, `enabled` nullbar), `AgentKeyOut` wie `MonitorAgentKey.to_dict` (`:351-357`; die Route `apps/monitoring/app/routers/admin.py:24` setzt `apiKey` beim Anlegen auf den Rohschlüssel, `:47`), `AgentKeyDeletedOut` `{deleted: bool}` (`:55`), `ServerCleanupOut` `{checksDeleted: int, alertsDeleted: int}` (`apps/monitoring/app/template_sync.py:743`). Routen `maintenance.py:39`, `:48` (201), `:59`; `admin.py:24`, `:51`, `:59`. Tests nach Muster. Der Server liest von `POST /agent-keys` nur `apiKey` (`apps/server/app/modules/provisioning/helpers.py:64-66`).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_maintenance_router.py tests/test_admin_router.py
Doku: keine
Abhängt von: T13
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T13: die Wartungs- und Admin-Operationen mit `{}`
Orakel: contract — die Modelle gegen `to_dict` und die Dict-Literale über die echte Route
Dedup-Key: ref:cross:openapi:response-side-blind
HEAD: b25c65a6

### T16 — Monitoring: Templates und Builtin-Update (R-0685)  [x] (gebaut im Teil-Ledger tasks/api-contracts-monitoring.md, gemergt in 6523be96)
Komponente: monitoring · Dateien: apps/monitoring/app/schemas.py, apps/monitoring/app/routers/templates.py, apps/monitoring/tests/test_response_shapes.py, apps/monitoring/tests/openapi.snapshot.json
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @c935cd01 2026-10-29T22:34:15+01:00
Review: approve (.ah-out/review/api-contracts-monitoring/T16.verdict.json im Teil-Worktree)
Änderung: `TemplateOut` wie `MonitorTemplate.to_dict` (`apps/monitoring/app/models.py:232-257`; Check- und Alert-Definitionen `list[dict[str, Any]]`, weil ihre Schlüssel je Definition wechseln), dazu `assignments`, `tagAssignments` (`TemplateAssignmentOut` wie `MonitorTemplateAssignment.to_dict` `:281-289`, `TagAssignmentOut` wie `MonitorTemplateTagAssignment.to_dict` `:329-334`) und `syncResult` (`SyncResultOut` `{created, updated, deleted, servers}`, `apps/monitoring/app/template_sync.py:388-393`) je `Optional[...] = None`; `BuiltinUpdateOut` `{currentVersion, shippedVersion, current, shipped}` (`apps/monitoring/app/routers/templates.py:301-306`). Routen `templates.py:68` (list), `136` (201), `166`, `185` (PUT, mit `syncResult`), `281` (builtin-update GET), `310` (builtin-update POST, mit `syncResult`); alle mit `response_model_exclude_unset=True`. Tests nach Muster; (c) GET ohne, PUT mit `syncResult`, ein Template mit Zuordnungen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_templates_router.py tests/test_template_overrides.py tests/test_stored_json_numbers.py
Doku: keine
Abhängt von: T13
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T13: die sechs Template-Operationen mit `{}`
Orakel: contract — die Modelle gegen `to_dict` und die Ergänzungen der Routen über die echte Route
Dedup-Key: ref:cross:openapi:response-side-blind
HEAD: b25c65a6

### T17 — Monitoring: Zuordnungen, Vorschläge, Tag-Sync (R-0685)  [x] (gebaut im Teil-Ledger tasks/api-contracts-monitoring.md, gemergt in 6523be96)
Komponente: monitoring · Dateien: apps/monitoring/app/schemas.py, apps/monitoring/app/routers/templates.py, apps/monitoring/tests/test_response_shapes.py, apps/monitoring/tests/openapi.snapshot.json, apps/monitoring/tests/test_templates_router.py, CHANGELOG.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @0e23fb01 2026-10-29T22:41:12+01:00
Review: approve (.ah-out/review/api-contracts-monitoring/T17.verdict.json im Teil-Worktree)
Änderung: `ServerAssignmentOut` (`TemplateAssignmentOut` plus `templateName: Optional[str]`, `removedChecks: int`, `apps/monitoring/app/routers/templates.py:97`), `TemplateSuggestionOut` `{slug, templateId, templateName, reason}` (`:255`), `ApplyResultOut` `{checksCreated: list[str], alertsCreated: list[str]}` (die IDs, nicht Zahlen: `apps/monitoring/app/template_sync.py:583-612`) für `assign`, `RestoreOut` `{restored: int}` (`templates.py:399`, `template_sync.py:672-674`), `TagSyncOut` `{created, removed, refreshed: int}` (`apps/monitoring/app/tag_sync.py:142`); `assign-tag` (`templates.py:412`, 201) mit `TagAssignmentOut` aus T16 (`:427`). Routen `templates.py:97`, `:255`, `:332`, `:385`, `:412`, `:453`. Der Stand-in in `tests/test_templates_router.py:195-205` liefert heute `{"created": 2, "removed": 1}` ohne `refreshed` und würde mit dem Modell zur 500: er liefert und erwartet künftig `{"created": 2, "removed": 1, "refreshed": 0}`, die echte Form (keine Test-Löschung, die Assertion prüft weiter die Durchreiche). Tests nach Muster.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_templates_router.py tests/test_template_suggestions.py tests/test_tag_sync.py
Doku: CHANGELOG.md (Changed, umlautfrei: die OpenAPI-Beschreibung des Monitoring-Dienstes nennt die Felder seiner JSON-Antworten; die Antworten bleiben gleich)
Abhängt von: T16
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T13: die sechs Operationen mit `{}`; `test_templates_router.py:200-205` patcht `sync_tag_assignments` auf eine Form, die `tag_sync.py:142` nie liefert
Orakel: contract — die Modelle gegen die Dict-Literale über die echte Route
Dedup-Key: ref:cross:openapi:response-side-blind
HEAD: b25c65a6

### T18 — web: neuer API-Schlüssel zeigt sein Erstelldatum (R-0686)  [ ]
Komponente: web · Dateien: apps/web/src/lib/api/types.ts, apps/web/src/lib/stores/apikeys.ts, apps/web/src/lib/stores/apikeys.test.ts, CHANGELOG.md
Änderung: Zuerst der rote Test in `apikeys.test.ts` (neben `create returns the secret but never stores it in the list`, `:35`): `api.create` liefert `{ key, id, name, permission, created_at: '2026-01-02T03:04:05Z' }`; nach `apikeys.create(...)` trägt der neue Listeneintrag `created_at` mit genau diesem Wert und weiterhin kein `key`. Dann `ApiKeyCreateResult` (`apps/web/src/lib/api/types.ts:61-66`) um `created_at?: string | null` ergänzen (`ApiKeyCreatedResponse`, `apps/server/app/modules/api_keys/schemas.py:18-28`: nicht required, nullbar) und `ApiKey.created_at` (`:53`) ebenso auf `string | null`; der Store übernimmt es (`apps/web/src/lib/stores/apikeys.ts:33-36`). `formatDate` nimmt `null` schon (`src/lib/utils/datetime.ts:24`).
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/stores/apikeys.test.ts
Doku: CHANGELOG.md (Fixed, umlautfrei: ein neu angelegter API-Schluessel zeigt sein Erstelldatum sofort, nicht erst nach dem Neuladen)
Beweis: origin/main@b25c65a6 · der neue Test aus `Änderung:` auf HEAD dreimal rot: Erwartung `created_at: '2026-01-02T03:04:05Z'`, Beobachtung `undefined` (`apikeys.ts:33-36` baut den Eintrag aus `id`, `name`, `permission`)
Orakel: contract — der Listeneintrag gegen die Antwort von `POST /api/api-keys`
Dedup-Key: ref:web:types.ts:handwritten-api-types
HEAD: b25c65a6

### T19 — web: Vertragstest `types.contract.test.ts` und Typ-Korrekturen (R-0686)  [ ]
Komponente: web · Dateien: apps/web/src/lib/api/types.contract.test.ts, apps/web/src/lib/api/types.ts, apps/desktop/ui/src/lib/api/types.ts, docs/developer/cicd.html, docs/en/developer/cicd.html
Änderung: Neue Testdatei (SPDX) nach den Regeln der Spec („Client-Vertragstest“): `typescript` (devDependency) liest `types.ts` per `ts.createSourceFile`, der Test liest `apps/server/tests/openapi.snapshot.json` wie `mocks.contract.test.ts` (`deref`, `shapeOf`). Zuordnungstabelle für die Antwort-Interfaces (`LoginResponse`, `RefreshResponse`, `User`, `EnrollmentGrant`, `ApiKey`, `ApiKeyCreateResult`, `Server`, `Hook`, `HookDetail`, `HookCreateResult`, `HookTokenResult`, `FrpConfig`, `FrpStatusProxy`, `FrpStatus`, `AuditEntry`) und die Anfrage-Interfaces (`UserCreate`, `UserUpdate`, `ApiKeyCreate`, `HookCreate`, `HookUpdate`, `FrpConfigInput`), je mit `omit` und Grund; `HookRunResult` und `ApiError` sind ausgenommen (Nicht-Ziel bzw. kein Schema). Wächter: Paare existieren, Zahl gepinnt, Gegenprobe je Regel an einem synthetischen Paar. Korrekturen, die der Test verlangt, mindestens: `User.created_at` (`types.ts:21`) bekommt `| null` (Schema: required und nullbar, `apps/server/app/modules/users/schemas.py:80`), `FrpConfig.bindPort` (`:147`) `number | null` (`apps/server/app/modules/frp/schemas.py:299`; Leser `FrpConfigModal.svelte:47` hat schon `?? 7000`), `FrpStatusProxy` (`:172-182`) `tunnel` aufnehmen oder in `omit`. Die geteilten Symbole `FrpConfig`, `FrpStatus`, `FrpStatusProxy`, `Server` (`apps/desktop/ui/scripts/sync-from-web.sh:107`) im selben Commit gleich in der Desktop-`types.ts`; `svelte-check` beider Frontends muss grün bleiben.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/api/types.contract.test.ts  und bash apps/desktop/ui/scripts/sync-from-web.sh --check
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html (Abschnitt „Paritäts- und Contract-Gates“ / „Parity and contract gates“: Zeile „Web-Typen gegen den Server-Snapshot“ mit Datei und Regeln)
Abhängt von: T2, T9, T10, T12
Beweis: origin/main@b25c65a6 · Lese-Probe: `ApiKeyCreateResult` (`types.ts:61-66`) ohne `created_at`, `User.created_at?: string` ohne `null`, `FrpConfig.bindPort: number` gegen `Optional[int]`; kein Test liest `types.ts` gegen den Snapshot (`grep -rl openapi.snapshot apps/web/src` → nur `mocks.contract.test.ts`)
Orakel: contract — jedes zugeordnete Interface gegen sein Komponenten-Schema; jede Regel schlägt an ihrem synthetischen Paar an
Dedup-Key: ref:web:types.ts:handwritten-api-types
HEAD: b25c65a6

### T20 — desktop-ui: Vertragstest gegen den Server-Snapshot (R-0687)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.contract.test.ts, apps/desktop/ui/src/lib/api/types.ts, docs/developer/cicd.html, docs/en/developer/cicd.html, DEVELOPMENT.md
Änderung: Neue Testdatei (SPDX), Helfer wie in T19 (Spec, Trade-off 3), liest `apps/server/tests/openapi.snapshot.json`. Zuordnung der Server-Interfaces in `apps/desktop/ui/src/lib/api/types.ts`: Antwort `Connection` (`:7-22`), `Server` (`:24-32`), `Playbook` (`:63-71`), `FrpConfig` (`:85-99`), `FrpTunnel` (`:104-120`), `FrpStatus` (`:150-154`), `FrpStatusProxy`, `FrpProvisionToken` (`:156-163`), `FrpProvisionTokenCreateResult` (`:165-170`), `NotificationItem` (`:557-569`), `NotificationSubscription` (`:572-582`), `NotificationPrefs` (`:584-588`); Anfrage `ServerInput` (`:34-40`) und die übrigen `…Input`-Typen mit Schema. Korrekturen, die der Test verlangt (u. a. `createdAt`, `frpTunnels` an `Server`, `extraConfig` an `FrpConfig`/`FrpTunnel`: aufnehmen oder `omit` mit Grund); die geteilten Symbole bleiben mit Web gleich (`sync-from-web.sh --check`). Aufrufer, die eine Korrektur bricht, per `ledger.sh set-files` aufnehmen.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/api/types.contract.test.ts  und bash apps/desktop/ui/scripts/sync-from-web.sh --check
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html (Zeile „Desktop-Typen gegen beide Snapshots“; der Satz `:334-336` / EN entsprechend sagt künftig, dass Web- und Desktop-Typen gegen den Snapshot geprüft werden, der Agent nicht) · DEVELOPMENT.md (bei `sync-from-web.sh`, `:360-368`: eine geänderte Antwort zieht Modell, Snapshot und beide `types.ts` im selben Commit nach)
Abhängt von: T1 bis T12, T19
Beweis: origin/main@b25c65a6 · kein Test der Desktop-UI liest einen Snapshot (`grep -rl openapi.snapshot apps/desktop/ui/src` leer); `sync-from-web.sh:107` prüft vier von 63 Exporten
Orakel: contract — jedes zugeordnete Interface gegen sein Komponenten-Schema; jede Regel schlägt an ihrem synthetischen Paar an
Dedup-Key: ref:desktop:types.ts:no-contract-test
HEAD: b25c65a6

### T21 — desktop-ui: Monitoring-Typen für Checks, Status, Alerts, Wartung (R-0685, R-0687)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.contract.test.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/models/monitoring.ts
Änderung: Die Zuordnung liest zusätzlich `apps/monitoring/tests/openapi.snapshot.json`: `MonitorCheck` (`types.ts:442-460`), `MonitorCheckState` (`:435-440`), `MonitoringMetricsResponse` (`:507-510`), `AlertRule` (`:521-530`), `AlertLogEntry` (`:541-549`), `MaintenanceWindow` (`:479-492`) und die Anfrage-Typen mit Schema. Korrekturen: `AlertLogEntry.id` `string` → `number` (Spalte `Integer`, `apps/monitoring/app/models.py:188`; `MonitoringLog.svelte:17` nutzt sie nur als each-Key) und `alertRuleId`; `MonitorCheckState` mit `checkId`, `since`, `failCount`, `notifiedStatus` und `| null` an `message`, `lastCheck`, `details`; nullbares `enabled`. Aufrufer: `apps/desktop/ui/src/lib/models/monitoring.ts:196` (`return check.enabled && …` gibt bei `null` `null` zurück) wird `check.enabled === true && …` oder liefert explizit `boolean`; weitere Treffer von `svelte-check` per `ledger.sh set-files` (erwartet u. a. `MonitoringAlerts.svelte:41`, `AlertRuleModal.svelte:47`, `MaintenanceModal.svelte:76`). Die Darstellung gültiger Daten bleibt.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/api/types.contract.test.ts src/lib/models/monitoring.test.ts
Doku: keine
Abhängt von: T13, T14, T15, T20
Beweis: origin/main@b25c65a6 · `AlertLogEntry.id: string` (`types.ts:542`) gegen `id = Column(Integer, …)` (`apps/monitoring/app/models.py:188`), ausgegeben in `:203`
Orakel: contract — die Monitoring-Interfaces gegen den Monitoring-Snapshot
Dedup-Key: ref:desktop:types.ts:no-contract-test
HEAD: b25c65a6

### T22 — desktop-ui: Monitoring-Typen für Templates (R-0685, R-0687)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.contract.test.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/api/monitoring.ts
Änderung: Zuordnung für `MonitoringTemplateFull` (`types.ts:642-658`), `MonitoringTemplateAssignment` (`:629-634`), `MonitoringBuiltinUpdate` (`:674-679`), `TemplateSuggestion` (inline in `apps/desktop/ui/src/lib/api/monitoring.ts:31-36`, nach `types.ts` verschoben, damit der Test es findet) und `TemplateCheckDef`/`TemplateAlertDef` (`:608-627`) in Richtung Anfrage. Korrekturen: `createdAt`, `updatedAt`, `syncResult` an `MonitoringTemplateFull`, `id`, `templateId` an `MonitoringTemplateAssignment` (aufnehmen oder `omit` mit Grund). Aufrufer wie T21.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/api/types.contract.test.ts src/lib/api/monitoring.test.ts
Doku: keine
Abhängt von: T17, T21
Beweis: origin/main@b25c65a6 · `MonitoringTemplateFull` (`types.ts:642-658`) ohne `createdAt`, `updatedAt`, `syncResult`, die `MonitorTemplate.to_dict` (`apps/monitoring/app/models.py:232-257`) bzw. die PUT-Route liefern
Orakel: contract — die Template-Interfaces gegen den Monitoring-Snapshot
Dedup-Key: ref:desktop:types.ts:no-contract-test
HEAD: b25c65a6

### T23 — desktop-ui: Narrowing-Funktionen für `state.details` (R-0687)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/models/checkDetails.ts, apps/desktop/ui/src/lib/models/checkDetails.test.ts
Änderung: Neue Dateien (SPDX). Je Checker-Form eine Funktion `unknown → <Typ> | null` (bzw. Liste leer) für `MonitorZfsDetails`, `MonitorSmartDetails` (kennt auch `{absent: <Grund>}`, `apps/monitoring/app/checkers/smart.py:97`), `MonitorResourceDetails`, `MonitorForecastDetails`, `MonitorServiceDetails`, `MonitorContainerDetails` (`apps/desktop/ui/src/lib/api/types.ts:424-433`). Ein Feld mit falschem Typ gilt als fehlend, gültige Daten kommen unverändert zurück; Vorbild für das Prüfen `SecSystem.svelte:67-97` (`LooseDetails`, `asFlag`, `asCount`). Tests je Funktion: gültige Form, `null`/`undefined`, Feld mit falschem Typ, SMART `absent`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/models/checkDetails.test.ts
Doku: keine
Beweis: origin/main@b25c65a6 · `grep -c ' as Monitor[A-Za-z]*Details' src/components/monitoring/section/*.svelte` (in `apps/desktop/ui`) → 9 Casts in sechs Dateien; `MonitorCheckDetails` endet mit `Record<string, unknown>` (`types.ts:433`), jeder Cast kompiliert
Orakel: contract — die Narrower gegen die Formen der Checker
Dedup-Key: ref:desktop:types.ts:no-contract-test
HEAD: b25c65a6

### T24 — desktop-ui: SecZfs, SecSmart, SecForecast ohne Cast (R-0687)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/section/SecZfs.svelte, apps/desktop/ui/src/components/monitoring/section/SecSmart.svelte, apps/desktop/ui/src/components/monitoring/section/SecForecast.svelte, apps/desktop/ui/src/components/monitoring/section/SecSmart.test.ts, apps/desktop/ui/src/components/monitoring/section/SecForecast.test.ts
Änderung: Die Casts `SecZfs.svelte:34`, `:38`, `SecSmart.svelte:28`, `SecForecast.svelte:22` werden Aufrufe der Narrower aus T23. Die Darstellung gültiger Daten bleibt; SMART `absent` wird typisiert, nicht angezeigt (eine Anzeige wäre sichtbares Verhalten). Neue Tests (SPDX) für SecSmart und SecForecast wie `SecZfs.test.ts`: gültige Daten rendern wie heute, `details` mit falschem Feldtyp rendert die leere Sektion statt zu werfen. Suite vor und nach dem Diff grün, beide Summary-Zeilen in den Commit-Body.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/section/SecZfs.test.ts src/components/monitoring/section/SecSmart.test.ts src/components/monitoring/section/SecForecast.test.ts
Doku: keine
Abhängt von: T23
Beweis: origin/main@b25c65a6 · Grep wie T23: 4 der 9 Casts in diesen drei Dateien
Orakel: metric — Casts `as Monitor…Details` in den drei Dateien
Metrik: `grep -c ' as Monitor[A-Za-z]*Details'` (GNU grep) über SecZfs, SecSmart, SecForecast: 4 → 0
Dedup-Key: ref:desktop:types.ts:no-contract-test
HEAD: b25c65a6

### T25 — desktop-ui: SecLive, SecServices, SecDocker ohne Cast (R-0687)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/section/SecLive.svelte, apps/desktop/ui/src/components/monitoring/section/SecServices.svelte, apps/desktop/ui/src/components/monitoring/section/SecDocker.svelte, apps/desktop/ui/src/components/monitoring/section/SecLive.test.ts, apps/desktop/ui/src/components/monitoring/section/SecServices.test.ts, apps/desktop/ui/src/components/monitoring/section/SecDocker.test.ts
Änderung: Die Casts `SecLive.svelte:79`, `:118`, `:129`, `SecServices.svelte:77`, `SecDocker.svelte:89` werden Aufrufe der Narrower aus T23. Je vorhandene Testdatei ein Fall mit falschem Feldtyp in `details` (leere bzw. Rückfall-Darstellung statt Wurf); die bestehenden Fälle bleiben unverändert grün. Suite vor und nach dem Diff grün, beide Summary-Zeilen in den Commit-Body.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/section/SecLive.test.ts src/components/monitoring/section/SecServices.test.ts src/components/monitoring/section/SecDocker.test.ts
Doku: keine
Abhängt von: T23
Beweis: origin/main@b25c65a6 · Grep wie T23: 5 der 9 Casts in diesen drei Dateien
Orakel: metric — Casts `as Monitor…Details` in den drei Dateien
Metrik: `grep -c ' as Monitor[A-Za-z]*Details'` (GNU grep) über SecLive, SecServices, SecDocker: 5 → 0
Dedup-Key: ref:desktop:types.ts:no-contract-test
HEAD: b25c65a6
