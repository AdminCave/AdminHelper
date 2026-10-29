<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# API-Verträge: Antwortmodelle für Server und Monitoring, Client-Typen gegen den Snapshot (Teil server) — Task-Ledger
Status: bereit · Branch: feature/api-contracts-server · Review: pro Task
Spec: docs/features/api-contracts.md (Roadmap R-0684; R-0407 erledigt T10 mit)
Heavy: none — Teil-Ledger von tasks/api-contracts.md (T1–T12); die schwere Prüfung (linux-full + scenario + windows) fährt das Vorhabens-Ledger vor dem Merge
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

Teil-Ledger (Kevin 2026-10-23, Spec Trade-off 8): T1–T12 aus `tasks/api-contracts.md`, gemergt in `feature/api-contracts`. CHANGELOG-Einträge in `changelog.d/api-contracts-server.md` statt `CHANGELOG.md` (Konvention seit dem Plan).

### T1 — connections: `ConnectionOut` und `ConnectionImportResult` (R-0684)  [x]
Komponente: server · Dateien: apps/server/app/modules/connections/schemas.py, apps/server/app/modules/connections/router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @d03d3794 2026-10-29T22:00:37+01:00
Review: approve (.ah-out/review/api-contracts-server/T1.verdict.json)
Änderung: Vorher die offizielle FastAPI-Doku zu Response Model und `response_model_exclude_unset` lesen (WebFetch), Ergebnis in den Commit-Body. Neu in `connections/schemas.py`: `ConnectionOut` mit `model_config = ConfigDict(extra="allow")` und den Schlüsseln von `Connection.to_dict` (`apps/server/app/modules/connections/models.py:66-90`): `id`, `name`, `kind` als `str` (Spalte `:49` nicht eingeschränkt, die Import-Validierung gibt es erst seit v0.36.0, Commit `84d4eaa8`), `host`, `username`, `domain`, `keyPath`, `url`, `notes` als `str` (`or ""`), `port: Optional[int]`, `tags: list[Any]`, `trustCert: bool`, `lastUsed: Optional[str]`, `serverId: Optional[str] = None` (nur gesetzt, wenn es einen Server gibt). `ConnectionImportResult` `{imported: int, mode: str}` (`router.py:306`). Routen `GET ''` (`router.py:95`, `list[ConnectionOut]`), `POST ''` (`:110`), `PUT /{conn_id}` (`:138`), `POST /{conn_id}/touch` (`:173`) mit `response_model_exclude_unset=True`; `POST /import` (`:237`). Neue Datei `tests/test_response_shapes.py` mit dem Testmuster; (c) Verbindung ohne Server → kein `serverId`; Verbindung mit `extra_data` `{"proxyJump": "jump.example"}` → der Schlüssel steht in der Antwort (prüft, dass `extra="allow"` mit `exclude_unset` Extras behält); Altzeile direkt per ORM mit `kind="vnc"` und `tags='[1, "a"]'` → 200 und gleich `to_dict()`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_connections_isolation.py tests/test_connections_import.py
Doku: keine (das Schema steht unter `/api/docs`; CHANGELOG sammelt T12)
Beweis: origin/main@b25c65a6 · Snapshot-Probe (python3, `apps/server/tests/openapi.snapshot.json`): das 2xx-Schema von GET/POST `/api/connections`, PUT `/api/connections/{conn_id}`, POST `/{conn_id}/touch` und POST `/import` nennt keine `properties` (Objekt mit `additionalProperties: true` bzw. Array davon)
Orakel: contract — das Modell gegen `Connection.to_dict` über die echte Route, volle, dünne und Altzeile
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T2 — servers: `ServerOut` und `InternalServerOut` (R-0684)  [x]
Komponente: server · Dateien: apps/server/app/modules/servers/schemas.py, apps/server/app/modules/servers/router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @775ed939 2026-10-29T22:06:21+01:00
Review: approve (.ah-out/review/api-contracts-server/T2.verdict.json)
Änderung: `ServerOut` wie `Server.to_dict` (`apps/server/app/modules/servers/models.py:41-55`): `id`, `name`, `hostname: str`, `osType: Optional[str]`, `tags` (Regel 3, Validierung `servers/schemas.py:39`, `:50`), `notes: str`, `createdAt: Optional[str]`, `connections: list[ConnectionOut]` (`include_connections` ist überall `True`, kein Aufrufer setzt es), `frpTunnels: list[FrpTunnelOut]` (`apps/server/app/modules/frp/schemas.py:312`). `InternalServerOut` `{id, hostname, name, tags}` (`servers/router.py:78-86`). Routen `GET ''` (`:90`), `POST ''` (`:103`), `GET /{server_id}` (`:136`), `PUT /{server_id}` (`:144`) mit `response_model_exclude_unset=True` (verschachtelt `serverId` der Verbindungen); intern `GET /servers` (`:70`, `list[InternalServerOut]`). Tests nach Muster; (b) Server mit einer Verbindung und einem Tunnel, Server ohne beides und ohne `os_type`, `tags`, `notes`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_internal_servers.py tests/test_servers_authz.py
Doku: keine
Abhängt von: T1
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: GET/POST `/api/servers`, GET/PUT `/api/servers/{server_id}`, GET `/api/internal/servers` ohne `properties`
Orakel: contract — das Modell gegen `Server.to_dict` über die echte Route
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T3 — frp: Tunnel-Routen mit dem vorhandenen `FrpTunnelOut` (R-0684)  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/tunnel_router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json, apps/server/app/modules/frp/schemas.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @6cf32628 2026-10-29T22:16:45+01:00
Review: approve (.ah-out/review/api-contracts-server/T3.verdict.json)
Änderung: `response_model=list[FrpTunnelOut]` an `GET /tunnels` (`apps/server/app/modules/frp/tunnel_router.py:26`), `FrpTunnelOut` an `POST /tunnels` (`:67`), `GET /tunnels/{tunnel_id}` (`:153`), `PUT /tunnels/{tunnel_id}` (`:161`). Das Modell (`frp/schemas.py:312-328`) bildet `FrpTunnel.to_dict(mask_secrets=True)` (`frp/models.py:111-131`) schon ab und bleibt unverändert (es steht seit R-0043 im Snapshot unter `FrpServerConfigDetail`); `tags: list[str]` vorher nach Regel 3 an den Schreibern prüfen, bei einem Widerspruch `[?]` statt das Modell zu ändern. Tests nach Muster, `secretKey` ist in jeder Antwort `null`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_frp_tunnels.py
Doku: keine
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: die vier Tunnel-Operationen ohne `properties`; `FrpTunnelOut` steht im Snapshot nur unter `FrpServerConfigDetail.tunnels`
Orakel: contract — `FrpTunnelOut` gegen `FrpTunnel.to_dict(mask_secrets=True)` über die echte Route
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T4 — frp: `VisitorBundleOut` und `ConfigHashOut` (R-0684)  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/schemas.py, apps/server/app/modules/frp/generate_router.py, apps/server/app/modules/frp/provision_router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @13295a7d 2026-10-29T23:22:22+01:00
Review: approve (.ah-out/review/api-contracts-server/T4.verdict.json)
Änderung: In `frp/schemas.py` unter „Responses“: `VisitorBundleOut` `{toml: str, pki: dict[str, Any]}` (`apps/server/app/modules/frp/generate_router.py:159`, `pki` ist heute `{}`), `ConfigHashOut` `{hash: Optional[str]}` (`apps/server/app/modules/frp/provision_router.py:89`, `:92`). Routen `GET /generate/visitor-bundle` (`generate_router.py:137`) und `GET /provision/{server_id}/config-hash` (`provision_router.py:76`). Tests nach Muster; (c) `config-hash` mit und ohne Tunnel (`hash` null bzw. String). Die Nicht-JSON-Routen derselben Dateien bleiben (Spec, Nicht-Ziele).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_frp_tunnels.py tests/test_frp_provision_authz.py
Doku: keine
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: GET `/api/frp/generate/visitor-bundle` und GET `/api/frp/provision/{server_id}/config-hash` ohne `properties`
Orakel: contract — die Modelle gegen die Dict-Literale über die echte Route
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T5 — ansible: `PlaybookOut` und `PlaybookContentOut` (R-0684)  [x]
Komponente: server · Dateien: apps/server/app/modules/ansible/schemas.py, apps/server/app/modules/ansible/router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @07695b0c 2026-10-29T22:23:38+01:00
Review: approve (.ah-out/review/api-contracts-server/T5.verdict.json)
Änderung: `PlaybookOut` wie `Playbook.to_dict` (`apps/server/app/modules/ansible/models.py:25-34`): `id`, `name`, `filename: str`, `description: str` (`or ""`), `tags` (Regel 3), `createdAt`, `updatedAt: Optional[str]`. `PlaybookContentOut` `{content: str}` (`apps/server/app/modules/ansible/router.py:118`). Routen `GET ''` (`:40`), `POST ''` (`:46`), `GET /{playbook_id}` (`:94`), `GET /{playbook_id}/content` (`:104`), `PUT /{playbook_id}` (`:122`). Tests nach Muster.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_ansible.py
Doku: keine
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: die fünf Playbook-Operationen ohne `properties`
Orakel: contract — das Modell gegen `Playbook.to_dict` über die echte Route
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T6 — provisioning: Token- und Activate-Antworten (R-0684)  [x]
Komponente: server · Dateien: apps/server/app/modules/provisioning/schemas.py, apps/server/app/modules/provisioning/router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @a8dcceaf 2026-10-29T22:29:01+01:00
Review: approve (.ah-out/review/api-contracts-server/T6.verdict.json)
Änderung: Neue Datei `provisioning/schemas.py` (SPDX) mit `ProvisionTokenCreatedOut` `{token, expiresAt, serverId, serverName}` (`apps/server/app/modules/provisioning/router.py:83-88`), `ProvisionTokenOut` wie `ProvisionToken.to_dict` (`provisioning/models.py:49-57`: `id`, `serverId`, `expiresAt`, `usedAt: Optional[str]`, `isValid: bool`, `createdAt`), `ActivateOut` (`router.py:209-226`): `serverName`, `apiKey: str`, `monitorApiKey: Optional[str]`, `monitorUrl: Optional[str]`, `frp: Optional[FrpBundleOut]` (`provisioning/helpers.py:77-110`: `None` oder `{config: str, pkiBundle: str}`), `enrollment: ActivateEnrollmentOut` `{token, subjectId, scope: str, enrollPort: int}`. Routen `POST /{server_id}/provision/token` (`router.py:59`), `GET /{server_id}/provision/tokens` (`:92`), `POST /{server_id}/provision/activate` (`:109`). Tests nach Muster; (c) Activate mit und ohne FRP-Konfiguration, mit und ohne erreichbaren Monitoring-Dienst (`monitorApiKey`/`monitorUrl` null). Der Go-Spiegel im Agent bleibt (R-0688).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_provisioning.py
Doku: keine
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: POST `…/provision/token`, GET `…/provision/tokens`, POST `…/provision/activate` ohne `properties`
Orakel: contract — die Modelle gegen die Dict-Literale und `ProvisionToken.to_dict` über die echte Route
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T7 — notifications: Feed, Zähler, Prefs, Ingest (R-0684)  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/schemas.py, apps/server/app/modules/notifications/router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @da026cb8 2026-10-29T22:39:33+01:00
Review: approve (.ah-out/review/api-contracts-server/T7.verdict.json)
Änderung: In `notifications/schemas.py`: `NotificationOut` wie `Notification.to_dict` (`apps/server/app/modules/notifications/models.py:104-117`), `NotificationSubscriptionOut` wie `NotificationSubscription.to_dict` (`:68-79`; `categories: Optional[str]`, roher JSON-Text), `NotificationPrefsOut` `{email, telegramChatId: Optional[str], subscriptions: list[NotificationSubscriptionOut]}` (`apps/server/app/modules/notifications/router.py:103-114`), `UnreadCountOut` `{count: int}` (`:76`), `MarkReadOut` `{updated: int}` (`:91`, `:97`), `EventsAcceptedOut` `{notified: int}` (`:217`). Routen `GET ''` (`:48`, heute `list[dict[str, Any]]`), `GET /unread-count` (`:66`), `POST /read` (`:80`), `GET`/`PUT /notification-prefs` (`:118`, `:126`), `POST /events` (`:183`, 202). Nullbarkeit je Spalte aus `models.py`. Tests nach Muster; der SSE-Stream bleibt.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_notifications.py
Doku: keine
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: GET `/api/notifications` (Array offener Objekte), `/unread-count`, `/read`, GET/PUT `/api/users/me/notification-prefs`, POST `/api/internal/events` ohne `properties`
Orakel: contract — die Modelle gegen die `to_dict`-Methoden und Dict-Literale über die echte Route
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T8 — users: `LogoutOut` und `MyServerOut` (R-0684)  [x]
Komponente: server · Dateien: apps/server/app/modules/users/schemas.py, apps/server/app/modules/users/auth_router.py, apps/server/app/modules/users/router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @3ab1b6dc 2026-10-29T22:44:41+01:00
Review: approve (.ah-out/review/api-contracts-server/T8.verdict.json)
Änderung: `LogoutOut` `{detail: str}` (`apps/server/app/modules/users/auth_router.py:275`) an `POST /logout` (`:243`); `MyServerOut` `{id, name, hostname: str}` (`apps/server/app/modules/users/router.py:243-245`) an `GET /me/servers` (`:243`, `list[MyServerOut]`). Tests nach Muster; für `/me/servers` gibt es heute keinen Test, (b) mit einem Nutzer mit und einem ohne zugeordneten Server.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_auth.py
Doku: keine
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: POST `/api/auth/logout` und GET `/api/users/me/servers` ohne `properties`
Orakel: contract — die Modelle gegen die Dict-Literale über die echte Route
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T9 — hooks: `HookTokenOut` für rotate (R-0684)  [x]
Komponente: server · Dateien: apps/server/app/modules/hooks/schemas.py, apps/server/app/modules/hooks/router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @199d8cb6 2026-10-29T22:54:18+01:00
Review: approve (.ah-out/review/api-contracts-server/T9.verdict.json)
Änderung: `HookTokenOut` `{token: str}` (`apps/server/app/modules/hooks/router.py:334`) an `POST /{hook_id}/rotate` (`:320`). Trigger und `/run` bleiben (Spec, Nicht-Ziele). Tests nach Muster; für rotate gibt es heute keinen Test der Antwortform.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_hooks.py
Doku: keine
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: POST `/api/hooks/{hook_id}/rotate` ohne `properties`
Orakel: contract — das Modell gegen das Dict-Literal über die echte Route
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T10 — enrollment: `EnrollmentGrantOut` (R-0684, R-0407)  [x]
Komponente: server · Dateien: apps/server/app/modules/enrollment/schemas.py, apps/server/app/modules/enrollment/router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json, apps/web/src/lib/api/mocks.contract.test.ts
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @4c0f800a 2026-10-29T23:01:23+01:00
Review: approve (.ah-out/review/api-contracts-server/T10.verdict.json)
Änderung: Neue Datei `enrollment/schemas.py` (SPDX) mit `EnrollmentGrantOut` `{token: str, subjectId: str, scope: str, browser: bool, enrollPort: int, expiresAt: Optional[str]}` wie `_mint_token` (`apps/server/app/modules/enrollment/router.py:44-65`) an `POST /token` (`:79`) und `POST /token/for` (`:108`). Tests nach Muster (Browser- und Nicht-Browser-Grant). Der Web-Mock `makeEnrollmentGrant` (`apps/web/tests/e2e/mocks.ts:123-133`) hat genau diese Schlüssel; damit prüft `apps/web/src/lib/api/mocks.contract.test.ts` die Fixture `enrollment/token/for`: Pin `:146` von 16 auf 17, Kommentar `:142-145` nennt nur noch `audit` als offen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_enrollment_mint.py  und bash scripts/dev/verify.sh web --strict -- src/lib/api/mocks.contract.test.ts
Doku: keine
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: POST `/api/enrollment/token` und `/token/for` ohne `properties`; `mocks.contract.test.ts:142-146` nennt die Fixture als ungeprüft
Orakel: contract — das Modell gegen `_mint_token` über die echte Route; der Web-Mock gegen den Snapshot
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T11 — web: Audit-Mock in der vollen Antwortform  [x]
Komponente: web · Dateien: apps/web/tests/e2e/mocks.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @18902239 2026-10-29T23:08:20+01:00
Review: approve (.ah-out/review/api-contracts-server/T11.verdict.json)
Änderung: Die zwei Zeilen von `AUDIT_ROWS` (`apps/web/tests/e2e/mocks.ts:57-76`) bekommen die fehlenden Schlüssel von `AuditLog.to_dict` (`apps/server/app/modules/audit/models.py:39-53`): `actorId: null`, `objectId: null`, `sourceIp: null`, `status: 'success'`, `detail: null`. Vorbereitung für T12: danach prüft `mocks.contract.test.ts` die Audit-Fixture gegen die required-Liste. `status` ändert die Statuszelle der Audit-Seite (`apps/web/src/pages/Audit.svelte:137`) im Bildvergleich `tests/e2e/smoke.spec.ts-snapshots/audit-chromium-linux.png` (Toleranz 2 %); `smoke.spec.ts` headless fahren, Summary in den Commit-Body. Liegt die Abweichung über der Toleranz: `[?]` (ein neues Referenzbild ist eine sichtbare Teständerung).
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/api/mocks.contract.test.ts
Doku: keine
Beweis: origin/main@b25c65a6 · `mocks.ts:57-76` ohne `actorId`, `objectId`, `sourceIp`, `status`, `detail`; `AuditLog.status` ist `nullable=False` (`audit/models.py:36`)
Orakel: contract — der Mock gegen die Antwortform von `GET /api/audit`
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

