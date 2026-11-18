# kern-doku-3: Klassenkennung in zwei abgeschlossenen Ledgern entfernen

Roadmap: R-1589 (REF). Triage Kevin 2026-11-18: neutralisieren, aktueller Stand; die Git-Historie bleibt.

## Problem / Motivation

Die abgeschlossenen Ledger `tasks/kern-desktop-3.md` und `tasks/ops-2.md` nennen in ihrer Vorbemerkung (Zeile 14) die
Roadmap-Klasse einzelner Tasks in Klammern. Öffentliche Plan-Dateien sollen diese Klasse nicht tragen (Regel
2026-10-22, neutral planen).

## Ziel und Nicht-Ziele

Ziel: In beiden Vorbemerkungen fällt die Klammer mit der Klasse weg; der Satz nennt weiter, bei welchen Tasks
`security` zusätzlich prüfte.

Nicht-Ziele: keine Änderung an der Git-Historie, an Specs oder an anderen Ledgern (eine Suche nach der Kennung in
`tasks/` und `docs/features/` findet nur diese zwei Stellen).

## Betroffene Komponenten und Dateien

`tasks/kern-desktop-3.md`, `tasks/ops-2.md` (je eine Zeile).

## Datenmodell / API / Migrationen

Keine.

## Externe Integrationen

Keine.

## Trade-offs und Alternativen

Belassen wäre ohne Aufwand, widerspricht aber der Regel; die Historie umzuschreiben ist ausgeschlossen (Kevin).

## Risiken und Rollback

Keine Wirkung auf Code oder Nutzer. Rollback: Revert des Task-Commits.

## Doku-Impact

Keiner: Ledger sind interne Plan-Dateien, kein dokumentiertes Verhalten; kein CHANGELOG-Eintrag.

## Offene Fragen

Keine.
