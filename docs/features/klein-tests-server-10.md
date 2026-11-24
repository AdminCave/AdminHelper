<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-server-10 — Test-Zeit und Testname

Zug `tasks/klein-tests-server-10.md` mit R-1718 und R-1741. `overlap.sh` (2026-11-24): kein offener Branch ändert
die betroffenen Dateien.

## Problem / Motivation
- **R-1718:** `test_a_dashboard_that_never_answers_is_named_in_the_failure_of_the_wait`
  (`apps/server/tests/test_frps_supervisor.py`) wartet 90 s auf den Timeout seines Helfers `_with_dashboard`
  (`3 * WAIT`, `WAIT = 30.0`) und prüft nur dessen Fehlermeldung. Das kostet je Python-Bein 90 s CI-Zeit.
- **R-1741:** `apps/monitoring/tests/test_auth.py` nennt einen Test `test_correctkey_matches`; richtig ist
  `test_correct_key_matches`.

## Ziel & Nicht-Ziele
`_with_dashboard` bekommt einen optionalen Timeout (Standard bleibt `3 * WAIT`); der eine Test gibt einen kurzen
mit (Richtwert 10 s: der Supervisor pollt jede Sekunde, `FRPS_READ_SECONDS=1`). Die Assertions bleiben unverändert,
alle anderen Aufrufer behalten ihr Verhalten. Der Test wird umbenannt, sonst nichts. Kein Produktcode.

## Betroffene Komponenten & Dateien
server (`apps/server/tests/test_frps_supervisor.py`), monitoring (`apps/monitoring/tests/test_auth.py`).

## Datenmodell / API / Migrationen
Keine.

## Trade-offs & Alternativen
Ein Parameter am Helfer statt eigener Kopie des Wartens im Test: eine Zeile mehr, kein zweiter Pfad. Ein zu kurzer
Timeout würde den Test flackern lassen; 10 s lassen rund neun Polls zu, die Meldung nennt schon nach dem ersten
Request die Pfade.

## Risiken & Rollback
Nur Tests; Rückgängig per Revert. Gegenprobe: der Test bleibt rot, wenn die Meldung die Request-Liste nicht mehr
nennt.

## Doku-Impact
Keine (Tests).

## Offene Fragen
Keine.
