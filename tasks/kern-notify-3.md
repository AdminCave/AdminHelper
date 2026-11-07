# Ruhezeiten · Eskalation · Zusammenfassung per E-Mail · Ton bei Kritisch — Task-Ledger
Status: geplant · Branch: feature/kern-notify-3 · Review: pro Task
Spec: docs/features/kern-notify-3.md (Roadmap R-1081)
Heavy: linux-full — Server-API und Alembic-Migration (notification-prefs), zwei neue Scheduler-Jobs, Desktop-Journey der Benachrichtigungen; geht in den Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Server: Spalten, Migration, Prefs-API und Zeitrechnung je Zone (R-1081)  [ ]
Komponente: server · Dateien: apps/server/app/modules/notifications/models.py, apps/server/alembic/versions/a4b6c8d0e2f4_notification_quiet_escalation_digest.py, apps/server/app/modules/notifications/schemas.py, apps/server/app/modules/notifications/router.py, apps/server/app/modules/notifications/quiet.py, apps/server/tests/test_notification_quiet.py, apps/server/tests/test_notification_settings.py, apps/server/tests/openapi.snapshot.json
Änderung: Die Spalten der Spec an `NotificationSettings`, `Notification.escalated_at` und `NotificationIncident.critical_since`, die Migration mit `server_default` auf den Standardwerten; der Downgrade setzt `digest`-Einträge auf `pending`. Die Prefs-API GET/PUT bekommt die neuen Felder additiv (fehlendes Feld behält seinen Wert); geprüft werden `HH:MM`, `minutes` ∈ {5,10,30}, der Kanal und die IANA-Zone (422). `quiet.py` (SPDX) rechnet `in_quiet`, `quiet_end` und `next_digest_at` in der Zone der Person, Standard UTC. Vorher prüfen, ob das Server-Image `tzdata` hat (`/usr/share/zoneinfo` im Image oder das Python-Paket), sonst `tzdata` in die Abhängigkeiten und `THIRD_PARTY_LICENSES.md`, per `set-files`. Tests: Prefs-Rundlauf und 422-Fälle; Zeitrechnung über Mitternacht, an beiden DST-Umstellungstagen in `Europe/Berlin`, in UTC und in einer Zone ohne DST; Migration hoch und runter. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_quiet.py tests/test_notification_settings.py tests/test_notification_prefs_test.py tests/test_openapi_snapshot.py tests/test_response_shapes.py tests/test_alembic_builtin.py
Doku: → T5

### T2 — Server: Ruhezeit hält Nicht-Kritisches zurück, Zusammenfassung sammelt E-Mails (R-1081)  [ ]
Komponente: server · Dateien: apps/server/app/modules/notifications/incidents.py, apps/server/app/modules/notifications/digest.py, apps/server/app/modules/notifications/outbox.py, apps/server/app/modules/hooks/scheduler.py, apps/server/app/scheduler_main.py, apps/server/tests/test_notification_digest.py, apps/server/tests/test_notifications.py, apps/server/tests/test_outbox.py
Änderung: `_queue` setzt in der Ruhezeit der Person für Info, Warnung und `ok` `next_attempt_at` = Ende der Ruhezeit (Kritisch nur ohne Durchlass). Bei eingeschalteter Zusammenfassung bekommen E-Mail-Einträge für Info, Warnung und `ok` Status `digest`. `digest.py` (SPDX) `send_digests(db, now)` schickt je fälliger Person (`next_digest_at`, `digest_last_at`) eine Mail mit allen `digest`-Einträgen, setzt sie auf `sent` und `digest_last_at`. Ist die Zusammenfassung aus, gehen wartende `digest`-Einträge beim nächsten Lauf als Zusammenfassung raus; ohne Einträge geht keine Mail. Der Systemjob läuft alle fünf Minuten neben `schedule_outbox_drain`. Tests: zurückgehalten und zur Endzeit zugestellt (Drain mit `now` danach), Kritisch mit und ohne Durchlass, `digest` liegt im Drain, Versand um 08:00 täglich und am Montag, keine Mail ohne Einträge, kein Doppelversand im selben Fenster. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_digest.py tests/test_notifications.py tests/test_outbox.py tests/test_notification_incidents.py tests/test_notification_channels.py
Doku: → T5
Abhängt von: T1

