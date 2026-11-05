<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-notify-incidents — Task-Ledger
Status: bereit · Branch: feature/arch-notify-incidents · Review: pro Task
Spec: docs/features/arch-notify-incidents.md (Roadmap R-1079)
Heavy: linux-full — Server-API, Hub-Ingress vom Monitoring und die Desktop-Journey notification-push; der Sammellauf fährt Stack und GUI-E2E
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Vorlage `AdminCave/DesignSystem@244e890` (`ui_kits/adminhelper/notifications.jsx`). Stand `origin/main@a3645c00`. Die
Server-Tasks T1–T4 liegen auf Risikopfaden (`notifications/*`, `schemas.py`, `alembic/versions/*`, `frp/*`,
`enrollment/*`): `security` je Task. T5 (`alerter.py`) und T6 (`types.ts`) ebenso.

### T1 — Server: Kategorien nach Mockup und Datenmigration (R-1079)  [x]
Komponente: server · Dateien: apps/server/app/main.py, apps/server/app/modules/frp/supervisor_watch.py, apps/server/app/modules/enrollment/expiry.py, apps/server/app/modules/notifications/event_bridge.py, apps/server/app/modules/notifications/models.py, apps/server/alembic/versions/c1a7e3f5b9d2_notification_categories.py, apps/server/tests/test_notification_category_migration.py, apps/server/tests/test_frp_supervisor_watch.py, apps/server/tests/test_notification_bridge.py, apps/server/tests/test_certificate_expiry_watch.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @0205d37e 2026-11-05T09:09:01+01:00
Review: approve (.ah-out/review/arch-notify-incidents/T1.verdict.json)
Änderung: Die Erzeuger schreiben die Mockup-Kategorien statt `lifecycle`: frp_config (`main._tell_admins`), frps (`supervisor_watch`) und `lifecycle.frp.tunnel.created` → `tunnel`, Zertifikatsablauf → `security`, `lifecycle.server.deleted` → `agent`; der Spalten-Kommentar in `models.py` nennt das Vokabular. Neue Alembic-Revision (Kopf `b4d6f8a0c2e1`) bildet Altzeilen nach `event_type`-Präfix und Abos (`categories` mit `lifecycle` → tunnel, security, agent) ab, Downgrade zurück (für Abos verlustbehaftet, im Kopf dokumentiert). Neuer Migrationstest nach dem Muster von `test_outbox_expiry_migration.py` (SPDX). Zehn Dateien: ein Umbenennen über vier Erzeuger mit ihren drei Tests, gemeinsam mit der Migration, damit nie gemischte Kategorien stehen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_category_migration.py tests/test_frp_supervisor_watch.py tests/test_notification_bridge.py tests/test_certificate_expiry_watch.py tests/test_migrations_smoke.py
Doku: → T9

### T2 — Server: Vorfall-Tabellen und Migration (R-1079)  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/models.py, apps/server/alembic/versions/d3b5f7a9c1e4_notification_incidents.py, apps/server/tests/test_notification_incident_migration.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @f5eea904 2026-11-05T09:14:48+01:00
Review: approve (.ah-out/review/arch-notify-incidents/T2.verdict.json)
Änderung: Modelle `NotificationIncident`, `NotificationIncidentMember`, `NotificationIncidentEvent`, `NotificationServerMute`; an `Notification` die Spalten `incident_id` (FK CASCADE), `notified_at`, `muted_until`, `hidden_at` und die Eindeutigkeit je (user, incident). Migration mit Backfill `notified_at = created_at`, danach NOT NULL; Downgrade entfernt alles. Migrationstest (SPDX): Altzeilen behalten Inhalt und bekommen `notified_at`, Downgrade/Upgrade wiederholbar.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_incident_migration.py tests/test_migrations_smoke.py tests/test_alembic_builtin.py
Doku: → T9
Abhängt von: T1

