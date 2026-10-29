<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Audit-Abdeckung und Admin-Meldungen: Hooks, Provisionierungs-Token, Monitoring-Proxy, Hochstufung

Stand des Codes: `origin/main@b1432223`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/audit-coverage.md`. Härtung, Kevin 2026-10-22. PR #254 (hooks-followups) wird vor dem Bau gemergt; er ändert
keine der Code-Dateien dieses Plans, verschiebt aber die Audit-Absätze der Betriebsdoku um eine Zeile
(`docs/admin/betrieb.html:130` → `:131`, `docs/en/admin/operations.html:89` → `:90`).

## Problem / Motivation

Die Betriebsdoku beschreibt den Audit-Trail so: `docs/admin/betrieb.html:130` — „Sicherheits- und
änderungsrelevante Aktionen werden in einem <strong>append-only Audit-Trail</strong> protokolliert — mit Actor …,
Quell-IP und Zeitstempel. Erfasst werden u.&nbsp;a. das Anlegen/Ändern/Löschen <strong>und die Nutzung</strong> von
Verbindungen, Änderungen an Servern/Benutzern/API-Keys/FRP/Ansible sowie Logins …“ (EN
`docs/en/admin/operations.html:89`). Der Code schreibt die Einträge über `audit.record`
(`apps/server/app/modules/audit/service.py:25-56`) mit dem Actor aus `actor_from_request`
(`apps/server/app/core/request_context.py:41-43`), den `get_current_user` bindet (`apps/server/app/core/auth.py:230`).
Folgende Admin-Aktionen schreiben heute keinen Eintrag:

1. **Hooks.** `apps/server/app/modules/hooks/router.py` importiert `audit` nicht (`:10-35`). Ohne Eintrag bleiben
   `create_hook` (`:142-175`), `update_hook` (`:256-288`, auch das Script), `delete_hook` (`:291-299`), `toggle_hook`
   (`:302-316`), `rotate_hook_token` (`:319-333`) und `run_hook_manually` (`:336-363`).
2. **Provisionierungs-Token.** `create_provision_token` (`apps/server/app/modules/provisioning/router.py:58-88`)
   schreibt keinen Eintrag; das Einlösen (`:108-207`) schreibt schon `apikey.deleted` und `enrollment.token.minted`
   (`:190-207`).
3. **Schreibzugriffe über den Monitoring-Proxy.** `proxy_to_monitoring`
   (`apps/server/app/modules/monitoring_proxy/router.py:112-163`) leitet `POST`, `PUT` und `DELETE` an den
   Monitoring-Dienst weiter (Checks, Alarmregeln, Templates, Wartungsfenster), ohne Eintrag.
4. **Benutzer ändern.** `update_user` (`apps/server/app/modules/users/router.py:97-152`) schreibt `user.updated`
   ohne `detail` (`:144-151`). Ob das Passwort, das Admin-Recht oder die Server-Zuordnung geändert wurde, steht nicht
   im Eintrag; die CLI unterscheidet den Passwort-Reset schon als `user.password_reset` (`apps/server/app/cli.py:89-96`).
5. **Glocke „Sicherheit“.** Die Admin-Doku verspricht `docs/admin/monitoring.html:373` — „<strong>Sicherheit</strong>:
   ein neuer Admin-Benutzer wurde angelegt.“ (EN `:373`). Die Meldung entsteht aus dem Event `user.created` mit
   `is_admin` (`apps/server/app/modules/notifications/event_bridge.py:23-37`, `:71-75`), das nur `POST /api/users`
   feuert (`users/router.py:83-85`). Eine Hochstufung über `PUT /api/users/{id}` (`:113-138`) und
   `python -m app.cli create-admin` (`cli.py:45-69`) feuern kein Event; dort bleibt die Glocke still.

## Ziel & Nicht-Ziele

Ziel:
- Jede schreibende Hook-Route der Admins schreibt nach dem Commit genau einen Eintrag mit dem angemeldeten Admin als
  Actor und dem Hook als Objekt: `hook.created` (`detail` `type=<hook_type>`), `hook.updated` (`detail` die geänderten
  Felder, Spec Trade-off 2), `hook.deleted`, `hook.updated` für `/toggle` (`detail` `enabled=true|false`),
  `hook.token_rotated`, `hook.run` (`status` `success` oder `failure` nach dem Ergebnis des Laufs). Kein Token, kein
  Script-Inhalt und kein Fehlertext eines Laufs im Eintrag.
- `POST /api/servers/{id}/provision/token` schreibt `provision.token.minted` mit dem Server als Objekt und
  `detail` `ttl=24h`; weder das Token noch sein Hash stehen im Eintrag.
- Jedes `POST`, `PUT` und `DELETE` über `/api/monitoring/{path}`, auf das der Monitoring-Dienst antwortet, schreibt
  `monitoring.post`, `monitoring.put` oder `monitoring.delete` mit `object_type` `monitoring`, dem weitergeleiteten
  Pfad (kodiert, ohne Query) als `object_label`, `detail` `status=<HTTP-Status>` und `status` `success` (< 400) oder
  `failure`. Bricht die Weiterleitung nach dem Senden ab (etwa ein Lese-Timeout), entsteht derselbe Eintrag mit
  `status` `error` und `detail` `error=<Typname des Fehlers>`; ein Verbindungsfehler (nichts gesendet) schreibt
  nichts (Trade-off 4). `GET` schreibt nichts; der Inhalt der Anfrage steht nie im Eintrag.
- `user.updated` nennt in `detail` die geänderten Felder, feste Reihenfolge, durch `, ` getrennt: `password` (wenn
  gesendet), `is_admin=true|false` (wenn sich der Wert ändert), `server_ids` (wenn sich die Menge ändert); ändert
  sich nichts, bleibt `detail` leer.
- Neues Event `user.promoted` (`{id, username}`), wenn `PUT /api/users/{id}` `is_admin` von `false` auf `true` setzt;
  Event-Hooks können es abonnieren (Web-Auswahl mit Beschriftung DE+EN). Die Glocke meldet es unter „Sicherheit“ wie
  einen neu angelegten Admin.
- `python -m app.cli create-admin` feuert `user.created` mit `is_admin: true` wie `POST /api/users`; damit meldet
  die Glocke auch diesen Weg.

Nicht-Ziele (YAGNI):
- Kein Eintrag für den Webhook-Trigger (`/api/hooks/trigger`, `/trigger/{token}`, `hooks/router.py:185-245`) und den
  Agent-Report (`monitoring_proxy/router.py:71-98`): Eingänge von Maschinen mit eigenem Token, bis zu 20 bzw. 120
  Aufrufe je IP und Minute (`hooks/router.py:47-48`, `monitoring_proxy/router.py:31-32`); offene Frage 1.
- Keine Einträge für lesende Routen (wie überall im Server; von den Lesezugriffen erfasst er nur die Nutzung einer
  Verbindung).
- Keine Umbenennung: `UserUpdate` kennt keinen Benutzernamen (`apps/server/app/modules/users/schemas.py:67-70`).
- Kein Event bei einer Herabstufung.
- Kein Event für den Bootstrap des ersten Admins (`users/auth_router.py`) und `_ensure_admin` (`app/main.py`): dort
  gibt es keinen anderen Admin, den die Glocke erreichen könnte; die Wege zum Admin führt R-0690 zusammen.
- Kein Umbau des Musters Commit → `fire_event` → `audit.record` (R-0689); dieser Plan folgt dem bestehenden Muster.
- Keine Anzeige von `detail` in der Web-Auditansicht (offene Frage 2).
- Keine Migration, kein neues Feld, keine Route.

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | server | `apps/server/app/modules/hooks/router.py`, `apps/server/tests/test_hooks_audit.py` (neu) |
| T2 | server | `apps/server/app/modules/provisioning/router.py`, `apps/server/tests/test_provision_token_audit.py` (neu) |
| T3 | server | `apps/server/app/modules/monitoring_proxy/router.py`, `apps/server/tests/test_monitoring_proxy_audit.py` (neu) |
| T4 | server | `apps/server/app/modules/users/router.py`, `apps/server/tests/test_users_update_audit.py` (neu) |
| T5 | server | `apps/server/app/modules/users/router.py`, `apps/server/app/modules/hooks/schemas.py`, `apps/web/src/lib/utils/hooks.ts`, `apps/web/src/lib/i18n/dictionaries.ts`, `apps/server/tests/test_users_promotion_event.py` (neu) |
| T6 | server | `apps/server/app/modules/notifications/event_bridge.py`, `apps/server/tests/test_notification_bridge.py` |
| T7 | server | `apps/server/app/cli.py`, `apps/server/tests/test_cli.py` |
| T8 | scripts | `docs/admin/betrieb.html`, `docs/en/admin/operations.html`, `docs/admin/monitoring.html`, `docs/en/admin/monitoring.html`, `CHANGELOG.md` |
| T9 | server | `docs/developer/hooks.html`, `docs/en/developer/hooks.html`, `docs/developer/server.html`, `docs/en/developer/server.html`, `docs/developer/api-reference.html`, `docs/en/developer/api-reference.html` |

Auf `scripts/dev/review-risk.txt` stehen `apps/server/app/modules/monitoring_proxy/*` (T3),
`apps/server/app/modules/users/*` (T4, T5), `apps/server/app/modules/*/schemas.py` (T5) und
`apps/server/app/modules/notifications/*` (T6): diese Tasks bekommen zusätzlich `security`.

T5 ändert zwei Web-Dateien in einer Server-Task: `apps/server/tests/test_event_whitelist.py:30-57` verlangt, dass
jedes Literal in `fire_event("…")` in `VALID_EVENTS` steht und `VALID_EVENTS` gleich `HOOK_EVENTS` im Web ist, mit
einer Beschriftung DE+EN; die drei Stellen gehen deshalb in einem Commit.

## Datenmodell / API / Migrationen

- Keine Migration: `audit_log.action` ist `String`, `detail` ist `Text` (`apps/server/app/modules/audit/models.py:31`,
  `:37`).
- OpenAPI bleibt unverändert: `request: Request` (T1, T2) und `db: Session = Depends(get_db)` (T3) erscheinen nicht
  im Schema, keine Route bekommt einen Docstring (der Docstring ist die `description`); T1–T3 fahren
  `tests/test_openapi_snapshot.py` im `Verify:`.
- Neue Audit-Aktionen: `hook.created`, `hook.updated`, `hook.deleted`, `hook.token_rotated`, `hook.run`,
  `provision.token.minted`, `monitoring.post`, `monitoring.put`, `monitoring.delete`. Kein Client führt Aktionen als
  Vertrag: die Web-Ansicht filtert mit freiem Text und zeigt `action` als Text
  (`apps/web/src/pages/Audit.svelte:23`, `:91`, `:133`), die Betriebsdoku nennt Bereiche, keine Namen.
- Neues Event `user.promoted` (Payload `{id, username}`): `VALID_EVENTS` (`apps/server/app/modules/hooks/schemas.py:13-34`),
  `HOOK_EVENTS` (`apps/web/src/lib/utils/hooks.ts:7-28`), Beschriftungen `hook.event.user.promoted`
  (`apps/web/src/lib/i18n/dictionaries.ts:149-150`, `:436-437`), Event-Katalog `docs/developer/hooks.html:54` (EN
  `:54`). Event-Namen stehen nicht im OpenAPI-Schema (`event_triggers` ist `list[str]`, `hooks/schemas.py:44`, `:53`).
- Neuer Hub-`event_type` `security.admin.promoted` (Kategorie `security`, Schweregrad `warning`). Abos filtern nach
  Schweregrad und Kategorie, nicht nach `event_type` (`apps/server/app/modules/notifications/service.py:163`, `:165`):
  wer heute „Neuer Admin-Benutzer“ bekommt, bekommt auch diese Meldung.
- Kein Vertrags-Drift: der Desktop ruft den Provisionierungs-Token und den Monitoring-Proxy
  (`apps/desktop/ui/src/lib/api/provisioning.ts:26`, `apps/desktop/ui/src/lib/api/monitoring.ts`), deren Antworten
  bleiben gleich; `/api/hooks`, `/api/audit` und `PUT /api/users/{id}` ruft nur das Web, der Agent keine dieser
  Routen.

## Externe Integrationen

Keine. Ein Detail der Standardbibliothek trägt T7: `python -m app.cli` endet mit `raise SystemExit(main())`
(`cli.py:187-188`), `fire_event` gibt die Arbeit an einen `ThreadPoolExecutor` (`apps/server/app/core/events.py:19`,
`:65-67`). `concurrent.futures.thread` registriert `_python_exit` per `threading._register_atexit`, das beim Ende des
Interpreters die Worker-Threads joint (CPython seit 3.9, bpo-39812). Probe 2026-10-22 (Python 3.13.5, dreimal): ein
Skript, das eine Aufgabe mit 0,5&nbsp;s Laufzeit einreicht und sofort `SystemExit(0)` wirft, schreibt ihre Datei
jedes Mal. Für Python 3.12 im Container nicht geprobt; der Mechanismus ist derselbe.

## Trade-offs & Alternativen

1. **Proxy: Aktion je Methode (T3).** (a) `monitoring.post|put|delete` mit dem Pfad als `object_label` —
   **Empfehlung**: die Web-Ansicht zeigt `action` und `objectType: objectLabel`, aber kein `detail`
   (`Audit.svelte:66-71`, `:114-140`), so bleibt Methode und Ziel sichtbar. (b) Eine Aktion `monitoring.write` mit
   Methode im `detail` — die Methode wäre in der Web-Ansicht unsichtbar. (c) Fachliche Namen je Monitoring-Route —
   eine zweite Routentabelle im Server, die mit dem Monitoring auseinanderläuft.
2. **`hook.updated`: geänderte statt gesendete Felder (T1).** Vorher-Nachher-Vergleich der Spalten `name`,
   `description`, `script`, `event_triggers`, `schedule_interval`, `enabled`. Hält auch, wenn sich die Lesart von
   `None` in `update_hook` ändert (R-0651 plant `model_fields_set` für `description`). Nur Feldnamen, bei `enabled`
   der neue Wert; kein Script-Inhalt, kein Hash (YAGNI).
3. **Wann `hook.run` schreibt (T1).** Nach dem Lauf, mit `status` aus `result["success"]` — wie `audit.record` es
   verlangt („Call it AFTER the audited operation“, `audit/service.py:9-10`). Ein Eintrag vorher bräuchte einen
   zweiten für das Ergebnis.
4. **Proxy-Eintrag bei einem Fehler des Clients (T3).** Ein Verbindungsfehler (`ConnectError`, `ConnectTimeout`,
   `PoolTimeout`, `UnsupportedProtocol`) heißt, nichts wurde gesendet: kein Eintrag. Ein Fehler nach dem Senden
   (Lese-Timeout, Lese- oder Protokollfehler) kann eine schon übernommene Änderung verbergen: ein Eintrag mit
   `status` `error` und nur dem Typnamen des Fehlers in `detail` (die Meldung trägt die Ziel-URL); danach wirft der
   Handler weiter, die Antwort an den Browser bleibt gleich. Das hält, egal ob R-0655 (Fehlerbehandlung des Proxys)
   vorher oder nachher landet.
5. **Event `user.promoted` statt `user.updated` (T5).** (a) Eigenes Event nur für die Hochstufung —
   **Empfehlung**, ein Event je sicherheitsrelevantem Übergang, Payload wie `user.deleted`. (b) Allgemeines
   `user.updated` mit geänderten Feldern — mehr Vertrag (Feldliste), die Brücke müsste filtern. (c) Die Brücke ohne
   Bus direkt aus `update_user` aufrufen — Event-Hooks sähen die Hochstufung nicht, und der Weg wiche vom Bus ab.
6. **CLI feuert `user.created` (T7)** statt eines eigenen Events: derselbe Vorgang wie `POST /api/users`, gleiche
   Payload, bestehender Vertrag. Auf einer frischen Installation bekommt der erste Admin damit eine Glocken-Meldung
   über sich selbst (`scripts/install.sh` legt ihn per CLI an); hingenommen.
7. **Text der neuen Glocken-Meldung (T6)** englisch („User promoted to admin: <name>“): neue Code-Strings sind
   englisch; der deutsche Alt-Text von `_on_user_created` bleibt.

## Risiken & Rollback

- T3 schreibt pro Schreibzugriff über den Proxy eine Zeile; Admin-Aktionen im Web, kein Maschinenverkehr (der
  Agent-Report hat seine eigene Route). Die Aufbewahrung begrenzt `AUDIT_RETENTION_DAYS` (Default 365).
- T3 schreibt synchron in die DB aus einem `async`-Handler: über `run_in_threadpool`, wie der Rate-Limit-Zähler
  daneben (`monitoring_proxy/router.py:81`). `from __future__ import annotations` (`:12`): `Session` muss auf
  Modulebene importiert sein, damit FastAPI die Annotation auflöst.
- `audit.record` bleibt best effort (`audit/service.py:7-9`): ein Fehler beim Schreiben bricht die Aktion nicht ab.
- T5 und T7 lösen Event-Hooks aus (`user.promoted`, `user.created` aus der CLI); in der CLI joint der Interpreter den
  Pool vor dem Ende, ein Hook mit 30&nbsp;s Timeout verlängert den CLI-Aufruf entsprechend.
- Rollback: jede Task ist ein eigener Commit ohne Datenänderung; Revert genügt.

## Doku-Impact

T8: Betriebsdoku (DE+EN) nennt die neuen Bereiche des Audit-Trails und `detail` bei Benutzer-Änderungen;
Monitoring-Doku (DE+EN) nennt Hochstufung und CLI bei der Glocke „Sicherheit“; CHANGELOG (Added: Event
`user.promoted`; Changed: Audit-Abdeckung, `detail`, CLI-Event). T9: Entwickler-Doku (DE+EN) — Event-Katalog,
Event-Liste und Brücke in `server.html`, API-Referenz (Benutzer, Hooks, Provisionierung, Proxy) und die veraltete
Aussage zum Audit im Hinweis der API-Referenz (`docs/developer/api-reference.html:179`, EN `:179`: „Audit-Trails
laufen via Hook-Events über das Logging-System; ein dedizierter /api/audit-Endpoint existiert (Stand v0.23.2)
nicht“, obwohl `:110-111` `GET /api/audit` beschreibt). T1–T7: keine eigene Doku-Zeile.

## Offene Fragen

1. **Webhook-Trigger auditieren?** Empfehlung: nein — Eingang einer Maschine mit Token, bis 20 Aufrufe je IP und
   Minute, das Ergebnis geht an den Aufrufer; die Nutzung eines Hooks durch einen Admin (`/run`) ist erfasst. Bei
   „ja“ eine eigene Task an `hooks/router.py:185-225` mit Actor `anonymous` und dem Hook als Objekt. Hält keine Task.
2. **`detail` in der Web-Auditansicht?** `Audit.svelte:114-140` zeigt `detail` nicht, obwohl `AuditEntry` es trägt
   (`apps/web/src/lib/api/types.ts:205`); die Unterscheidung in `user.updated` (T4) sieht man also nur über
   `GET /api/audit`. Empfehlung: eigene Roadmap-Zeile (web), nicht in diesem Paket. Hält keine Task.