### T3 — Server: Eskalation unbestätigter kritischer Vorfälle an den Kanal der Person (R-1081)  [ ]
Komponente: server · Dateien: apps/server/app/modules/notifications/incidents.py, apps/server/app/modules/notifications/escalation.py, apps/server/app/modules/hooks/scheduler.py, apps/server/app/scheduler_main.py, apps/server/tests/test_notification_escalation.py, apps/server/tests/test_notification_incidents.py
Änderung: `critical_since` wird beim ersten kritischen Ping eines Vorfalls gesetzt und geleert, wenn er behoben wird. Beim Wiederöffnen leert `act` außerdem `escalated_at` der Zeilen. `escalation.py` (SPDX) `escalate_due(db, now)`: für offene Vorfälle mit `critical_since` ≤ `now − Frist der Person` und einer Zeile ohne `escalated_at`, die nicht stumm ist, und mit Eskalation an, Kanal an und Ziel vorhanden, ein Outbox-Eintrag auf dem gewählten Kanal mit Schweregrad `critical` und dem Text „Unbestätigt seit N Min.: <Titel>“ (Ruhezeit wie Kritisch). `escalated_at` wird mit `escalated_at IS NULL` im UPDATE gesetzt, der Eintrag `escalated` mit dem Kanal kommt in die Zeitleiste, die SSE-Benachrichtigung wie bei `finish_actions`. Der Systemjob läuft jede Minute. Tests: Eskalation nach Frist, nicht vor der Frist, nicht nach Bestätigen oder Beheben, einmal je Person, wieder nach Wiederöffnen, stumm, Kanal ohne Ziel oder ausgeschaltet, Matrix ohne den Kanal eskaliert trotzdem, Abfragezahl begrenzt. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_escalation.py tests/test_notification_incidents.py tests/test_notification_incident_api.py
Doku: → T5
Abhängt von: T1

### T4 — Desktop-UI: Abschnitt Ruhe, Eskalation & Zusammenfassung, Ruhezeit und Durchlass im Desktop, Ton bei Kritisch (R-1081)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/components/NotificationPrefs.svelte, apps/desktop/ui/src/components/NotificationPrefs.test.ts, apps/desktop/ui/src/lib/stores/notifyPrefs.ts, apps/desktop/ui/src/lib/stores/notifyPrefs.test.ts, apps/desktop/ui/src/lib/stores/dnd.ts, apps/desktop/ui/src/lib/stores/dnd.test.ts, apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/components/AppShell.notifications.test.ts, apps/desktop/ui/src/lib/osNotify.ts, apps/desktop/ui/src/lib/sound.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Typen der neuen Prefs-Felder. Neuer Abschnitt in `NotificationPrefs.svelte` nach dem Mockup: Ruhezeiten (zwei Zeitfelder und Schalter), „Kritisches trotzdem durchlassen“, Eskalation (5/10/30 Min., Kanal; Kanäle ohne Ziel oder ausgeschaltet deaktiviert, Hinweis), Zusammenfassung (Aus/Täglich/Wöchentlich), Ton bei Kritisch. Beim Speichern geht die Zone aus `Intl` mit. `notifyPrefs` rechnet `inQuiet(now)` in der gespeicherten Zone. `allows` in `dnd.ts` lässt Kritisches nur mit Durchlass durch und schweigt in der Ruhezeit. `AppShell` spielt bei einem gezeigten kritischen Toast den Ton aus `sound.ts` (SPDX, WebAudio, ohne `AudioContext` still), wenn er an ist; OS-Meldungen folgen derselben Prüfung. i18n DE/EN. Tests: Abschnitt lädt und speichert die Felder samt Zone, Ruhezeit über Mitternacht, Durchlass für DND und Ruhezeit, Ton nur bei Kritisch und nur außerhalb der Ruhe. Mehr als acht Dateien, weil Store, Shell und Formular die Prüfung gemeinsam tragen.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T5
Abhängt von: T1

### T5 — Doku DE+EN und CHANGELOG (R-1081)  [ ]
Komponente: docs · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/server.html, docs/en/developer/server.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-notify-3.md
Änderung: Unterabschnitt Ruhezeiten, Eskalation, Zusammenfassung und Ton unter „Kanäle und Matrix“ (DE `#kanaele`, EN `#channels`), dazu Outbox-Status `digest`, zwei Systemjobs, `critical_since`/`escalated_at` in der Server-Doku, die neuen Prefs-Felder in der API-Referenz und ein CHANGELOG-Fragment (umlautfrei).
Verify: bash scripts/dev/verify.sh docs --strict
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/server.html, docs/en/developer/server.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-notify-3.md
Task-Review: am Ende
Abhängt von: T2, T3, T4

## Entscheidungen
