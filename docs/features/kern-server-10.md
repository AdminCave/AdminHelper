# kern-server-10 — Server: Supervisor-Frist und 422-Form

Roadmap: R-1444, R-1494

## Problem / Motivation
- **R-1444:** Auf `main` lief der Server-Shard 1/2 (CI-Lauf 43496686654, Versuch 1) in den 25-min-Jobdeckel; der
  Rerun war grün. Der Runner war in diesem Versuch durchweg etwa fünfmal langsamer (Zeile 3 der Fortschrittsanzeige
  2 min statt 19 s). Das einzige `F` steht an Position 810 der Shard-Reihenfolge, die `--shard` deterministisch aus
  `shard_weights.toml` berechnet; auf c16472cf9 nachgesammelt (1549 Tests, wie im Lauf) ist das
  `test_frps_supervisor.py::test_a_valid_change_restarts_frps_once_from_the_new_copy[new token]`. Die Datei wartet
  mit `WAIT = 10.0` (`apps/server/tests/test_frps_supervisor.py:79`) auf Bedingungen; `.claude/rules/testing.md`
  („Fristen“) verlangt mindestens 30 s. Die Fehlermeldung selbst ist verloren (Job abgebrochen vor der
  Zusammenfassung), die Zuordnung ist deshalb eine Rekonstruktion.
- **R-1494:** Vier Routen antworten auf einen fachlichen Eingabefehler mit `422` und `detail` als String, obwohl ihr
  OpenAPI-Schema `HTTPValidationError` deklariert: `apps/server/app/modules/connections/router.py:314` (leerer Name
  ohne Server), `apps/server/app/modules/ansible/router.py:61` und `:154` (YAML nicht lesbar),
  `apps/server/app/modules/notifications/router.py:602` (gesperrtes Ziel im Testversand). Kevin hat die Änderung der
  422-Form wie bei R-1450 angenommen (Triage 2026-11-16).

## Ziel & Nicht-Ziele
- `WAIT` in `test_frps_supervisor.py` auf 30 s; alle Verwendungen sind Obergrenzen einer Abfrage, ein grüner Lauf
  dauert nicht länger. Belegt mit dem Dauerlauf aus `testing.md`.
- Die vier Stellen werfen `RequestValidationError` wie `servers/router.py` (`_invalid_name`), Antwort
  `{"detail": [{"type", "loc", "msg", "input"}]}`: `loc` `["body", "name"]`, `["body", "content"]`,
  `["body", "channel"]`.
- Nicht: der Jobdeckel in `ci.yml` (Workflow, Kevins Merge), keine Änderung am Supervisor, keine weiteren Routen.

## Betroffene Komponenten & Dateien
server: `apps/server/tests/test_frps_supervisor.py`; `apps/server/app/modules/{connections,ansible,notifications}/router.py`
mit ihren Tests (`test_connection_derived_names.py`, `test_ansible.py`, `test_notification_prefs_test.py`);
`docs/developer/api-reference.html` DE+EN; `changelog.d/kern-server-10.md`.

## Datenmodell / API / Migrationen
Keine Migration. API: nur die Form des 422-Bodys der vier Fälle (Statuscode bleibt). Web und Desktop lesen
`detail` als String oder Liste (`apps/web/src/lib/api/client.ts`, `msg` je Eintrag); das OpenAPI-Schema ändert sich
nicht.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
- R-1444: einen `faulthandler_timeout` oder `-v` in der CI zu setzen, machte den nächsten Hänger sichtbar, ändert aber
  `ci.yml` (Kevin) und behebt nichts; die Fristregel ist die belegte Ursache. Empfehlung: nur `WAIT`.
- R-1494: `msg` behält den bisherigen Text, damit Clients, die ihn anzeigen, dasselbe zeigen.

## Risiken & Rollback
Ein Client, der `detail` nur als String liest, zeigt bei diesen vier Fällen den generischen Text; Web/Desktop lesen
beide Formen. Rollback: Revert der Task.

## Doku-Impact
`docs/developer/api-reference.html` DE+EN: die 422-Form der vier Fälle. CHANGELOG-Fragment.

## Offene Fragen
Keine.