### T12 — audit: `AuditLogOut` (R-0684)  [x]
Komponente: server · Dateien: apps/server/app/modules/audit/schemas.py, apps/server/app/modules/audit/router.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json, apps/web/src/lib/api/mocks.contract.test.ts, changelog.d/api-contracts-server.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @3f8ff406 2026-10-29T23:17:06+01:00
Review: approve (.ah-out/review/api-contracts-server/T12.verdict.json)
Änderung: Neue Datei `audit/schemas.py` (SPDX) mit `AuditLogOut` wie `AuditLog.to_dict` (`apps/server/app/modules/audit/models.py:39-53`): `id: int`, `timestamp: Optional[str]`, `actorType`, `action`, `status: str`, die übrigen `Optional[str]`. `GET ''` (`apps/server/app/modules/audit/router.py:25`) von `list[dict[str, Any]]` auf `list[AuditLogOut]`. Tests nach Muster. `mocks.contract.test.ts:146` von 17 auf 18, der Kommentar `:142-145` sagt, dass alle 18 Fixtures geprüft werden.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_audit_api.py  und bash scripts/dev/verify.sh web --strict -- src/lib/api/mocks.contract.test.ts
Doku: changelog.d/api-contracts-server.md (Changed, umlautfrei: die OpenAPI-Beschreibung des Servers nennt die Felder aller JSON-Antworten; die Antworten selbst bleiben gleich)
Abhängt von: T11
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T1: GET `/api/audit` ist ein Array offener Objekte ohne `properties`
Orakel: contract — das Modell gegen `AuditLog.to_dict` über die echte Route; der Web-Mock gegen den Snapshot
Dedup-Key: ref:server:routers:missing-response-models
HEAD: b25c65a6