### T3 — Server: Falten im Hub (R-1079)  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/incidents.py, apps/server/app/modules/notifications/service.py, apps/server/app/modules/notifications/schemas.py, apps/server/app/modules/notifications/router.py, apps/server/tests/test_notification_incidents.py, apps/server/tests/test_notifications.py, apps/server/tests/openapi.snapshot.json, apps/server/app/modules/notifications/models.py, apps/server/app/modules/notifications/outbox.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @7b5a4260 2026-11-05T10:15:12+01:00
Review: approve (.ah-out/review/arch-notify-incidents/T3.verdict.json)
Änderung: Neues Modul `incidents.py` (SPDX) mit dem Falten aus der Spec (aktiver Vorfall → falten, behobener in `REOPEN_WINDOW` → still wieder öffnen, sonst neu; Ping-Regel wie `hub_decision`; Erholung behebt automatisch; Bündel mit Mitgliedern; schlüssellose warning/critical-Ereignisse je ein Vorfall, nur mit Empfänger:in). `ingest_event` und `notify_users` schreiben darüber eine Zeile je (Person, Vorfall), Pings setzen `notified_at`, ungelesen und Outbox, stumme Zeilen nicht; Verlauf mit Deckel 200. `IncomingEvent` bekommt `incident_key`, `incident_keys`, `rules` mit Validierung. `alert.triggered` feuert nur bei critical-Pings. Retention nach `notified_at` und für behobene Vorfälle. Die Ping-Fälle von `test_alerter_hub.py` (Cooldown, Eskalation, Erholung nur nach gezeigtem Problem, nichts nachholen) als Hub-Tests; Least-Privilege der Bündel-Texte.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_incidents.py tests/test_notifications.py tests/test_notification_bridge.py tests/test_openapi_snapshot.py
Doku: → T9
Abhängt von: T2

### T4 — Server: Feed-Felder und Vorfall-Aktionen (R-1079)  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/router.py, apps/server/app/modules/notifications/schemas.py, apps/server/app/modules/notifications/incidents.py, apps/server/app/modules/notifications/models.py, apps/server/tests/test_notification_incident_api.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @0f68ca09 2026-11-05T11:00:54+01:00
Review: approve (.ah-out/review/arch-notify-incidents/T4.verdict.json)
Änderung: Feed-Zeilen mit `incidentId`, `state`, `count`, `ackedBy`, `resolvedBy`, `notifiedAt`, `muted`, `mutedUntil`, `muteSource`; Sortierung nach `notified_at`, ausgeblendete fehlen, `unread-count` ohne stumme und ausgeblendete. Routen aus der Spec: Detail (Verlauf und Mitglieder nach Server-Sichtbarkeit gefiltert, `canAct`), `ack` (Sammel), `resolve`, `reopen`, `notes`, `mute`, `server-mutes`, `hide`, `unread`; 404 ohne eigene Zeile, 403/`skipped` ohne Sicht auf jeden Server, 409 bei ungültigem Übergang; SSE-Anstoß an die Mitempfänger:innen. Neue Testdatei (SPDX) mit Least-Privilege je Route.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_incident_api.py tests/test_notification_incidents.py tests/test_notifications.py tests/test_response_shapes.py tests/test_openapi_snapshot.py
Doku: → T9
Abhängt von: T3

### T5 — Monitoring: Glocke ohne eigenen Cooldown, Schlüssel und Regel-Ergebnisse (R-1079)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/alerter.py, apps/monitoring/app/alert_bundle.py, apps/monitoring/tests/test_alerter_hub.py, apps/monitoring/tests/test_alert_bundle.py, apps/monitoring/tests/test_alerter_dispatch.py, apps/monitoring/app/models.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @a5ccb7c3 2026-11-05T11:21:29+01:00
Review: approve (.ah-out/review/arch-notify-incidents/T5.verdict.json)
Änderung: `hub_decision` ohne Cooldown-Zweig (jede Problem-Transition ≥ warning geht an den Hub, Erholung wie heute nur nach gezeigtem Problem; `hub_status`/`hub_sent_at` weiter geschrieben, `HUB_COOLDOWN` entfällt). `send_to_rule` gibt `(name, channel, ok)` zurück, `process_alert` gibt die Ergebnisse und `incident_key = check:<id>` an `emit_to_hub`; `alert_bundle` setzt `incident_keys` parallel zu `source_ids` und die Regeln des Bündel-Versands. Die Cooldown-Tests in `test_alerter_hub.py` werden zu „geht an den Hub“ (der Cooldown ist in T3 als Hub-Test gesichert).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alerter_hub.py tests/test_alert_bundle.py tests/test_alerter_dispatch.py tests/test_alerter.py tests/test_alerter_sent_state.py
Doku: → T9
Abhängt von: T3

