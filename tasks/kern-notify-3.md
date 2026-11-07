# Ruhezeiten · Eskalation · Zusammenfassung per E-Mail · Ton bei Kritisch — Task-Ledger
Status: erledigt · Branch: feature/kern-notify-3 · Review: pro Task
Spec: docs/features/kern-notify-3.md (Roadmap R-1081)
Heavy: linux-full — Server-API und Alembic-Migration (notification-prefs), zwei neue Scheduler-Jobs, Desktop-Journey der Benachrichtigungen; geht in den Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Server: Spalten, Migration, Prefs-API und Zeitrechnung je Zone (R-1081)  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/models.py, apps/server/alembic/versions/a4b6c8d0e2f4_notification_quiet_escalation_digest.py, apps/server/app/modules/notifications/schemas.py, apps/server/app/modules/notifications/router.py, apps/server/app/modules/notifications/quiet.py, apps/server/tests/test_notification_quiet.py, apps/server/tests/test_notification_settings.py, apps/server/tests/openapi.snapshot.json, apps/server/tests/test_response_shapes.py, apps/server/requirements.in, apps/server/requirements.txt, THIRD_PARTY_LICENSES.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @29f6999f7 2026-11-07T11:44:22+01:00
Review: approve (.ah-out/review/kern-notify-3/T1.verdict.json)
Änderung: Die Spalten der Spec an `NotificationSettings`, `Notification.escalated_at` und `NotificationIncident.critical_since`, die Migration mit `server_default` auf den Standardwerten; der Downgrade setzt `digest`-Einträge auf `pending`. Die Prefs-API GET/PUT bekommt die neuen Felder additiv (fehlendes Feld behält seinen Wert); geprüft werden `HH:MM`, `minutes` ∈ {5,10,30}, der Kanal und die IANA-Zone (422). `quiet.py` (SPDX) rechnet `in_quiet`, `quiet_end` und `next_digest_at` in der Zone der Person, Standard UTC. Vorher prüfen, ob das Server-Image `tzdata` hat (`/usr/share/zoneinfo` im Image oder das Python-Paket), sonst `tzdata` in die Abhängigkeiten und `THIRD_PARTY_LICENSES.md`, per `set-files`. Tests: Prefs-Rundlauf und 422-Fälle; Zeitrechnung über Mitternacht, an beiden DST-Umstellungstagen in `Europe/Berlin`, in UTC und in einer Zone ohne DST; Migration hoch und runter. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_quiet.py tests/test_notification_settings.py tests/test_notification_prefs_test.py tests/test_openapi_snapshot.py tests/test_response_shapes.py tests/test_alembic_builtin.py
Doku: → T5

### T2 — Server: Ruhezeit hält Nicht-Kritisches zurück, Zusammenfassung sammelt E-Mails (R-1081)  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/incidents.py, apps/server/app/modules/notifications/digest.py, apps/server/app/modules/notifications/outbox.py, apps/server/app/modules/hooks/scheduler.py, apps/server/app/scheduler_main.py, apps/server/tests/test_notification_digest.py, apps/server/tests/test_notifications.py, apps/server/tests/test_outbox.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @2434edff1 2026-11-07T11:58:19+01:00
Review: approve (.ah-out/review/kern-notify-3/T2.verdict.json)
Änderung: `_queue` setzt in der Ruhezeit der Person für Info, Warnung und `ok` `next_attempt_at` = Ende der Ruhezeit (Kritisch nur ohne Durchlass). Bei eingeschalteter Zusammenfassung bekommen E-Mail-Einträge für Info, Warnung und `ok` Status `digest`. `digest.py` (SPDX) `send_digests(db, now)` schickt je fälliger Person (`next_digest_at`, `digest_last_at`) eine Mail mit allen `digest`-Einträgen, setzt sie auf `sent` und `digest_last_at`. Ist die Zusammenfassung aus, gehen wartende `digest`-Einträge beim nächsten Lauf als Zusammenfassung raus; ohne Einträge geht keine Mail. Der Systemjob läuft alle fünf Minuten neben `schedule_outbox_drain`. Tests: zurückgehalten und zur Endzeit zugestellt (Drain mit `now` danach), Kritisch mit und ohne Durchlass, `digest` liegt im Drain, Versand um 08:00 täglich und am Montag, keine Mail ohne Einträge, kein Doppelversand im selben Fenster. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_digest.py tests/test_notifications.py tests/test_outbox.py tests/test_notification_incidents.py tests/test_notification_channels.py
Doku: → T5
Abhängt von: T1

