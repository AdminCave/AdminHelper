<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-notify-incidents — Task-Ledger
Status: aktiv · Branch: feature/arch-notify-incidents · Review: pro Task
Spec: docs/features/arch-notify-incidents.md (Roadmap R-1079)
Heavy: linux-full — Server-API, Hub-Ingress vom Monitoring und die Desktop-Journey notification-push; der Sammellauf fährt Stack und GUI-E2E
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Vorlage `AdminCave/DesignSystem@244e890` (`ui_kits/adminhelper/notifications.jsx`). Stand `origin/main@a3645c00`. Die
Server-Tasks T1–T4 liegen auf Risikopfaden (`notifications/*`, `schemas.py`, `alembic/versions/*`, `frp/*`,
`enrollment/*`): `security` je Task. T5 (`alerter.py`) und T6 (`types.ts`) ebenso.

### T1 — Server: Kategorien nach Mockup und Datenmigration (R-1079)  [ ]
Komponente: server · Dateien: apps/server/app/main.py, apps/server/app/modules/frp/supervisor_watch.py, apps/server/app/modules/enrollment/expiry.py, apps/server/app/modules/notifications/event_bridge.py, apps/server/app/modules/notifications/models.py, apps/server/alembic/versions/c1a7e3f5b9d2_notification_categories.py, apps/server/tests/test_notification_category_migration.py, apps/server/tests/test_frp_supervisor_watch.py, apps/server/tests/test_notification_bridge.py, apps/server/tests/test_certificate_expiry_watch.py
Änderung: Die Erzeuger schreiben die Mockup-Kategorien statt `lifecycle`: frp_config (`main._tell_admins`), frps (`supervisor_watch`) und `lifecycle.frp.tunnel.created` → `tunnel`, Zertifikatsablauf → `security`, `lifecycle.server.deleted` → `agent`; der Spalten-Kommentar in `models.py` nennt das Vokabular. Neue Alembic-Revision (Kopf `b4d6f8a0c2e1`) bildet Altzeilen nach `event_type`-Präfix und Abos (`categories` mit `lifecycle` → tunnel, security, agent) ab, Downgrade zurück (für Abos verlustbehaftet, im Kopf dokumentiert). Neuer Migrationstest nach dem Muster von `test_outbox_expiry_migration.py` (SPDX). Zehn Dateien: ein Umbenennen über vier Erzeuger mit ihren drei Tests, gemeinsam mit der Migration, damit nie gemischte Kategorien stehen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_category_migration.py tests/test_frp_supervisor_watch.py tests/test_notification_bridge.py tests/test_certificate_expiry_watch.py tests/test_migrations_smoke.py
Doku: → T9

### T2 — Server: Vorfall-Tabellen und Migration (R-1079)  [ ]
Komponente: server · Dateien: apps/server/app/modules/notifications/models.py, apps/server/alembic/versions/d3b5f7a9c1e4_notification_incidents.py, apps/server/tests/test_notification_incident_migration.py
Änderung: Modelle `NotificationIncident`, `NotificationIncidentMember`, `NotificationIncidentEvent`, `NotificationServerMute`; an `Notification` die Spalten `incident_id` (FK CASCADE), `notified_at`, `muted_until`, `hidden_at` und die Eindeutigkeit je (user, incident). Migration mit Backfill `notified_at = created_at`, danach NOT NULL; Downgrade entfernt alles. Migrationstest (SPDX): Altzeilen behalten Inhalt und bekommen `notified_at`, Downgrade/Upgrade wiederholbar.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_incident_migration.py tests/test_migrations_smoke.py
Doku: → T9
Abhängt von: T1