### T6 — Desktop: Vertrag, Modell und Store (R-1079)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/api/notifications.ts, apps/desktop/ui/src/lib/api/notifications.test.ts, apps/desktop/ui/src/lib/models/notifications.ts, apps/desktop/ui/src/lib/models/notifications.test.ts, apps/desktop/ui/src/lib/stores/notifications.ts, apps/desktop/ui/src/lib/stores/notifications.test.ts, apps/desktop/ui/src/lib/api/types.contract.test.ts, apps/desktop/ui/src/pages/Notifications.test.ts, apps/desktop/ui/src/components/NotificationBell.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @708bbcc3 2026-11-05T11:55:01+01:00
Review: approve (.ah-out/review/arch-notify-incidents/T6.verdict.json)
Änderung: `NotificationItem` mit den Feed-Feldern aus T4, Typen für Detail und Verlauf; API-Aufrufe für Detail und alle Aktionen. Modell: echtes `isOpen` (warning/critical, `open`, nicht stumm), Postfächer inbox/open/acked/resolved/muted/all, Kategorien-Vokabular. Store: Toast-Erkennung über vorgerücktes `notifiedAt` (ungelesen, nicht stumm) statt `lastSeenId`; Aktionen aktualisieren die Zeilen und laden nach.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/api/notifications.test.ts src/lib/models/notifications.test.ts src/lib/stores/notifications.test.ts src/lib/api/types.contract.test.ts src/pages/Notifications.test.ts src/components/NotificationBell.test.ts
Doku: → T9
Abhängt von: T4

### T7 — Desktop: Detail, Postfächer und Aktionen nach Mockup (R-1079)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/pages/Notifications.svelte, apps/desktop/ui/src/pages/Notifications.test.ts, apps/desktop/ui/src/components/NotificationDetail.svelte, apps/desktop/ui/src/components/NotificationDetail.test.ts, apps/desktop/ui/src/components/NotificationBell.svelte, apps/desktop/ui/src/components/NotificationBell.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/i18n/i18n.test.ts, apps/desktop/ui/src/lib/models/notifications.ts, apps/desktop/ui/src/lib/models/notifications.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @437f6947 2026-11-05T12:17:44+01:00
Review: approve (.ah-out/review/arch-notify-incidents/T7.verdict.json)
Änderung: Neue Komponente `NotificationDetail.svelte` (SPDX): Zustand, ×n, Aktionen (Bestätigen, Als behoben markieren, Wieder öffnen), Stumm-Menü (1 Stunde, bis morgen 07:00 Ortszeit, Server für 24 h, Regel bearbeiten → Monitoring-Alerts; Stumm aufheben), Meta (Zeitpunkt, Regel, Kanäle/„nur Glocke“, ID), Verlauf und Notiz-Eingabe. Center mit den sechs Postfächern und Sammelaktionen Gelesen/Bestätigen/Ausblenden, „Als ungelesen markieren“; Glocken-Panel mit Schnell-„Bestätigen“. Texte DE+EN.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/pages/Notifications.test.ts src/components/NotificationDetail.test.ts src/components/NotificationBell.test.ts src/lib/i18n/i18n.test.ts src/lib/models/notifications.test.ts
Doku: → T9
Abhängt von: T6

