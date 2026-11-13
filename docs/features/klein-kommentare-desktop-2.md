<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-kommentare-desktop-2

## Problem / Motivation
R-1398: In `apps/desktop/ui/src/lib/api/types.ts` zaehlt der Kommentar zu `MonitorResourceDetails.problems` die
Schluessel auf (`cpu, memory, swap, load, disk:<mount>, inode:<mount>, temp:<sensor>`). Seit
`_grade_load_shed` (`apps/monitoring/app/checkers/agent.py`, R-1268) kommt der Schluessel `load_shed` dazu: nur als
`warning`, ohne Hysterese. Der Kommentar nennt ihn nicht.

## Ziel & Nicht-Ziele
Ziel: der Kommentar nennt `load_shed`. Nicht-Ziel: den Typ aendern (`Record<string, ...>` deckt den Schluessel schon).

## Betroffene Komponenten & Dateien
`apps/desktop/ui/src/lib/api/types.ts` (nur Kommentar). Die Typen sind per `sync-from-web.sh` an das Web-Frontend
gebunden; `MonitorResourceDetails` steht dort nicht (vor dem Bau gegriffen), sonst wuerde die PR-CI den Gleichlauf pruefen.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
Keine; ein Satz im vorhandenen Kommentar.

## Risiken & Rollback
Keine, reine Kommentaraenderung; Revert des Commits.

## Doku-Impact
Keine (interner Kommentar).

## Offene Fragen
Keine.