## Entscheidungen
- T1: `ConnectionOut.tags` ist `Any`, nicht `list[Any]` wie im Plan: ein Import vor v0.36.0 schrieb einen
  Nicht-Listen-Wert unverändert, eine solche Altzeile machte die ganze Liste zur 500 (Regel 3). Der Snapshot zeigt
  `tags` damit ungetypt; die Client-Vertragstests (T19/T20) lesen es als unbekannt.
- T3: `GET /api/frp/tunnels` gibt Nicht-Admins seit dem Plan nur die `_MAPPING_FIELDS` (TunnelMapping des Desktops);
  ein reines `list[FrpTunnelOut]` machte ihre Liste zur 500. Deklariert ist `list[FrpTunnelOut | TunnelMappingOut]`
  mit `union_mode="left_to_right"` (die volle Zeile zuerst; die Gegenprobe mit umgedrehter Reihenfolge: 2 failed).
- T10: Der Pin in `mocks.contract.test.ts` stand schon auf 17 (nicht 16 wie im Plan, ein früherer Merge hob ihn);
  mit der Enrollment-Fixture geht er auf 18, offen bleibt nur `audit` (T12).
- T12: Der Pin geht von 18 auf 19 (Plan: 17 → 18, Folge der Verschiebung aus T10); damit erreichen alle Fixtures die
  Schlüsselprüfung. Der CHANGELOG-Eintrag folgt der Form von `api-contracts-monitoring` (Server-API statt Monitoring-API).