### T8 — Desktop-E2E: Vorfall-Journey (R-1079)  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/notification-push.live.js, apps/desktop/e2e/test/lib/live.js
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped @fb9c69ae 2026-11-05T12:24:41+01:00
Review: approve (.ah-out/review/arch-notify-incidents/T8.verdict.json)
Änderung: Die Live-Spec bekommt eine zweite Journey: ein Ereignis mit `incident_key` einspeisen, Vorfall im Center öffnen, bestätigen, eine Wiederholung zählt ×2 ohne neuen Toast, die Erholung behebt ihn. `live.js` lernt das Einspeisen mit Schlüssel. Der echte Lauf gehört zum Sammellauf (`Heavy: linux-full`); hier Lint und Syntax.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: → T9
Abhängt von: T7

### T9 — Doku DE+EN und Changelog (R-1079)  [x]
Komponente: server · Dateien: docs/developer/server.html, docs/en/developer/server.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/hooks.html, docs/en/developer/hooks.html, docs/developer/desktop.html, docs/en/developer/desktop.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/arch-notify-incidents.md, docs/admin/index.html, docs/en/admin/index.html, README.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @14ad9215 2026-11-05T12:41:25+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Notification-Hub mit Vorfällen, Falten und Tabellen; neue Routen, Feld- und Ingress-Felder; Glocke ohne eigenen Monitoring-Cooldown, Schlüssel und Regel-Ergebnisse; `alert.triggered` nur beim critical-Ping; Benachrichtigungs-Center (Postfächer, Detail, Stummschalten, Kategorien); Changelog-Eintrag. Sechzehn Dateien: sieben Seiten je DE+EN, README und der Changelog.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_openapi_snapshot.py
Doku: diese Task
Task-Review: am Ende
Abhängt von: T8