### T3 — Server: Eskalation unbestätigter kritischer Vorfälle an den Kanal der Person (R-1081)  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/incidents.py, apps/server/app/modules/notifications/escalation.py, apps/server/app/modules/hooks/scheduler.py, apps/server/app/scheduler_main.py, apps/server/tests/test_notification_escalation.py, apps/server/tests/test_notification_incidents.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @eef85d260 2026-11-07T12:15:19+01:00
Review: approve (.ah-out/review/kern-notify-3/T3.verdict.json)
Änderung: `critical_since` wird beim ersten kritischen Ping eines Vorfalls gesetzt und geleert, wenn er behoben wird. Beim Wiederöffnen leert `act` außerdem `escalated_at` der Zeilen. `escalation.py` (SPDX) `escalate_due(db, now)`: für offene Vorfälle mit `critical_since` ≤ `now − Frist der Person` und einer Zeile ohne `escalated_at`, die nicht stumm ist, und mit Eskalation an, Kanal an und Ziel vorhanden, ein Outbox-Eintrag auf dem gewählten Kanal mit Schweregrad `critical` und dem Text „Unbestätigt seit N Min.: <Titel>“ (Ruhezeit wie Kritisch). `escalated_at` wird mit `escalated_at IS NULL` im UPDATE gesetzt, der Eintrag `escalated` mit dem Kanal kommt in die Zeitleiste, die SSE-Benachrichtigung wie bei `finish_actions`. Der Systemjob läuft jede Minute. Tests: Eskalation nach Frist, nicht vor der Frist, nicht nach Bestätigen oder Beheben, einmal je Person, wieder nach Wiederöffnen, stumm, Kanal ohne Ziel oder ausgeschaltet, Matrix ohne den Kanal eskaliert trotzdem, Abfragezahl begrenzt. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_escalation.py tests/test_notification_incidents.py tests/test_notification_incident_api.py
Doku: → T5
Abhängt von: T1

### T4 — Desktop-UI: Abschnitt Ruhe, Eskalation & Zusammenfassung, Ruhezeit und Durchlass im Desktop, Ton bei Kritisch (R-1081)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/components/NotificationPrefs.svelte, apps/desktop/ui/src/components/NotificationPrefs.test.ts, apps/desktop/ui/src/lib/stores/notifyPrefs.ts, apps/desktop/ui/src/lib/stores/notifyPrefs.test.ts, apps/desktop/ui/src/lib/stores/dnd.ts, apps/desktop/ui/src/lib/stores/dnd.test.ts, apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/components/AppShell.notifications.test.ts, apps/desktop/ui/src/lib/osNotify.ts, apps/desktop/ui/src/lib/sound.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/api/types.contract.test.ts, apps/desktop/ui/src/lib/i18n/i18n.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @efe5301e7 2026-11-07T12:45:33+01:00
Review: approve (.ah-out/review/kern-notify-3/T4.verdict.json)
Änderung: Typen der neuen Prefs-Felder. Neuer Abschnitt in `NotificationPrefs.svelte` nach dem Mockup: Ruhezeiten (zwei Zeitfelder und Schalter), „Kritisches trotzdem durchlassen“, Eskalation (5/10/30 Min., Kanal; Kanäle ohne Ziel oder ausgeschaltet deaktiviert, Hinweis), Zusammenfassung (Aus/Täglich/Wöchentlich), Ton bei Kritisch. Beim Speichern geht die Zone aus `Intl` mit. `notifyPrefs` rechnet `inQuiet(now)` in der gespeicherten Zone. `allows` in `dnd.ts` lässt Kritisches nur mit Durchlass durch und schweigt in der Ruhezeit. `AppShell` spielt bei einem gezeigten kritischen Toast den Ton aus `sound.ts` (SPDX, WebAudio, ohne `AudioContext` still), wenn er an ist; OS-Meldungen folgen derselben Prüfung. i18n DE/EN. Tests: Abschnitt lädt und speichert die Felder samt Zone, Ruhezeit über Mitternacht, Durchlass für DND und Ruhezeit, Ton nur bei Kritisch und nur außerhalb der Ruhe. Mehr als acht Dateien, weil Store, Shell und Formular die Prüfung gemeinsam tragen.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T5
Abhängt von: T1

