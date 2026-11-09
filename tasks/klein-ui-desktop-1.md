<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ui-desktop-1 — Desktop-UI: Ruhe-Hinweis, Fehler im abgedockten Terminal (R-1185, R-1169) — Task-Ledger
Status: aktiv · Branch: feature/klein-ui-desktop-1 · Review: am Ende
Spec: docs/features/klein-ui-desktop-1.md (Roadmap R-1185, R-1169)
Heavy: none — reine Desktop-UI ohne Stack-, Gateway- oder Install-Pfad; Komponententests decken das sichtbare Verhalten
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@0fc7e94c5`. R-1159 fährt nicht mit (zweiter Teil kein Klein-Umfang, siehe Spec) und wandert in `tasks/kern-terminal-3.md`.

### T1 — Ruhe-Hinweis nennt den Durchlass nur, wenn er gilt (R-1185)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/NotificationBell.svelte, apps/desktop/ui/src/components/NotificationBell.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @fa0fba4e6 2026-11-09T14:47:42+01:00
Review: am Ende (Branch-Review)
Beweis: review kern-notify-3 2026-11-07, feature/kern-notify-3@b80c1e947, `dictionaries.ts` `notifications.dndNote`; `stores/dnd.ts` `allows()` lässt Kritisches nur bei `criticalPasses()` durch
Dedup-Key: bug:desktop-ui:dictionaries.ts:notifications.dndNote
Änderung: Erst Test rot (Durchlass aus → der Hinweis enthält „Kritisches kommt trotzdem durch“ nicht). Dann neuer Schlüssel `notifications.dndNoteAll` („Ruhe bis {time}.“ / „Quiet until {time}.“) in DE+EN; `NotificationBell.svelte` wählt per `criticalPasses()` zwischen beiden.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/NotificationBell.test.ts
Doku: keine (Fehlerbehebung ohne dokumentiertes Verhalten)

### T2 — Abgedocktes Terminal zeigt Fehler an (R-1169)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/terminal/DetachedTerminal.svelte, apps/desktop/ui/src/components/terminal/DetachedTerminal.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @67d7b85a7 2026-11-09T14:56:52+01:00
Review: am Ende (Branch-Review)
Beweis: review kern-terminal-1 2026-11-06, `DetachedTerminal.svelte`: `reportError` aus `terminals.ts` landet in `statusBar`-Toasts, die nur `AppShell` (`<StatusBar />`) rendert
Dedup-Key: bug:desktop-ui:DetachedTerminal.svelte:report_error
Änderung: Erst Test rot (nach `reportError('x')` zeigt das Fenster den Text). Dann `<StatusBar />` in `DetachedTerminal.svelte` einbinden.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/terminal/DetachedTerminal.test.ts
Doku: keine (Fehlerbehebung ohne dokumentiertes Verhalten)

### T3 — Doku und CHANGELOG-Fragment nachziehen (R-1185, R-1169)  [ ]
Komponente: scripts · Dateien: docs/admin/index.html, docs/en/admin/index.html, changelog.d/klein-ui-desktop-1.md
Änderung: Der Satz zu „Nicht stören“ nennt den Durchlass für Kritisches nur noch, solange „Kritisches trotzdem durchlassen“ an ist (DE+EN, Verweis auf monitoring); CHANGELOG-Fragment `### Fixed` für beide Fehlerbehebungen. Aus der Abschlussprüfung (wichtig, docs/admin/index.html:123, docs/en/admin/index.html:85).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/index.html, docs/en/admin/index.html
Task-Review: am Ende