### T3 — Server: Falten im Hub (R-1079)  [ ]
Komponente: server · Dateien: apps/server/app/modules/notifications/incidents.py, apps/server/app/modules/notifications/service.py, apps/server/app/modules/notifications/schemas.py, apps/server/app/modules/notifications/router.py, apps/server/tests/test_notification_incidents.py, apps/server/tests/test_notifications.py, apps/server/tests/openapi.snapshot.json
Änderung: Neues Modul `incidents.py` (SPDX) mit dem Falten aus der Spec (aktiver Vorfall → falten, behobener in `REOPEN_WINDOW` → still wieder öffnen, sonst neu; Ping-Regel wie `hub_decision`; Erholung behebt automatisch; Bündel mit Mitgliedern; schlüssellose warning/critical-Ereignisse je ein Vorfall, nur mit Empfänger:in). `ingest_event` und `notify_users` schreiben darüber eine Zeile je (Person, Vorfall), Pings setzen `notified_at`, ungelesen und Outbox, stumme Zeilen nicht; Verlauf mit Deckel 200. `IncomingEvent` bekommt `incident_key`, `incident_keys`, `rules` mit Validierung. `alert.triggered` feuert nur bei critical-Pings. Retention nach `notified_at` und für behobene Vorfälle. Die Ping-Fälle von `test_alerter_hub.py` (Cooldown, Eskalation, Erholung nur nach gezeigtem Problem, nichts nachholen) als Hub-Tests; Least-Privilege der Bündel-Texte.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_incidents.py tests/test_notifications.py tests/test_notification_bridge.py tests/test_openapi_snapshot.py
Doku: → T9
Abhängt von: T2

### T4 — Server: Feed-Felder und Vorfall-Aktionen (R-1079)  [ ]
Komponente: server · Dateien: apps/server/app/modules/notifications/router.py, apps/server/app/modules/notifications/schemas.py, apps/server/app/modules/notifications/incidents.py, apps/server/app/modules/notifications/models.py, apps/server/tests/test_notification_incident_api.py, apps/server/tests/test_response_shapes.py, apps/server/tests/openapi.snapshot.json
Änderung: Feed-Zeilen mit `incidentId`, `state`, `count`, `ackedBy`, `resolvedBy`, `notifiedAt`, `muted`, `mutedUntil`, `muteSource`; Sortierung nach `notified_at`, ausgeblendete fehlen, `unread-count` ohne stumme und ausgeblendete. Routen aus der Spec: Detail (Verlauf und Mitglieder nach Server-Sichtbarkeit gefiltert, `canAct`), `ack` (Sammel), `resolve`, `reopen`, `notes`, `mute`, `server-mutes`, `hide`, `unread`; 404 ohne eigene Zeile, 403/`skipped` ohne Sicht auf jeden Server, 409 bei ungültigem Übergang; SSE-Anstoß an die Mitempfänger:innen. Neue Testdatei (SPDX) mit Least-Privilege je Route.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_incident_api.py tests/test_notification_incidents.py tests/test_notifications.py tests/test_response_shapes.py tests/test_openapi_snapshot.py
Doku: → T9
Abhängt von: T3

### T5 — Monitoring: Glocke ohne eigenen Cooldown, Schlüssel und Regel-Ergebnisse (R-1079)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/alerter.py, apps/monitoring/app/alert_bundle.py, apps/monitoring/tests/test_alerter_hub.py, apps/monitoring/tests/test_alert_bundle.py, apps/monitoring/tests/test_alerter_dispatch.py
Änderung: `hub_decision` ohne Cooldown-Zweig (jede Problem-Transition ≥ warning geht an den Hub, Erholung wie heute nur nach gezeigtem Problem; `hub_status`/`hub_sent_at` weiter geschrieben, `HUB_COOLDOWN` entfällt). `send_to_rule` gibt `(name, channel, ok)` zurück, `process_alert` gibt die Ergebnisse und `incident_key = check:<id>` an `emit_to_hub`; `alert_bundle` setzt `incident_keys` parallel zu `source_ids` und die Regeln des Bündel-Versands. Die Cooldown-Tests in `test_alerter_hub.py` werden zu „geht an den Hub“ (der Cooldown ist in T3 als Hub-Test gesichert).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alerter_hub.py tests/test_alert_bundle.py tests/test_alerter_dispatch.py tests/test_alerter.py tests/test_alerter_sent_state.py
Doku: → T9
Abhängt von: T3