### T5 — Doku DE+EN und CHANGELOG (R-1081)  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/server.html, docs/en/developer/server.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-notify-3.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b3ee068db 2026-11-07T12:52:19+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Unterabschnitt Ruhezeiten, Eskalation, Zusammenfassung und Ton unter „Kanäle und Matrix“ (DE `#kanaele`, EN `#channels`), dazu Outbox-Status `digest`, zwei Systemjobs, `critical_since`/`escalated_at` in der Server-Doku, die neuen Prefs-Felder in der API-Referenz und ein CHANGELOG-Fragment (umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/server.html, docs/en/developer/server.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-notify-3.md
Task-Review: am Ende
Abhängt von: T2, T3, T4

### T6 — Eskalation folgt der aktuellen Sicht und den Kategorien (R-1081)  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/escalation.py, apps/server/tests/test_notification_escalation.py, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/server.html, docs/en/developer/server.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @42cfa2ffe 2026-11-07T13:10:33+01:00
Review: approve (.ah-out/review/kern-notify-3/T6.verdict.json)
Änderung: Aus der Abschlussprüfung. `escalate_due` eskaliert nur, wer den Vorfall jetzt noch sieht (dieselbe Prüfung wie `access`: Admin oder ein zugewiesener Server des Vorfalls), und nicht in einer ausgeschalteten Kategorie (wie `service.channels_for`). Ohne Sicht oder in stummer Kategorie bleibt `escalated_at` leer. Die Mitglieder der fälligen Vorfälle lädt eine Abfrage. Tests: Zuweisung entzogen, früherer Admin bei einem Vorfall ohne Server, Wiederöffnen nach dem Entzug, zugewiesene Person eskaliert, stumme und andere Kategorie. Doku: der Satz zur Stummschaltung klarer, Sicht und Kategorie im Abschnitt Eskalation DE+EN.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_escalation.py
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/server.html, docs/en/developer/server.html
Abhängt von: T3, T5

