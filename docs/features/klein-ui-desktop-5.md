<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ui-desktop-5 — Heartbeat-Anzeige und Reihenfolge der Server-Seite

Roadmap R-1564, R-1542. Beides Desktop-UI (`apps/desktop/ui`), keine API- oder Datenänderung.

## Problem je Zeile
- **R-1564 (BUG):** `SecHeartbeat.svelte` nimmt die erste Zahl aus der Check-Meldung als Sekunden. Der Checker
  (`apps/monitoring/app/checkers/agent.py`) meldet aber `Agent unreachable for 47 min (limit: 15 min)` (Minuten) und
  `Agent active (last report 12s ago)` (Sekunden). Ersteres erscheint als 47 s.
- **R-1542 (FEAT):** Die Karte „Neu gefunden (n)" steht heute nach den Problem-Karten. Gewünscht: immer ganz oben.

## Ziel und Nicht-Ziele
- Die Anzeige liest Sekunden aus beiden Meldungsformen (Minuten ×60); eine unbekannte Form zeigt „—".
- „Neu gefunden" steht vor den Problem-Karten. Sonst bleibt die Reihenfolge (Problem-Karten, Rest, Kosten).
- Nicht-Ziel: die Meldung des Checkers ändern oder `details` um Sekunden erweitern (API-Vertrag, nicht nötig).

## Trade-offs
Meldungstext parsen bleibt, weil der Check heute keine Sekunden in `state.details` an die UI liefert; das Muster ist
an die zwei festen Meldungsformen des Checkers gebunden statt an „die erste Zahl".

## Doku-Impact
`docs/admin/monitoring.html` (DE+EN) nennt die Reihenfolge der Karten; sie ändert sich. Changelog-Fragment.

## Risiken und Rollback
Gering, reine UI. Rollback per Revert.

## Offene Fragen
Keine.