### T6 — Desktop: Vertrag, Modell und Store (R-1079)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/api/notifications.ts, apps/desktop/ui/src/lib/api/notifications.test.ts, apps/desktop/ui/src/lib/models/notifications.ts, apps/desktop/ui/src/lib/models/notifications.test.ts, apps/desktop/ui/src/lib/stores/notifications.ts, apps/desktop/ui/src/lib/stores/notifications.test.ts
Änderung: `NotificationItem` mit den Feed-Feldern aus T4, Typen für Detail und Verlauf; API-Aufrufe für Detail und alle Aktionen. Modell: echtes `isOpen` (warning/critical, `open`, nicht stumm), Postfächer inbox/open/acked/resolved/muted/all, Kategorien-Vokabular. Store: Toast-Erkennung über vorgerücktes `notifiedAt` (ungelesen, nicht stumm) statt `lastSeenId`; Aktionen aktualisieren die Zeilen und laden nach.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/api/notifications.test.ts src/lib/models/notifications.test.ts src/lib/stores/notifications.test.ts
Doku: → T9
Abhängt von: T4

### T7 — Desktop: Detail, Postfächer und Aktionen nach Mockup (R-1079)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/pages/Notifications.svelte, apps/desktop/ui/src/pages/Notifications.test.ts, apps/desktop/ui/src/components/NotificationDetail.svelte, apps/desktop/ui/src/components/NotificationDetail.test.ts, apps/desktop/ui/src/components/NotificationBell.svelte, apps/desktop/ui/src/components/NotificationBell.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Neue Komponente `NotificationDetail.svelte` (SPDX): Zustand, ×n, Aktionen (Bestätigen, Als behoben markieren, Wieder öffnen), Stumm-Menü (1 Stunde, bis morgen 07:00 Ortszeit, Server für 24 h, Regel bearbeiten → Monitoring-Alerts; Stumm aufheben), Meta (Zeitpunkt, Regel, Kanäle/„nur Glocke“, ID), Verlauf und Notiz-Eingabe. Center mit den sechs Postfächern und Sammelaktionen Gelesen/Bestätigen/Ausblenden, „Als ungelesen markieren“; Glocken-Panel mit Schnell-„Bestätigen“. Texte DE+EN.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/pages/Notifications.test.ts src/components/NotificationDetail.test.ts src/components/NotificationBell.test.ts src/lib/i18n/i18n.test.ts
Doku: → T9
Abhängt von: T6

### T8 — Desktop-E2E: Vorfall-Journey (R-1079)  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/notification-push.live.js, apps/desktop/e2e/test/lib/live.js
Änderung: Die Live-Spec bekommt eine zweite Journey: ein Ereignis mit `incident_key` einspeisen, Vorfall im Center öffnen, bestätigen, eine Wiederholung zählt ×2 ohne neuen Toast, die Erholung behebt ihn. `live.js` lernt das Einspeisen mit Schlüssel. Der echte Lauf gehört zum Sammellauf (`Heavy: linux-full`); hier Lint und Syntax.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: → T9
Abhängt von: T7

### T9 — Doku DE+EN und Changelog (R-1079)  [ ]
Komponente: server · Dateien: docs/developer/server.html, docs/en/developer/server.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/hooks.html, docs/en/developer/hooks.html, docs/developer/desktop.html, docs/en/developer/desktop.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/arch-notify-incidents.md
Änderung: Notification-Hub mit Vorfällen, Falten und Tabellen; neue Routen, Feld- und Ingress-Felder; Glocke ohne eigenen Monitoring-Cooldown, Schlüssel und Regel-Ergebnisse; `alert.triggered` nur beim critical-Ping; Benachrichtigungs-Center (Postfächer, Detail, Stummschalten, Kategorien); Changelog-Eintrag. Dreizehn Dateien: sechs Seiten je DE+EN und der Changelog.
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
