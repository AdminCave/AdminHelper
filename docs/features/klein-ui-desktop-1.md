<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ui-desktop-1 — Desktop-UI: Ruhe-Hinweis und Fehler im abgedockten Terminal (R-1185, R-1169)

## Problem
- **R-1185:** Der Hinweis unter „Nicht stören“ (`notifications.dndNote`, `NotificationBell.svelte`) sagt immer
  „Kritisches kommt trotzdem durch“. `allows()` in `stores/dnd.ts` lässt Kritisches aber nur durch, solange
  `criticalPasses()` (`quiet.critical`) gilt; ist der Durchlass aus, hält Nicht stören auch Kritisches zurück.
- **R-1169:** Im abgedockten Terminal-Fenster (`DetachedTerminal.svelte`) zeigt `reportError` den Fehler nirgends:
  die Toasts rendert nur `StatusBar` im `AppShell`, das Fenster hat keine.

## Ziel & Nicht-Ziele
Der Hinweis nennt den Durchlass nur, wenn er gilt; ein Fehler im abgedockten Terminal ist dort sichtbar.
Nicht-Ziel: neue Bedienelemente, neues Verhalten von `allows()`.

## Betroffene Dateien
`NotificationBell.svelte` (+Test), `lib/i18n/dictionaries.ts` (DE+EN, ein Schlüssel `notifications.dndNoteAll`),
`components/terminal/DetachedTerminal.svelte` (+Test, bindet `StatusBar` ein). Kein API-, Datenmodell- oder Migrationsbezug.

## Nicht mitgefahren
R-1159: der erste Teil (Verlauf neu laden nach eingebettetem SSH-Start) ist bereits mit `133a6fc4d` behoben
(`connectFlow.ts:374`, Test `connectFlow.test.ts` „reloads a shown history too“). Der zweite Teil, das Sitzungsende
beim Terminal-Exit, fehlt tatsächlich (`endSession` ruft nur `markRdpExit`), braucht aber eine Zuordnung
Terminal-Key → Sitzung über `terminals.ts` und `connectFlow.ts` und ist keine Klein-Arbeit: Zeile wandert in den
Kern-Zug `kern-terminal-3`.

## Doku-Impact
Keine: Fehlerbehebungen ohne dokumentiertes Verhalten.

## Risiken & Rollback
Gering; je Task ein Commit, einzeln zurücknehmbar. Der Hinweis wird beim Rendern ausgewertet (`prefs` ist kein
Store): ändert sich der Durchlass bei offenem Panel, stimmt er nach dem nächsten Öffnen.

## Offene Fragen
Keine.
