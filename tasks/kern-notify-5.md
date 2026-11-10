# Benachrichtigungen: Grenze für manuelle Verlaufseinträge, Eskalationsfrist beim Rückfall — Task-Ledger
Status: bereit · Branch: feature/kern-notify-5 · Review: pro Task
Spec: docs/features/kern-notify-5.md (Roadmap R-1147, R-1186)
Heavy: linux-full — Server-API (Benachrichtigungen); Sammellauf. Kein `scenario`, kein `windows`.
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1147: höchstens 200 Verlaufseinträge von Hand, danach 409 für Notiz und Wieder öffnen  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/incidents.py, apps/server/app/modules/notifications/router.py, apps/server/tests/test_notification_incident_api.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @9e26e76bf 2026-11-10T06:36:17+01:00
Review: approve (.ah-out/review/kern-notify-5/T1.verdict.json)
Änderung: `MANUAL_MAX = 200` und Zählung der Einträge von Hand (Gegenstück zu `_AUTOMATIC`); `_team_action`
antwortet für `note` und `reopened` 409, sobald der Vorfall `MANUAL_MAX` Einträge von Hand hat; Bestätigen und
Beheben bleiben möglich. API-Test: an der Grenze 409 für Notiz und Wieder öffnen, Beheben und Bestätigen gehen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_incident_api.py tests/test_openapi_snapshot.py
Doku: → T3

### T2 — R-1186: Rückfall auf Warnung stoppt die Eskalationsfrist  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/incidents.py, apps/server/app/modules/notifications/escalation.py, apps/server/tests/test_notification_escalation.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @dc8ab7f06 2026-11-10T06:44:35+01:00
Review: approve (.ah-out/review/kern-notify-5/T2.verdict.json)
Änderung: Im `_trigger` setzt ein Vorfall, der nicht mehr kritisch ist, `critical_since` zurück und ruft `_rearm`;
ein erneutes Kritisch beginnt eine neue Frist. Tests: kein Eskalieren nach Rückfall vor Fristende; neue Frist ab
dem erneuten Kritisch; wer schon eskaliert war, eskaliert nach der neuen Frist erneut.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_escalation.py tests/test_notification_incidents.py
Doku: → T3
Abhängt von: T1

### T3 — Doku und CHANGELOG  [x]
Komponente: server · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-notify-5.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @a7624659c 2026-11-10T06:45:29+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: DE+EN: Eskalation (Frist stoppt beim Rückfall, neue Frist nach erneutem Kritisch), Teamaktionen (Grenze
von 200 Einträgen von Hand); CHANGELOG-Eintrag neutral.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_escalation.py
Doku: diese Task
Task-Review: am Ende

### T4 — Abschlussprüfung: Kommentar an `critical_since`, Entwickler-Doku, Docstrings  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/models.py, apps/server/app/modules/notifications/escalation.py, apps/server/tests/test_notification_escalation.py, docs/developer/server.html, docs/en/developer/server.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @ec765b9a3 2026-11-10T06:55:29+01:00
Review: approve (.ah-out/review/kern-notify-5/T4.verdict.json)
Änderung: Fund der Abschlussprüfung: der Kommentar an `critical_since` nennt den ersten kritischen Ping, seit T2 ist es
der letzte Wechsel auf Kritisch, ein Rückfall auf Warnung leert ihn; dasselbe in der Entwickler-Doku DE+EN, dort auch
die Grenze von 200 Einträgen von Hand; Docstrings aus T2 neu umbrochen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_escalation.py tests/test_notification_incidents.py
Doku: docs/developer/server.html, docs/en/developer/server.html
Abhängt von: T3

## Entscheidungen
- T2: Der Rückfall auf Warnung ruft `_rearm` (wie ein Reopen): ohne ihn eskaliert, wer in der ersten Frist schon eine Nachricht bekam, nach einem neuen Kritisch nicht mehr; Flattern eskaliert höchstens einmal je volle Frist am Stück kritisch.
