# klein-tests-monitoring-4 — agent_ping: beide Meldungsformen testen

Roadmap: R-1600.

## Problem

`SecHeartbeat.svelte` liest das Alter eines Agents aus der Meldung des `agent_ping`-Checks: `unreachable for N min` (Agent weg) und `last report Ns ago` (Agent meldet sich). Die Tests in `test_agent_ping_checker.py` pinnen nur die erste Form (`assert msg == "Agent unreachable for 16 min …"`); die zweite prüft kein Test. Ändert jemand den Wortlaut des ok-Falls, bricht die Desktop-Anzeige still.

## Ziel & Nicht-Ziele

Ein Test pinnt den Wortlaut der ok-Meldung. Nicht-Ziel: der Wortlaut selbst oder die Desktop-Seite ändern sich nicht.

## Betroffene Komponenten & Dateien

`apps/monitoring/tests/test_agent_ping_checker.py`.

## Datenmodell / API / Migrationen

Keine.

## Trade-offs & Alternativen

Der Test steht neben den Tests des Checkers, nicht im Desktop-UI-Test: die Meldung ist die Quelle, die UI der Leser. Ein Querverweis im Kommentar nennt `SecHeartbeat.svelte`.

## Risiken & Rollback

Nur ein Test; ein Commit.

## Doku-Impact

Keine.

## Offene Fragen

Keine.
