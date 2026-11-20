# kern-monitoring-54: Compose-Kennung nur aus eindeutigen Teilen

Roadmap: R-1663 (REF), Nachlese der Prüfung von kern-monitoring-53. Angenommen Kevin 2026-11-20.

## Problem
`_compose_ident` (`apps/monitoring/app/checkers/plugins.py:539`) setzt Projekt, Dienst und Nummer eines
Compose-Containers mit `/` zur Objekt-Kennung zusammen. Enthält ein Teil selbst `/`, ist die Kennung nicht mehr
eindeutig zerlegbar. Docker Compose lässt `/` in Projekt- und Dienstnamen nicht zu, der Fall entsteht nur aus einem
abweichenden Agent-Bericht.

## Ziel und Nicht-Ziele
- Ziel: Enthält Projekt oder Dienst ein `/`, gibt es keine Compose-Kennung; das Objekt behält wie bei einer
  unvollständigen Kennung den Containernamen als Schlüssel.
- Nicht-Ziel: Änderungen am Agent, an der API oder an gespeicherten Objekten.

## Betroffene Dateien
`apps/monitoring/app/checkers/plugins.py`, `apps/monitoring/tests/test_plugin_checkers.py`.

## Datenmodell / API / Migrationen
Keine.

## Risiken und Rollback
Ein Container mit `/` im Compose-Teil wechselte den Objekt-Schlüssel; nach Compose-Regeln gibt es keinen solchen.
Rollback: Revert des Commits.

## Doku-Impact
Keiner (internes Verhalten bei unzulässigen Agent-Daten, nicht dokumentiert).

## Offene Fragen
Keine.