### T7 — Eskalationsfrist mit Obergrenze im Schema (R-1081)  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/schemas.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @eeb63b0ab 2026-11-07T13:31:37+01:00
Review: approve (.ah-out/review/kern-notify-3/T7.verdict.json)
Änderung: Aus der PR-CI (#414, run 42371542725): `test_every_integer_input_has_a_maximum` verlangt ein `maximum` für jede Ganzzahl-Eingabe; `Literal[5, 10, 30]` erzeugt nur ein `enum`. `minimum`/`maximum` (5/30) ins Schema von `escalation.minutes`, Snapshot nachziehen; die Schutzregel bleibt unverändert.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_openapi_integer_bounds.py tests/test_openapi_snapshot.py tests/test_notification_settings.py
Doku: keine (nur die Schemagrenze; die Werte 5/10/30 stehen schon in der API-Referenz)
Abhängt von: T1

## Entscheidungen
- T1: Das Python-Paket `tzdata` kommt als Abhängigkeit dazu (Lock, `THIRD_PARTY_LICENSES.md`): das apt-`tzdata` des Images (trixie, ohne `tzdata-legacy`) kennt die alten Namen wie `Asia/Calcutta` nicht, die `Intl` liefern kann; Dev-Box und CI haben sie und hätten es verdeckt (Reviewer T1). Ein Test mit leerem TZPATH belegt es.
- T1: Request-Felder in snake_case wie die übrigen (`sound_critical`), Response in camelCase (`soundCritical`).
- T1: Eskalation an ohne Kanal ist 422; aus darf der Kanal leer sein. Ein Kanal ohne Ziel wird gespeichert (Spec).
- T1: Eine gespeicherte, inzwischen unbekannte Zone zählt als UTC (`quiet.zone`), statt den Job scheitern zu lassen.
- T1: Ein Ende in der doppelten Herbststunde nimmt den ersten Durchgang nach `now` (erst `fold=0`, dann `fold=1`).
- T1: `HH:MM` mit `[0-9]` statt `\d`: pydantics Pattern nimmt mit `\d` auch arabisch-indische Ziffern an (gegengeprüft).
- T2: Ein Outbox-Eintrag trägt `created_at` = Zeit des Pings (statt der DB-Uhr): Ruhezeit, Fenster der Zusammenfassung und Zeilen der Mail rechnen mit derselben Uhr.
- T2: Die Zusammenfassung geht an die Adresse des neuesten Eintrags; ein Fehlversand zählt einen Versuch je Eintrag und wiederholt beim nächsten Lauf (alle 5 Min.) ohne Backoff bis `NOTIFICATION_MAX_ATTEMPTS`, dann `failed`.
- T2: Fällig ist sie zur ersten Versandzeit nach dem späteren von ältestem Eintrag und `digest_last_at`: ein nach dem Versand committeter Ping mit älterem `created_at` wartet aufs nächste Fenster.
- T2: Eine Zusammenfassungs-Mail beachtet die Ruhezeit nicht (08:00 liegt außerhalb der Standard-Ruhezeit).
- T3: Der Text ist englisch („Unacknowledged for N min: <title>“, Code-Strings englisch); die Spec gibt die Bedeutung.
- T3: Eskaliert wird nur eine Zeile, die die Person mit `critical` bekam (`Notification.severity`).
- T3: `critical_since` setzt jedes Ereignis, das den offenen Vorfall kritisch macht, nicht erst der Ping: ein Wiederöffnen in `REOPEN_WINDOW` pingt niemanden und darf trotzdem wieder eskalieren (Spec). Vorfälle ohne Schlüssel setzen es beim Anlegen.
- T3: Ein Kanal ohne Ziel oder ausgeschaltet setzt `escalated_at` nicht; kommt das Ziel später, eskaliert der nächste Lauf.
- T3: `escalated_at` leert das Wiederöffnen in `act` und in `_problem`; `critical_since` leert jedes Beheben.
- T3: Die Server-Stummschaltung prüft die Zeile über `source_id`, wie Feed und Badge; die Sichtbarkeit wird beim Eskalieren nicht neu geprüft (die Zeile hat die Person schon).
- T4: Der Ton folgt dem gezeigten kritischen Toast: Wird Kritisches durchgelassen, klingt der Ton auch in der Ruhezeit und unter „Nicht stören“; ohne Durchlass schweigen Toast, OS-Meldung und Ton (Spec „Für Kritisches gilt derselbe Schalter“). Ein Ton je Stapel neuer Einträge.
- T4: Der Abschnitt erscheint nur, wenn der Server die Felder schickt (`quiet` vorhanden); dann gehen sie beim Speichern mit, sonst nicht. Ein alter Server würde sie zwar ignorieren (`RequestModel` ohne `extra=forbid`), die Einstellungen wirkten dort aber nicht.
- T4: Ein Eskalationskanal ist wählbar mit gespeichertem Ziel, eingeschaltet und vom Server zustellbar; der Schalter der Eskalation bleibt gesperrt, bis ein Kanal gewählt ist (der Server lehnt an ohne Kanal mit 422 ab).
- T4: Die Ruhezeit des Desktops rechnet in der gespeicherten Zone der Person (dieselbe Uhr wie der Server), nicht in der Zone des Rechners; eine unbekannte Zone zählt als UTC.
- T6: Die Eskalation prüft die Sicht der Person beim Versand neu, mit `incidents._sight` wie `access`; die T3-Zeile, sie werde nicht neu geprüft, gilt damit nicht mehr. Eine ausgeschaltete Kategorie eskaliert nicht (Spec, wie `channels_for`).
- T5: Das Verify der Doku-Task ist `scripts --strict -- doc_smoke_test` (Komponente `scripts`), wie in den übrigen Doku-Tasks; der Plan nannte die Komponente `docs`, die `verify.sh` nicht kennt.
