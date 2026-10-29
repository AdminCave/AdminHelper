<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Audit-Abdeckung und Admin-Meldungen: Hooks, Provisionierungs-Token, Monitoring-Proxy, Hochstufung — Task-Ledger
Status: erledigt · Branch: feature/audit-coverage · Review: pro Task
Spec: docs/features/audit-coverage.md (Härtung, Kevin 2026-10-22)
Heavy: linux-full — Route-Handler unter `apps/server` ändern sich (Hooks, Provisionierungs-Token, Monitoring-Proxy mit neuer DB-Abhängigkeit im `async`-Pfad, Benutzer), die Sammelläufe erzeugen Provisionierungs-Token und schreiben über den Proxy; Routen, Schemas und OpenAPI bleiben, keine Migration, kein Gateway-, PKI-, FRP-, Compose- oder Install-Pfad, kein Cross-Host-Datenpfad (kein `scenario`)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Hook-Aktionen der Admins, das Erzeugen von Provisionierungs-Token und Schreibzugriffe über den
Monitoring-Proxy stehen im Audit-Trail. (2) `user.updated` nennt die geänderten Felder. (3) Eine Hochstufung zum Admin
feuert das Event `user.promoted`, die Glocke „Sicherheit“ meldet sie; `app.cli create-admin` feuert `user.created`.
Zeilenangaben: origin/main@b1432223; der builder greppt sie vor dem Schreiben neu (PR #254 ist dann gemergt).

Für alle Tasks:
- Reihenfolge: T1, T2, T3, T4 unabhängig; T5 nach T4 (dieselbe Funktion `update_user`); T6 nach T5; T7 unabhängig;
  T8 nach T1–T7, T9 nach T1–T7.
- Security-Prüfer zusätzlich (Risikoliste `scripts/dev/review-risk.txt`): T3 (`monitoring_proxy/*`), T4 und T5
  (`users/*`, T5 auch `modules/*/schemas.py`), T6 (`notifications/*`).
- Muster eines Eintrags wie `apps/server/app/modules/users/router.py:86-93`: `audit.record(db, "<aktion>",
  actor=actor_from_request(request), object_type=…, object_id=…, object_label=…)` nach dem `db.commit()` der Aktion.
- Keine Routen-Docstrings ergänzen oder ändern (der Docstring ist die OpenAPI-`description`); ein Warum an einer
  Route als `#`-Kommentar. `request: Request` und `Depends(get_db)` ändern das Schema nicht; T1–T3 fahren
  `tests/test_openapi_snapshot.py` mit.
- Tests über `test_client` mit Bearer eines Admins wie `apps/server/tests/test_audit_wiring.py:18-25`; Audit-Zeilen
  per `db_session.query(AuditLog).filter(AuditLog.action == …)`. Ein Test prüft nie nur „keine Zeile“, ohne im selben
  Test oder daneben dieselbe Route mit Zeile zu zeigen.
- Events in Tests: `app.core.events._executor` durch einen Rekorder ersetzen (`submit(fn, *args)` merkt sich `args`,
  gibt ein erledigtes `Future` zurück, wie `_DiscardingExecutor` in `apps/server/tests/conftest.py:95-99`); so bleibt
  der Test unabhängig davon, wie ein Modul `fire_event` importiert.
- Neue Code-Strings englisch; bestehende deutsche Texte bleiben. Platzhalter-Adressen nur aus RFC 5737, Hosts unter
  `.example`.

### T1 — Hooks: Audit-Einträge für Anlegen, Ändern, Löschen, Ein/Aus, Token-Rotation, manuellen Lauf  [x]
Komponente: server · Dateien: apps/server/app/modules/hooks/router.py, apps/server/tests/test_hooks_audit.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @c4271187 2026-10-22T12:20:24+02:00
Review: approve (.ah-out/review/audit-coverage/T1.verdict.json)
Änderung: `hooks/router.py` importiert `from app.core.request_context import actor_from_request` und `from app.modules.audit import service as audit`; `create_hook` (`:142-175`), `update_hook` (`:256-288`), `delete_hook` (`:291-299`), `toggle_hook` (`:302-316`), `rotate_hook_token` (`:319-333`) und `run_hook_manually` (`:336-363`) bekommen `request: Request` (`Request` ist schon importiert, `:10`). Nach dem jeweiligen `db.commit()` genau ein Eintrag mit `object_type="hook"`, `object_id=hook.id`, `object_label=hook.name`: `hook.created` mit `detail=f"type={hook.hook_type}"`; `hook.updated` mit `detail` = die geänderten Spalten in fester Reihenfolge `name`, `description`, `script`, `event_triggers`, `schedule_interval`, `enabled` (Vorher-Nachher-Vergleich der Spaltenwerte; `enabled` als `enabled=true|false`; durch `", "` getrennt; nichts geändert → `detail=None`); `hook.deleted` (Id und Name vor dem `db.delete` merken); `/toggle` → `hook.updated` mit `detail` `enabled=true|false`; `hook.token_rotated`; `/run` → `hook.run` nach dem Lauf, `status="success"`, wenn `result.get("success") is True`, sonst `"failure"` (auch im `except`-Zweig `:360-361`), ohne `detail`. Die Antworten der Routen bleiben gleich. Webhook-Trigger (`:185-245`) und GET-Routen schreiben nichts (Spec, Nicht-Ziele). Neue Testdatei `tests/test_hooks_audit.py` (SPDX-Header wie `tests/test_audit_wiring.py:1-3`; `run_hook_script` in `app.modules.hooks.router` ersetzt): (a) Anlegen eines Webhook-Hooks → genau ein `hook.created` mit Actor `user`/`admin`, Objekt, `detail` `type=webhook`, `status` `success`; das Token aus der Antwort steht in keiner Spalte der Zeile; (b) `PUT` mit `script` und `enabled=false` → `hook.updated` mit `detail` `script, enabled=false`; `PUT` mit denselben Werten wie gespeichert → ein `hook.updated` mit `detail` `None`; ein `PUT` mit unbekanntem Event (422) → keine Zeile; (c) `DELETE` → `hook.deleted` mit Id und Name; (d) `/toggle` zweimal → zwei `hook.updated` mit `enabled=false`, dann `enabled=true`; (e) `/rotate` → `hook.token_rotated`, das neue Token in keiner Spalte; (f) `/run` mit Stand-in `{"success": True, …}` → `hook.run` `success`, mit `{"success": False, "error": "boom-ae1f", …}` → `failure` und `boom-ae1f` in keiner Spalte, mit einem Stand-in, der wirft → `failure`; (g) GET-Liste und GET eines Hooks → keine Zeile (neben (a)). Zuerst rot: (a)–(f) auf HEAD.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hooks_audit.py tests/test_hooks.py tests/test_openapi_snapshot.py
Doku: keine eigene (T8 und T9 beschreiben die Einträge)
Beweis: Code-Lesung apps/server/app/modules/hooks/router.py:10-35 (kein Import von `audit`), :142-363 (kein `audit.record`)
Orakel: contract — je schreibender Hook-Route genau eine Audit-Zeile mit Actor, Objekt und Status
HEAD: b1432223
Semantik: `docs/admin/betrieb.html:130` — „Sicherheits- und änderungsrelevante Aktionen werden in einem <strong>append-only Audit-Trail</strong> protokolliert — mit Actor …, Quell-IP und Zeitstempel.“ (EN `docs/en/admin/operations.html:89`; nach PR #254 `:131` bzw. `:90`)

### T2 — Provisionierungs-Token: Audit-Eintrag beim Erzeugen  [x]
Komponente: server · Dateien: apps/server/app/modules/provisioning/router.py, apps/server/tests/test_provision_token_audit.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @f122fc48 2026-10-22T10:32:21+02:00
Review: approve (.ah-out/review/audit-coverage/T2.verdict.json)
Änderung: `create_provision_token` (`apps/server/app/modules/provisioning/router.py:58-88`) bekommt `request: Request` (Import `:39`; `actor_from_request` und `audit` sind schon importiert, `:46`, `:49`) und schreibt nach `db.commit()`/`db.refresh(token)` (`:80-81`) genau einen Eintrag `provision.token.minted` mit `object_type="server"`, `object_id=server_id`, `object_label=server.name`, `detail="ttl=24h"`. Die Antwort bleibt gleich; `list_provision_tokens` (GET) schreibt nichts. Neue Testdatei `tests/test_provision_token_audit.py` (SPDX-Header; Server anlegen wie `_make_server` in `tests/test_provisioning.py`): (a) `POST /api/servers/<id>/provision/token` als Admin → genau eine Zeile `provision.token.minted` mit Actor `user`/`admin`, Objekt `server`/`<id>`/`<name>`, `detail` `ttl=24h`, `status` `success`; weder das Token aus der Antwort noch `hash_api_key(token)` steht in einer Spalte; (b) unbekannter Server (404) → keine Zeile; (c) `GET …/provision/tokens` → keine Zeile. Zuerst rot: (a) auf HEAD.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_provision_token_audit.py tests/test_provisioning.py tests/test_openapi_snapshot.py
Doku: keine eigene (T8 und T9)
Beweis: Code-Lesung apps/server/app/modules/provisioning/router.py:58-88 (kein `audit.record`; `activate_provision` schreibt schon, `:190-207`)
Orakel: contract — das Erzeugen eines Provisionierungs-Tokens ergibt genau eine Audit-Zeile ohne Token
HEAD: b1432223
Semantik: wie T1 (`docs/admin/betrieb.html:130`)

### T3 — Monitoring-Proxy: Audit-Eintrag für POST, PUT und DELETE  [x]
Komponente: server · Dateien: apps/server/app/modules/monitoring_proxy/router.py, apps/server/tests/test_monitoring_proxy_audit.py, docs/features/audit-coverage.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @e06ae0cc 2026-10-22T10:47:44+02:00
Review: approve (.ah-out/review/audit-coverage/T3.verdict.json)
Änderung: `proxy_to_monitoring` (`apps/server/app/modules/monitoring_proxy/router.py:112-163`) bekommt `db: Session = Depends(get_db)` (dieselbe Sitzung wie `get_current_user`; `Session` aus `sqlalchemy.orm` und `get_db` aus `app.core.database` auf Modulebene importieren, die Datei hat `from __future__ import annotations`, `:12`). Nach der Antwort des Monitorings (`:141-150`) und nur, wenn `request.method != "GET"`: `await run_in_threadpool(audit.record, db, f"monitoring.{request.method.lower()}", object_type="monitoring", object_label=forward_path, status="success" if resp.status_code < 400 else "failure", detail=f"status={resp.status_code}", actor=actor_from_request(request))`. `forward_path` ist der weitergeleitete, noch kodierte Pfad ohne Query (`:132-138`). Kein Eintrag, wenn die Allowlist ablehnt (`:124-126`). `_client.request` steht in `try/except httpx.HTTPError`: ein Verbindungsfehler (`httpx.ConnectError`, `ConnectTimeout`, `PoolTimeout`, `UnsupportedProtocol`) heißt, nichts wurde gesendet, also kein Eintrag; jeder andere `HTTPError` (ein Fehler nach dem Senden kann eine schon übernommene Änderung verbergen) schreibt bei Methode ≠ `GET` denselben Eintrag mit `status="error"` und `detail=f"error={type(exc).__name__}"` (nur der Typname, nie `str(exc)`, die Meldung trägt die Ziel-URL), danach `raise`; beide Wege über einen Modul-Helfer `_audit_write`. Das hält, egal ob R-0655 vorher oder nachher landet. Der Inhalt der Anfrage steht nie im Eintrag. Die Antwort an den Browser bleibt gleich; `proxy_agent_report` (`:71-98`) bleibt unverändert. Neue Testdatei `tests/test_monitoring_proxy_audit.py` (SPDX-Header; `_client` ersetzt durch `httpx.AsyncClient(transport=httpx.MockTransport(handler))` wie `tests/test_monitoring_ingest_ratelimit.py:150`): (a) `PUT /api/monitoring/checks/c1?server_id=s1` mit Body `{"smtp_password": "pw-3c9d"}`, Monitoring antwortet 200 → genau eine Zeile `monitoring.put`, Actor `user`/`admin`, `object_type` `monitoring`, `object_label` `checks/c1`, `detail` `status=200`, `status` `success`; `pw-3c9d` und `server_id` in keiner Spalte; (b) `POST /api/monitoring/checks/c1/toggle`, Monitoring 404 → `monitoring.post` mit `status` `failure`, `detail` `status=404`; (c) `DELETE /api/monitoring/templates/tpl-1/assign-tag/web%231%3Fx` → `monitoring.delete` mit `object_label` `templates/tpl-1/assign-tag/web%231%3Fx`; (d) `GET /api/monitoring/status` → keine Zeile; (e) `PUT /api/monitoring/admin/keys` (400 der Allowlist) → keine Zeile, Monitoring nicht aufgerufen; (f) der Client wirft beim `PUT` `httpx.ConnectError`, `ConnectTimeout`, `PoolTimeout` oder `UnsupportedProtocol` → keine Zeile; (g) der Client wirft beim `PUT` `httpx.ReadTimeout`, `ReadError` oder `RemoteProtocolError` → genau eine Zeile `monitoring.put` mit Actor `user`/`admin`, `object_label` `checks/c1`, `status` `error`, `detail` `error=<Typname>`; weder die Fehlermeldung noch die Monitoring-URL in einer Spalte. (f) und (g) über einen `TestClient` mit `raise_server_exceptions=False`, Status der Antwort nur `>= 500`. Zuerst rot: (a)–(c) und (g) auf HEAD.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_monitoring_proxy_audit.py tests/test_monitoring_ingest_ratelimit.py tests/test_monitoring_proxy_lifespan.py tests/test_openapi_snapshot.py
Doku: keine eigene (T8 und T9)
Beweis: Code-Lesung apps/server/app/modules/monitoring_proxy/router.py:112-163 (kein `audit.record`, keine DB-Sitzung im Handler)
Orakel: contract — je weitergeleitetem POST/PUT/DELETE genau eine Audit-Zeile mit Methode, Pfad und Status; GET keine
HEAD: b1432223
Semantik: wie T1 (`docs/admin/betrieb.html:130`)

### T4 — Benutzer ändern: geänderte Felder in `detail` von `user.updated`  [x]
Komponente: server · Dateien: apps/server/app/modules/users/router.py, apps/server/tests/test_users_update_audit.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @8e00c659 2026-10-22T10:56:31+02:00
Review: approve (.ah-out/review/audit-coverage/T4.verdict.json)
Änderung: `update_user` (`apps/server/app/modules/users/router.py:97-152`) merkt vor den Änderungen `is_admin` und die Menge der Server-Ids und gibt dem Eintrag `user.updated` (`:144-151`) `detail` = in fester Reihenfolge, durch `", "` getrennt: `password`, wenn `data.password is not None`; `is_admin=true|false` (neuer Wert), wenn er sich ändert; `server_ids`, wenn sich die Menge ändert; sonst `detail=None`. Sonst bleibt `update_user` gleich (Reihenfolge, Sperre der Herabstufung `:128-137`, Antwort). Neue Testdatei `tests/test_users_update_audit.py` (SPDX-Header): (a) nur Passwort → `detail` `password`, das Passwort steht in keiner Spalte; (b) Hochstufen eines Nicht-Admins → `is_admin=true`; (c) Herabstufen bei zwei Admins → `is_admin=false`; (d) neue Server-Zuordnung → `server_ids`; (e) alles zusammen → `password, is_admin=true, server_ids`; (f) `is_admin` wie gespeichert und dieselbe Server-Menge in anderer Reihenfolge → `detail` `None`; (g) Herabstufen des letzten Admins (400) → kein `user.updated`. Zuerst rot: (a)–(e) auf HEAD.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_users_update_audit.py tests/test_users.py tests/test_users_last_admin.py
Doku: keine eigene (T8 und T9)
Beweis: Code-Lesung apps/server/app/modules/users/router.py:144-151 (`user.updated` ohne `detail`)
Orakel: contract — `detail` nennt genau die geänderten Felder, nie einen Wert außer `is_admin`
HEAD: b1432223
Semantik: wie T1 (`docs/admin/betrieb.html:130`); die CLI trennt den Passwort-Reset schon (`apps/server/app/cli.py:89-96`, `user.password_reset`)

### T5 — Event `user.promoted` bei Hochstufung zum Admin  [x]
Komponente: server · Dateien: apps/server/app/modules/users/router.py, apps/server/app/modules/hooks/schemas.py, apps/web/src/lib/utils/hooks.ts, apps/web/src/lib/i18n/dictionaries.ts, apps/server/tests/test_users_promotion_event.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @39db488f 2026-10-22T11:09:39+02:00
Review: approve (.ah-out/review/audit-coverage/T5.verdict.json)
Änderung: `update_user` feuert nach `db.commit()`/`db.refresh(user)` und vor dem Audit-Eintrag `fire_event("user.promoted", {"id": user.id, "username": user.username})`, genau dann, wenn `is_admin` vorher `false` und jetzt `true` ist (den Vorher-Wert aus T4 nutzen; das Literal steht direkt im Aufruf, `tests/test_event_whitelist.py:20` liest es so). `"user.promoted"` kommt in `VALID_EVENTS` (`apps/server/app/modules/hooks/schemas.py:13-34`, nach `"user.deleted"`) und in `HOOK_EVENTS` (`apps/web/src/lib/utils/hooks.ts:7-28`, nach `'user.deleted'`), Beschriftung `'hook.event.user.promoted'`: DE „Benutzer zum Admin hochgestuft“ (nach `apps/web/src/lib/i18n/dictionaries.ts:150`), EN „User promoted to admin“ (nach `:437`); `tests/test_event_whitelist.py:30-57` bleibt grün. Neue Testdatei `tests/test_users_promotion_event.py` (SPDX-Header; Rekorder für `events._executor`, siehe „Für alle Tasks“): (a) Hochstufen eines Nicht-Admins → genau ein Event `("user.promoted", {"id": <id>, "username": <name>})`; (b) Herabstufen bei zwei Admins, `is_admin=true` für einen Admin, nur Passwort, nur Server-Zuordnung → kein `user.promoted`; (c) Herabstufen des letzten Admins (400) → kein Event; (d) ein Hook mit `event_triggers: ["user.promoted"]` lässt sich über `POST /api/hooks` anlegen (201). Der builder fährt zusätzlich `bash scripts/dev/verify.sh web --strict -- src/lib/i18n/i18n.test.ts` (Summary in den Commit-Body). Zuerst rot: (a) und (d) auf HEAD.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_users_promotion_event.py tests/test_event_whitelist.py tests/test_users.py
Doku: keine eigene (T8 und T9)
Abhängt von: T4
Beweis: Code-Lesung apps/server/app/modules/users/router.py:113-138, :142-151 (Hochstufung ohne `fire_event`); `fire_event("user.created", …)` nur in `create_user` (`:83-85`)
Orakel: contract — genau ein `user.promoted` je Übergang `false → true`, sonst keins
HEAD: b1432223

### T6 — Glocke „Sicherheit“ auch für `user.promoted`  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/event_bridge.py, apps/server/tests/test_notification_bridge.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @af0917d3 2026-10-22T11:20:11+02:00
Review: approve (.ah-out/review/audit-coverage/T6.verdict.json)
Änderung: Neuer Builder `_on_user_promoted(data)` in `apps/server/app/modules/notifications/event_bridge.py` neben `_on_user_created` (`:23-37`): `IncomingEvent(event_type="security.admin.promoted", severity="warning", category="security", title=f"User promoted to admin: {username}", body="An existing user was granted admin rights.", source_type="user", source_id=None)` mit `username = data.get("username", "?")`; Eintrag `"user.promoted": _on_user_promoted` in `_EVENT_BUILDERS` (`:71-75`). Der Modul-Docstring (`:8-12`) nennt die Hochstufung neben dem neuen Admin. Tests in `tests/test_notification_bridge.py`: in `TestBuildEvent` (a) `build_event("user.promoted", {"id": 9, "username": "promo"})` → Kategorie `security`, Schweregrad `warning`, `source_id` `None`, `event_type` `security.admin.promoted`, `promo` im Titel; in `TestBridgeDelivers` (b) wie `test_admin_created_reaches_admins` (`:51-56`): ein Admin mit Abo der Kategorie `security` bekommt genau eine Meldung. `test_unmapped_event_is_ignored` (`:45-47`) bleibt. Zuerst rot: (a), (b) auf HEAD.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_bridge.py
Doku: keine eigene (T8 und T9)
Abhängt von: T5
Beweis: Code-Lesung apps/server/app/modules/notifications/event_bridge.py:71-75 (nur `user.created` führt zu „Sicherheit“)
Orakel: contract — `user.promoted` erreicht dieselben Empfänger wie ein neu angelegter Admin
HEAD: b1432223
Semantik: `docs/admin/monitoring.html:373` — „<strong>Sicherheit</strong>: ein neuer Admin-Benutzer wurde angelegt.“ (EN `:373`); T8 ergänzt die Hochstufung

### T7 — CLI `create-admin` feuert `user.created`  [x]
Komponente: server · Dateien: apps/server/app/cli.py, apps/server/tests/test_cli.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @6130b248 2026-10-22T11:28:49+02:00
Review: approve (.ah-out/review/audit-coverage/T7.verdict.json)
Änderung: `create_admin` (`apps/server/app/cli.py:45-69`) feuert nach `db.commit()` (`:59`) und vor dem Audit-Eintrag (`:60-67`) `fire_event("user.created", {"id": user.id, "username": user.username, "is_admin": True})`, dieselbe Payload wie `POST /api/users` (`apps/server/app/modules/users/router.py:83-85`); Import `from app.core.events import fire_event`. Ein `#`-Kommentar nennt das Warum: der Interpreter joint den Pool von `fire_event` vor dem Ende des Prozesses (Spec, Externe Integrationen), das Event geht also nicht verloren. `reset_admin` und `mint_enroll_token` bleiben. Tests in `tests/test_cli.py` (Rekorder für `events._executor`): (a) erfolgreiches `create_admin` → genau ein Event `("user.created", {"id": <id>, "username": "kevin", "is_admin": True})`; (b) zu kurzes Passwort und vorhandener Name → kein Event (neben (a)). Die bestehenden Audit-Tests (`:165-225`) bleiben. Zuerst rot: (a) auf HEAD.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_cli.py
Doku: keine eigene (T8 und T9)
Beweis: Code-Lesung apps/server/app/cli.py:45-69 (kein `fire_event`)
Orakel: contract — derselbe Event wie der API-Weg
HEAD: b1432223
Semantik: wie T6 (`docs/admin/monitoring.html:373`)

### T8 — Betriebs- und Monitoring-Doku, CHANGELOG  [x]
Komponente: scripts · Dateien: docs/admin/betrieb.html, docs/en/admin/operations.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @00a2c5e5 2026-10-22T12:31:02+02:00
Review: approve (.ah-out/review/audit-coverage/T8.verdict.json)
Änderung: DE und EN, gleiche Stellen; Code-Stellen nach T1–T7 greppen. (1) Audit-Absatz `docs/admin/betrieb.html:130` / `docs/en/admin/operations.html:89` (nach PR #254 `:131` / `:90`): „Erfasst werden u. a. …“ nennt zusätzlich Hooks (Anlegen, Ändern mit den geänderten Feldern, Löschen, Ein- und Ausschalten, Token-Rotation, manueller Lauf mit Erfolg oder Fehlschlag), das Erzeugen von Provisionierungs-Token und Schreibzugriffe über den Monitoring-Proxy (`POST`/`PUT`/`DELETE` mit Pfad und Antwortstatus, bei einem Abbruch nach dem Senden Status `error`, ohne Inhalt); ein Satz: bei einer Benutzer-Änderung nennt `detail` (in der Antwort von `GET /api/audit`) die geänderten Felder — Passwort, Admin-Recht mit neuem Wert, Server-Zuordnung. Der Webhook-Trigger und lesende Zugriffe bleiben ohne Eintrag (ein Halbsatz). (2) `docs/admin/monitoring.html:373` / EN `:373`: „Sicherheit: ein neuer Admin-Benutzer wurde angelegt (auch per `python -m app.cli create-admin`) oder ein Benutzer zum Admin hochgestuft.“ (3) `CHANGELOG.md` unter `## [Unreleased]`, umlautfrei: `### Added` — Event `user.promoted` (`id`, `username`) bei einer Hochstufung zum Admin, abonnierbar fuer Event-Hooks; die Glocke meldet sie unter „Sicherheit“. `### Changed` — das Audit-Log erfasst Hook-Aktionen, das Erzeugen von Provisionierungs-Token und Schreibzugriffe ueber den Monitoring-Proxy; `user.updated` nennt in `detail` die geaenderten Felder; `python -m app.cli create-admin` feuert `user.created` wie die API. Der builder fährt zusätzlich `python3 scripts/dev/doc-smoke.py --paths --env --strict` (Exit 0, Ergebnis in den Commit-Body).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Task ist die Doku samt CHANGELOG
Abhängt von: T1, T2, T3, T4, T5, T6, T7
Semantik: Soll ist der Code nach T1–T7; zu ergänzen sind `docs/admin/betrieb.html:130` (Aufzählung „Erfasst werden u.&nbsp;a. …“) und `docs/admin/monitoring.html:373` („ein neuer Admin-Benutzer wurde angelegt“), EN `operations.html:89`, `monitoring.html:373`

### T9 — Entwickler-Doku: Event-Katalog, Event-Bus, API-Referenz  [x]
Komponente: server · Dateien: docs/developer/hooks.html, docs/en/developer/hooks.html, docs/developer/server.html, docs/en/developer/server.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @4c40a17d 2026-10-22T13:06:56+02:00
Review: approve (.ah-out/review/audit-coverage/T9.verdict.json)
Änderung: DE und EN, gleiche Stellen. (1) Event-Katalog `docs/developer/hooks.html:54` / EN `:54`: neue Zeile `user.promoted` — `id`, `username`; feuert, wenn `PUT /api/users/{id}` einem Benutzer das Admin-Recht gibt; bei `user.created` der Zusatz, dass auch `python -m app.cli create-admin` es feuert. (2) `docs/developer/server.html:167` / EN `:167`: `user.promoted` in der Liste der Event-Typen; `:187` / EN `:187`: die Brücke spiegelt `user.created`/`user.promoted`/`server.deleted`/`frp.tunnel.created`. (3) `docs/developer/api-reference.html` / EN, gleiche Zeilen: `PUT /api/users/{id}` (`:83`) — Audit `user.updated` mit den geänderten Feldern in `detail`, feuert `user.promoted` beim Wechsel von `is_admin` auf `true`; Abschnitt Hooks (`:113-122`) ein Satz zu den Audit-Aktionen `hook.created`, `hook.updated`, `hook.deleted`, `hook.token_rotated`, `hook.run`; `POST …/provision/token` (`:154`) — Audit `provision.token.minted`; Proxy (`:173-175`) — `POST`/`PUT`/`DELETE` schreiben `monitoring.post|put|delete` mit Pfad und Antwortstatus (bei einem Abbruch nach dem Senden `status` `error`, `detail` `error=<Typ>`); im Hinweis `:179` entfällt `audit` aus dem Titel und der Satz „Audit-Trails laufen via Hook-Events … existiert (Stand v0.23.2) nicht“ (EN „Audit trails run via hook events … as of v0.23.2“), denn `:110-111` beschreibt `GET /api/audit`. Die Aufzählung der Pfad-Prefixe (`:172`) bleibt wörtlich (gepinnt von `apps/server/tests/test_monitoring_proxy_allowlist.py:46-51`). Der builder fährt zusätzlich `bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test` (Summary in den Commit-Body).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_monitoring_proxy_allowlist.py
Doku: die Task ist die Doku; CHANGELOG trägt T8
Abhängt von: T1, T2, T3, T4, T5, T6, T7
Semantik: Soll ist der Code nach T1–T7; falsch nach T5–T7 sind `docs/developer/hooks.html:54` („<code>user.created</code> / <code>deleted</code>“ ohne `user.promoted`), `docs/developer/server.html:167`, `:187`, `docs/developer/api-reference.html:83` („User &auml;ndern (admin).“); schon heute falsch `:179` („ein dedizierter <code>/api/audit</code>-Endpoint existiert (Stand v0.23.2) nicht“)
