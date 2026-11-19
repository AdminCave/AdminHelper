# kern-doku-3: Klassenkennung in zwei abgeschlossenen Ledgern entfernen

Roadmap: R-1589 (REF). Triage Kevin 2026-11-18: neutralisieren, aktueller Stand; die Git-Historie bleibt.


# kern-doku-4 — Klassenkennung aus weiteren öffentlichen Plan-Dateien

## Problem / Motivation

R-1618 (Nachlese zu R-1589): Fünf öffentliche Plan-Dateien nennen die Roadmap-Klasse einzelner Zeilen oder Tasks in
anderer Form als die zwei, die kern-doku-3 bereinigt hat: `tasks/kern-agent-4.md:13`, `tasks/kern-agent-5.md:13`,
`tasks/ops-1.md:14`, `tasks/kern-monitoring-27.md:52`, `docs/features/kern-agent-2.md:8`. Öffentliche Plan-Dateien
sollen diese Klasse nicht tragen (Regel 2026-10-22, neutral planen).

## Ziel und Nicht-Ziele

Ziel: In den fünf Zeilen fällt die Klassenkennung weg; jeder Satz sagt weiter, wo `security` zusätzlich prüfte bzw.
dass Einzelheiten privat stehen.

Nicht-Ziele: keine Änderung an der Git-Historie. Nicht angefasst werden allgemeine Regeltexte (`tasks/README.md`,
`arch-workflow-*`), die die Klasse als Begriff nennen, und der Dedup-Key in `tasks/kern-deps-4.md:18`, der eine
öffentliche Abhängigkeits-Advisory bezeichnet.

## Betroffene Komponenten und Dateien

Die fünf Dateien oben, je eine Zeile.

## Datenmodell / API / Migrationen

Keine.

## Externe Integrationen

Keine.

## Trade-offs und Alternativen

Belassen: die Dateien sind abgeschlossen, die Historie trägt die Zeilen weiter. Empfehlung wie bei kern-doku-3: der
aktuelle Baum folgt der Regel.

## Risiken und Rollback

Keine; Revert des Task-Commits.

## Doku-Impact

Keine (interne Plan-Dateien).

## Offene Fragen

Keine.