## Entscheidungen
- 2026-11-05 (Session, Gate): Der Glocken-Cooldown wandert vom Monitoring in den Hub, mit derselben Ping-Regel (`REOPEN_WINDOW` = 30 min = `HUB_COOLDOWN`). Grund: mit Vorfällen lässt der Monitoring-Cooldown den Zustand lügen (critical → ok → critical binnen 30 min bliebe „behoben“), und ×n kann nicht zählen, was nie ankommt. Kevins Regel von 2026-10-19 bleibt wörtlich, das Monitoring braucht keine Migration.
- 2026-11-05 (Session, Gate): Eine Feed-Zeile je (Person, Vorfall); ein Ping setzt sie wieder auf ungelesen und rückt `notified_at` vor, der Desktop erkennt Toasts daran. Altzeilen bleiben ohne Vorfall.
- 2026-11-05 (Session, Gate): Zusammengeführt wird die Sicht, nicht die Engine: das Monitoring meldet die gefeuerten Regeln mit Ergebnis, der Vorfall zeigt Regel und Kanäle. Regel-Engine und `MonitorAlertLog` bleiben im Monitoring (R-1080 baut die Kanäle).
- 2026-11-05 (Session, Gate): Stummschalten (Vorfall bis, Server bis) gilt je Person, höchstens 7 Tage; „bis morgen 07:00“ rechnet der Desktop in Ortszeit.
- 2026-11-05 (Session, Gate): Team-Aktionen (bestätigen, beheben, wieder öffnen, Notiz) nur mit Sicht auf jeden Server des Vorfalls; Admins immer.
- 2026-11-05 (Session, Gate): Eine Eskalation warning → critical pingt und setzt einen bestätigten Vorfall zurück auf offen.
- 2026-11-05 (Session, Gate): Kategorien: frp_config, frps, `lifecycle.frp.*` → tunnel; Zertifikatsablauf → security; `lifecycle.server.deleted` → agent. Datenmigration für Zeilen und Abos, Downgrade für Abos verlustbehaftet.
- 2026-11-05 (Session, T3): Ein Ereignis ohne Schlüssel bei warning/critical ist ein eigener Vorfall, und nur, wenn es jemand bekommt; info und Erholungen ohne Schlüssel bleiben Zeilen ohne Vorfall wie bisher. Ein Problem mit Schlüssel auf gedeckelter Stufe info tut nichts (wie `hub_decision`).
- 2026-11-05 (Session, T3): Ein Outbox-Eintrag trägt den Text seines Pings: die Glockenzeile rückt mit dem nächsten Ping weiter, die Mail des ersten Pings bleibt dessen Text (`test_notifications.py`: Test umbenannt, Erwartung jetzt Titel des Pings statt NULL).
- 2026-11-05 (Session, T3): Eine stumme Zeile (Vorfall bis, Server bis) übernimmt den Inhalt eines Pings, bleibt gelesen, rückt `notified_at` nicht vor und schickt nichts; das Stummschalten eines Servers greift nur, wenn der Ping genau einen Server nennt.
- 2026-11-05 (Session, T3): Ein Einzel-Ereignis, das in ein Bündel faltet, überschreibt dessen Teamtext nicht; schließt es das Bündel ab, lautet die Entwarnung „Resolved: <Bündeltitel>“ nur mit den Serverzeilen des Lesers.
- 2026-11-05 (Session, T3): Aufbewahrung: Vorfälle ohne Schlüssel (kein Bündel) fallen wie zuvor ihre Zeilen nach `retention_days`, weil nichts sie behebt; offene Prüf-Vorfälle und Bündel bleiben. Eine Erholung ohne aktiven Vorfall setzt `recovered_at` des Mitglieds und schreibt einen stillen Verlaufseintrag.
- 2026-11-05 (Session, T3): Eine Eskalation ist ein eigener Verlaufseintrag `escalated` neben `triggered`; der SSE-Anstoß behält `maxId`, der Desktop wechselt in T6/T7 auf `notified_at`.
- 2026-11-05 (Session, T3): T3 trägt neun Dateien: die Kommentare in `models.py` und `outbox.py` folgen der neuen Outbox-Semantik.
- 2026-11-05 (Session, T3, security): Ein Schlüssel gehört zu seinem Server: ein Ereignis faltet, öffnet wieder oder erholt nur einen Vorfall (oder ein Bündel-Mitglied) desselben Servers. Ein Check, der auf einen anderen Server umzieht, öffnet dort einen neuen Vorfall; der alte bleibt offen, bis ihn jemand behebt (das Monitoring setzt den Zustand beim Umzug nicht zurück). Ein Bündel ohne Schlüssel (Sender vor R-1079) bleibt Zeilen ohne Vorfall wie bisher: kein Mitglied hielte seine Server, und Team-Aktionen prüfen genau diese. Weicht von Spec „Ältere Sender: schlüssellos“ für Bündel ab; T9 zieht die Doku nach.
- 2026-11-05 (Session, T4): Detail und die Aktionen an einem Vorfall verlangen die eigene Zeile und jetzt die Sicht auf mindestens einen seiner Server; fehlt eins, antwortet die Route 404, gleich wie ohne Zeile (verrät nicht, ob es den Vorfall gibt). Ein Vorfall ohne Server (`source_type` nicht `server` oder ohne `source_id`, kein Bündel) gehört den Admins, wie `service._user_can_see`.
- 2026-11-05 (Session, T4): Feed-Zeilen, deren Vorfall die Person nicht mehr sieht, tragen alle Vorfall-Felder als `null`, `incidentId` eingeschlossen; Zeilen- und Stumm-Felder bleiben (die Zeile gehört weiter ihr).
- 2026-11-05 (Session, T4): Zustand, Schwere und Zähler eines Bündels sind die des Teams; Titel, Text, Server und Verlauf im Detail zählen nur die sichtbaren Server (Verlaufseinträge mit `server_id` anderer Server fehlen).
- 2026-11-05 (Session, T4): `skipped` von `ack` ist eine Liste von IDs ohne Grund (keine Zeile, keine volle Sicht, nicht offen): ein Grund verriete fremde Vorfälle. `hide`, `unread` und `ack` nehmen 1–500 IDs (`IdsRequest`); der Desktop schickt in Teilen.
- 2026-11-05 (Session, T4): Beheben behält `acked_*`; wieder öffnen löscht `acked_*` und `resolved_*`; Beheben von Hand lässt die Bündel-Mitglieder, wie sie sind. Eine Notiz verlangt Text (leer oder nur Leerzeichen: 422), in jedem Zustand. 409 nur bei `resolve` auf behoben und `reopen` auf nicht behoben.
- 2026-11-05 (Session, T4): Stumm zeigt der Feed nur an Zeilen mit Vorfall; „Server stumm“ nur an Zeilen mit `source_type` `server` und `source_id`. Der Ping schreibt den einen Server eines Bündels mit nur einem Server (`_single_server`, etwa drei Checks auf einem Host) als `source_id` in die Zeile: Feed und `unread-count` lesen den Server-Mute aus der Zeile und folgen so dem Ping, der ihn angewandt hat (Prüferfund T4). Eine Bündel-Zeile mehrerer Server bleibt ohne `source_id` und ohne Server-Mute. `unread-count` zählt dieselben Regeln.
- 2026-11-05 (Session, T4, security): Ein Einzel-Ereignis eines Mitglieds, das in ein Bündel faltet, schreibt `escalated` und `notified` ohne `server_id`; wer nur einen Teil des Bündels sieht, erfährt so den Zeitpunkt (ohne Server und Anzahl). Bleibt: Zähler und Schwere sind nach Entscheidung die des Teams und ändern sich ohnehin sichtbar; T9 nennt es in der Doku.
- 2026-11-05 (Session, T4, security): Notizen schreibt nur, wer jeden Server des Vorfalls sieht, lesen kann sie jede Inhaberin einer Zeile; Freitext kann fremde Server nennen. T9 dokumentiert das, T7/T8 zeigen es als Hinweis am Notizfeld.
- 2026-11-05 (Session, T4): `PUT /server-mutes/{server_id}` ist ein Upsert, 404 für einen Server, den die Person nicht sieht (Admin: der nicht existiert); `DELETE` antwortet 204 und ist idempotent. Stummschalten ändert den Lesezustand nicht.
- 2026-11-05 (Session, T4): SSE: Team-Aktionen stoßen alle Inhaber:innen einer Zeile des Vorfalls an, persönliche (`mute`, `server-mutes`, `hide`, `unread`) nur die Person selbst; `read` bleibt wie bisher ohne Anstoß.
- 2026-11-05 (Session, T5): Das Monitoring hat keinen Glocken-Cooldown mehr: jedes Problem mit gekappter Stufe warning oder critical geht an den Hub, auch eine Besserung critical→warning (Schwere wie bisher die schlimmere beider Zustände, `hub_status` danach warning); die Entwarnung des Hubs pingt mit `notified_severity` des Vorfalls, die Stufe der Erholung im Ereignis ändert daran nichts.
- 2026-11-05 (Session, T5): `send_to_rule` liefert `RuleResult(name, channel, ok, server_id)`; `server_id` ist `match_server_id`. Ein Bündel nennt eine an einen Server gebundene Regel nie, auch wenn alle Mitglieder des Teilstücks auf diesem Server liegen: alle Lesenden des Vorfalls sehen die Regeln, nicht jede sieht jeden Server, und der Hub faltet ein Bündel eines Servers in einen offenen Bündel-Vorfall über mehrere und übernimmt dessen Regeln (der Hub kennt die Bindung nicht, darum filtert das Monitoring). Preis: auch ein Bündel-Vorfall eines Servers zeigt seine gebundenen Regeln nicht. Einzel-Ereignisse nennen ihre Regeln immer. Abweichung von der Spec (`(name, channel, ok)`): das vierte Feld bleibt im Monitoring.
- 2026-11-05 (Session, T5): Regeln je Ereignis: eine Zeile je (Name, Kanal), `ok` nur wenn jeder Versand dazu rausging; leerer Name wird `(unnamed)`, über 200 Zeichen auf 199 plus `…` gekürzt, höchstens 50 Zeilen (Grenzen von `IncomingEvent.rules`/`IncidentRule.name`, ein Test vergleicht sie mit dem Server-Schema). `rules: []` heißt „keine Regel hat gesendet“, ohne Feld (alter Absender) zeigt der Hub keine Regeln.
- 2026-11-05 (Session, T5): Bündel teilen nach Mitgliedern (`HUB_MAX_IDS` je Ereignis), ein Eintrag je Mitglied in `source_ids` und `incident_keys`; zwei Checks eines Servers nennen ihn zweimal, der Server entdoppelt. Faltet ein Bündel-Ereignis in einen Einzel-Vorfall, zeigt der die zusammengeführten Regeln des Teilstücks.
- 2026-11-05 (Session, T5): `incident_key` ist `check:<id>` ohne Kürzung: Check-IDs sind immer uuid4 (`routers/checks.py`, `template_sync.py`), 42 Zeichen bei 200 erlaubten.
- 2026-11-05 (Session, T6): Die Vorfall-Felder an `NotificationItem` sind optional: ein Server vor R-1079 schickt keine, der Vertragstest erlaubt die breitere Seite; dazu sechs Mappings (Detail, Verlauf, Server, Regel, Ack, Server-Mute).
- 2026-11-05 (Session, T6): Neu ist ein Eintrag, dessen `notifiedAt` nach dem spätesten bisher gesehenen liegt (`Date.parse`, die Länge der Mikrosekunden schwankt), ungelesen und nicht stumm; eine Zeile ohne `notifiedAt` (alter Server) fällt auf `id > lastSeenId` zurück, ebenso jede Zeile, solange noch keine Ping-Zeit gesehen wurde (Server-Update während einer laufenden Session: die Migration füllt `notifiedAt` für den ganzen Rückstand, der darf nicht als neu melden; Reviewer-Fund T6). So meldet ein erneuter Ping einer bekannten Zeile neu, eine ins 50er-Fenster gerutschte oder als ungelesen markierte nicht, und eigene Team-Aktionen pingen nicht. Dass WebKitGTK sechs Nachkommastellen parst, ist nicht verifiziert; `createdAt` hängt schon heute daran.
- 2026-11-05 (Session, T6): `isOpen` und die Postfächer nach Mockup: offen = warning/critical, `state` open, nicht stumm, gelesen oder nicht; Posteingang = nicht stumm und (ungelesen oder offen). Kategorien-Vokabular wie das des Servers (`backup`, `session` im Singular); `categoriesOf` sortiert danach, Unbekanntes hinten nach Name. Die Postfach-Leiste der Seite bleibt bis T7 bei drei Einträgen.
- 2026-11-05 (Session, T6): Store-Aktionen wie im Monitoring-Store: Fehler über `reportError`, Antwort `null`/`false`; nach Erfolg wird die geänderte Zeile lokal ersetzt und `loadFeed` abgewartet. `hide`, `unread`, `ack` schicken je Aufruf höchstens 500 eindeutige IDs (T4); jeder angenommene Teil gilt, auch wenn ein späterer scheitert. Ein Server-Mute lädt die Center-Liste neu, nur der Server kennt die betroffenen Zeilen.
- 2026-11-05 (Session, T6): Die Fixtures in `Notifications.test.ts` und `NotificationBell.test.ts` (T7-Dateien) zieht T6 nach: das neue `isOpen` braucht `state: 'open'`, sonst ginge T6 rot in den Commit.
- 2026-11-05 (Session, T7): Die Aktionen im Detail folgen den Übergängen des Servers ohne Schwere-Filter: offen zeigt Bestätigen und Beheben, bestätigt zeigt Beheben, behoben zeigt Wieder öffnen; nur mit `canAct`. Bestätigen geht auch an einer stummen offenen Zeile (Bestätigen gilt fürs Team, Stumm nur für die Person).
- 2026-11-05 (Session, T7): Das Detail lädt über `notificationsApi.fetchIncident` direkt (der Store hat keinen Wrapper); ein Zähler verwirft späte Antworten, ein Versionsschlüssel aus den Vorfall-Feldern der Zeile lädt bei jeder Änderung neu. Scheitert ein Nachladen, bleibt das alte Detail stehen, mit Hinweis. `{#key selected.id}` auf der Seite leert die Notiz beim Zeilenwechsel.
- 2026-11-05 (Session, T7): Sammel-Bestätigen zählt Vorfälle, nicht Zeilen; die Zahl der übersprungenen steht als Statushinweis bis zur nächsten Auswahl. Ausblenden nimmt alle ausgewählten Zeilen, die der Filter zeigt. Kein Label „N ausgewählt“: die Knöpfe tragen die Zahlen.
- 2026-11-05 (Session, T7): Die Leiste zeigt alle sechs Postfächer, der schmale Umschalter nur Posteingang, Offen, Alle. Das Schnell-Bestätigen der Glocke ist ein Textknopf nur an offenen Zeilen mit Vorfall.
- 2026-11-05 (Session, T7): Kanäle im Detail: die Kanäle des Hubs ohne Glocke und die der Regeln, ein gescheiterter markiert, entdoppelt; „nur Glocke“, wenn sonst nichts rausging. Server stumm gilt 24 h; „Regel bearbeiten“ öffnet den Alerts-Tab des Monitorings und steht nur an Kategorie monitoring.
- 2026-11-05 (Session, T7): T7 trägt zehn Dateien statt acht: die Anzeige-Helfer (Kategorie, Kanal, Zeit, Zustand) liegen testbar in `models/notifications.ts`, und `i18n.test.ts` braucht die dynamischen Präfixe; `Verify:` nimmt `models/notifications.test.ts` dazu.
- 2026-11-05 (Session, T8): Die Vorfall-Journey ist ein zweites `it` in `notification-push.live.js` (derselbe Runner `desktop_e2e_sse_push.sh`, dieselbe App-Sitzung); nach einem roten ersten hält `bail` die Spec an, einzeln gefahren (mocha grep) meldet sie sich selbst an. Zustände prüft sie an den Knöpfen des Details (sprachunabhängig), den Schlüssel macht ein Zeitstempel je Lauf eindeutig.
- 2026-11-05 (Session, T8): Eine stille Wiederholung stößt kein SSE an; das ×2 bringt der 30-s-Poll, darum warten die Schritte bis 45 s. „Kein Toast“ gilt, sobald ×2 sichtbar ist: `loadFeed` meldet neue Einträge vor dem Aktualisieren der Zeilen. Der echte Lauf gehört zum Sammellauf; hier Lint (eslint mit Gegenprobe) und `node --check`, live nicht verifiziert.
- 2026-11-05 (Session, T9): `docs/admin/index.html` (DE+EN) und `README.md` kamen dazu: beide beschrieben die Glocke noch ohne Vorfälle (Postfach Offen = ungelesen, Kategorie lifecycle). Neuer Abschnitt `#vorfaelle`/`#incidents` in der Admin-Doku Monitoring; Hooks-, Index- und Monitoring-Text verweisen darauf.
- 2026-11-05 (Session, T9): T9 bleibt reine Doku. Der Kommentar über `REOPEN_WINDOW` in `incidents.py` nennt `HUB_COOLDOWN` als Herkunft der 30 min (Warum, nicht veraltet); die Test-ID `alarm-after-cooldown` in `apps/monitoring/tests/test_check_engine_concurrency.py` (fremde Datei) nennt den entfallenen Glocken-Cooldown: Roadmap R-1146; `docs/features/monitoring-alert-quality.md` ist eine historische Spec und bleibt unverändert.
