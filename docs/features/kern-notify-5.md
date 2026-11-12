# Benachrichtigungen: Grenze für manuelle Verlaufseinträge, Eskalationsfrist beim Rückfall (kern-notify-5)

Roadmap: R-1147, R-1186 (Kevin 2026-11-09 Triage, vor 0.47.0; Entscheidungen Kevin 2026-11-10).

## Problem / Motivation
- **R-1147:** Der Verlauf eines Vorfalls hat eine Obergrenze (`HISTORY_MAX`, `incidents.py:56`), die `_cap_history`
  aber nur über automatische Einträge hält; für Notizen und Aktionen von Hand gibt es keine.
  Entscheidung Kevin: höchstens 200 manuelle Einträge je Vorfall, danach 409 für
  Notiz und Wieder öffnen; Bestätigen und Beheben bleiben möglich.
- **R-1186:** Fällt ein kritischer Vorfall auf Warnung zurück, läuft die Eskalationsfrist weiter
  (`critical_since` bleibt, `incidents.py:264`), und ein Vorfall, der nur noch Warnung ist, eskaliert als
  „kritisch, unbestätigt“. Entscheidung Kevin: Die Frist stoppt beim Rückfall auf Warnung, ein erneutes Kritisch
  beginnt eine neue Frist.

## Ziel & Nicht-Ziele
Ziel: Notiz und Wieder öffnen antworten 409, sobald ein Vorfall 200 Einträge von Hand hat; der Rückfall eines
Vorfalls von Kritisch auf Warnung beendet seine Frist und erlaubt nach einem neuen Kritisch eine neue Eskalation.
Nicht-Ziele: kein seitenweiser Verlauf, keine Änderung an `HISTORY_MAX` und `_cap_history`, keine Änderung an
Sammelmeldungen (ihr Schweregrad sinkt in einem offenen Vorfall nicht).

## Betroffene Komponenten & Dateien
- `apps/server/app/modules/notifications/incidents.py`: Grenze `MANUAL_MAX = 200` und eine Zählung der Einträge
  von Hand (Gegenstück zu `_AUTOMATIC`); im `_trigger` nach dem Setzen des Schweregrads: nicht mehr kritisch →
  `critical_since = None` und `_rearm` (die bisherigen Eskalationen gelten als erledigt, eine neue Frist darf
  wieder eskalieren).
- `apps/server/app/modules/notifications/router.py` (`_team_action`, `:198`): für `note` und `reopened` 409, wenn
  die Grenze erreicht ist.
- `apps/server/app/modules/notifications/escalation.py`: Modul-Docstring (Frist ab dem letzten Wechsel auf
  Kritisch).
- Tests: `apps/server/tests/test_notification_incident_api.py`, `apps/server/tests/test_notification_escalation.py`.
- Doku: `docs/admin/monitoring.html` und `docs/en/admin/monitoring.html` (Eskalation `:405`, Teamaktionen `:432`),
  `changelog.d/kern-notify-5.md`.

## Datenmodell / API / Migrationen
Keine Migration. API: `POST /incidents/{id}/notes` und `POST /incidents/{id}/reopen` antworten zusätzlich 409
(`detail`: Verlauf voll), sobald der Vorfall 200 Einträge von Hand hat. Web und Desktop zeigen das `detail` einer
409 schon heute als Fehler; kein Vertrags-Drift der Typen.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
- **409 statt Verlauf seitenweise:** Kevins Entscheidung; kleiner, ohne Vertragsänderung des Details.
- **Rückfall: `_rearm` mit:** ohne ihn eskaliert, wer in der ersten Frist schon eine Nachricht bekam, nach einem
  neuen Kritisch nicht mehr, und die neue Frist wäre für ihn wirkungslos. Flattern zwischen Warnung und Kritisch
  eskaliert höchstens einmal je volle Frist am Stück kritisch.

## Risiken & Rollback
Ein Team, das an einem langen Vorfall mehr als 200 Notizen schreibt, muss einen neuen anlegen lassen (Beheben,
das nächste Problem öffnet einen neuen). Rollback: Revert.

## Doku-Impact
`docs/admin/monitoring.html` DE+EN: Eskalation (Frist stoppt beim Rückfall, neue Frist nach erneutem Kritisch),
Teamaktionen (Grenze von 200 Einträgen von Hand). CHANGELOG über `changelog.d/kern-notify-5.md`.

## Offene Fragen
Keine.
