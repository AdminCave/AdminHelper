# Benachrichtigungen: Zielprüfung, Sperrreihenfolge, Zusammenfassung — Task-Ledger
Status: aktiv · Branch: feature/kern-notify-4 · Review: pro Task
Spec: docs/features/kern-notify-4.md (Roadmap R-1178, R-1179, R-1149, R-1188)
Heavy: linux-full — Server-API (Benachrichtigungen) und Monitoring; Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1178, R-1179: Zielprüfung ausgehender Anfragen ergänzt  [x]
Komponente: server · Dateien: apps/server/app/core/ssrf.py, apps/monitoring/app/core/ssrf.py, apps/server/tests/test_ssrf.py, apps/monitoring/tests/test_ssrf.py
Evidenz: run.sh[quick] server monitoring: 5 passed, 0 failed, 13 skipped @ad0ab5442 2026-11-10T04:16:08+01:00
Review: approve (.ah-out/review/kern-notify-4/T1.verdict.json)
Änderung: zwei Adressbereiche kommen in die Listen der Zielprüfung, in beiden Kopien gleich (Paritätstest); Tests je Kopie für
beide Bereiche mit und ohne Freigabe. Details in der privaten Notiz des Zugs.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T4

### T2 — R-1149: Erholung und Bestätigen sperren in einer Reihenfolge  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/incidents.py, apps/server/app/modules/notifications/router.py, apps/server/tests/test_notification_incident_locks.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @425b2e4ee 2026-11-10T04:25:55+01:00
Review: approve (.ah-out/review/kern-notify-4/T2.verdict.json)
Änderung: `_recover` sperrt vor jeder Änderung alle Vorfälle, die es anfassen kann (aktive mit einem der Schlüssel und
den letzten Vorfall je Schlüssel und Server), in einer Abfrage nach id; `_note_stale` sperrt nicht mehr selbst.
`ack_incidents` prüft ohne Sperre vor und sperrt nur Vorfälle, die es bestätigen darf (danach erneut geprüft).
Neue Testdatei (SPDX) mit zwei echten Verbindungen: zwei Ereignisse desselben Schlüssels gleichzeitig öffnen einen
Vorfall (`_lock`); eine Erholung, die auf einen gesperrten behobenen Vorfall wartet, hält den aktiven mit größerer id
noch nicht; ein `ack` mit einem behobenen Vorfall hält diesen nicht.
Beweis: reviewer branch arch-notify-incidents 2026-11-05, incidents.py:291,383-387,525; router.py:222-224
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_incident_locks.py tests/test_notification_incidents.py tests/test_notification_incident_api.py
Doku: → T4

### T3 — R-1188: Zusammenfassungs-Mail mit Obergrenze  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/digest.py, apps/server/tests/test_notification_digest.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @eeb40fb38 2026-11-10T04:28:40+01:00
Review: approve (.ah-out/review/kern-notify-4/T3.verdict.json)
Änderung: `_send` schreibt höchstens 200 Zeilen (die neuesten zuletzt wie heute, also die ältesten 200), dahinter
„… and N more“; der Betreff nennt weiter die volle Zahl, alle Einträge gelten als versandt. Test: 201 Einträge →
200 Zeilen und der Hinweis, alle `sent`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_digest.py
Doku: → T4

### T4 — Doku und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/betrieb.html, docs/en/admin/operations.html, docs/developer/server.html, docs/en/developer/server.html, changelog.d/kern-notify-4.md
Änderung: DE+EN: die Liste der gesperrten Bereiche der Zielprüfung, die Obergrenze der Zusammenfassung, die Sperrreihenfolge
der Erholung (Entwicklerdoku). CHANGELOG-Eintrag neutral.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- R-1147, R-1180, R-1186, R-1187 → tasks/kern-notify-5.md (Fragen an Kevin).
- T2: die Erholung sperrt vorab in einer id-geordneten Abfrage; ein Reopen, der zwischen dieser Sperre und `_containing` committet, kann noch eine Sperre außer der Reihe auslösen. Restrisiko als Frage an Kevin (Empfehlung: hinnehmen; das Fenster ist klein, ein uncommitteter Reopen wird von FOR UPDATE nicht erfasst, Postgres bricht einen Deadlock ab).
