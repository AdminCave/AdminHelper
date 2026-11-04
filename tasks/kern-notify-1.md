<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-notify-1 — Task-Ledger
Status: aktiv · Branch: feature/kern-notify-1 · Review: pro Task
Spec: docs/features/kern-notify-1.md (Roadmap R-1078)
Heavy: linux-full — Glocke und Panel gehören zur Desktop-Journey notification-push; der Sammellauf fährt die GUI-E2E
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Vorlage `AdminCave/DesignSystem@244e890` (`ui_kits/adminhelper/notifications.jsx`, `chrome.jsx`). Stand `origin/main@4d1ad071`. Pfade unter `apps/desktop/ui/`, soweit nicht anders genannt. Gebaut wird nach dem Merge von kern-verbindungen-1 und nach kern-design-3 (gemeinsam: `AppShell.svelte`, `dictionaries.ts`).

### T1 — Modell, Feed-Store und Nicht stören (R-1078)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/models/notifications.ts, apps/desktop/ui/src/lib/models/notifications.test.ts, apps/desktop/ui/src/lib/stores/notifications.ts, apps/desktop/ui/src/lib/stores/notifications.test.ts, apps/desktop/ui/src/lib/stores/dnd.ts, apps/desktop/ui/src/lib/stores/dnd.test.ts, apps/desktop/ui/src/lib/api/notifications.ts, apps/desktop/ui/src/lib/api/notifications.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @ed1919c9 2026-11-04T17:50:19+01:00
Review: approve (.ah-out/review/kern-notify-1/T1.verdict.json)
Änderung: Neues Modul `lib/models/notifications.ts` mit `isOpen` (ungelesen und warning/critical), `dayBucket` (Heute/Gestern/Älter, Ortszeit) und Filtern (Postfach, Schweregrad, Kategorie, Suche). Der Feed-Store markiert beim Öffnen des Panels nichts mehr, bekommt `markRead(ids)` und ein Center-Laden mit `limit`/`offset`. Neuer Store `dnd.ts`: Nicht stören bis zu einem Zeitpunkt (1 Std., 4 Std., morgen 07:00), in `localStorage` je Workspace, Ablauf ohne Timer-Leck, `allows(severity)`. SPDX in den neuen Dateien.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/models/notifications.test.ts src/lib/stores/notifications.test.ts src/lib/stores/dnd.test.ts src/lib/api/notifications.test.ts
Doku: → T5

### T2 — Live-Toasts und Weiche über Nicht stören (R-1078)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/statusBar.ts, apps/desktop/ui/src/lib/stores/statusBar.test.ts, apps/desktop/ui/src/components/StatusBar.svelte, apps/desktop/ui/src/components/StatusBar.test.ts, apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/components/AppShell.notifications.test.ts, apps/desktop/ui/src/components/StatusFooter.svelte, apps/desktop/ui/src/components/StatusFooter.test.ts
Änderung: `statusBar.ts` bekommt `showNotice({title, body, tone, sticky, onOpen})` neben `showStatus`/`reportError` (unverändert); der Stapel zeigt Ton, Text und „+N weitere“, kritische Toasts bleiben stehen. Die Shell schickt neue Feed-Einträge an Toasts und, falls eingeschaltet, an die OS-Benachrichtigung, beides nur, wenn `dnd.allows(severity)`; der Toast-Klick öffnet `#/notifications` mit dem Eintrag. Die Statusleiste zeigt „Nicht stören bis HH:MM“.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/statusBar.test.ts src/components/StatusBar.test.ts src/components/AppShell.notifications.test.ts src/components/StatusFooter.test.ts
Doku: → T5
Abhängt von: T1

### T3 — Glocke und Panel (R-1078)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/NotificationBell.svelte, apps/desktop/ui/src/components/NotificationBell.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Glocke als `IconButton` mit Badge (rot bei ungelesenem Kritischen, `bell-off` bei Nicht stören); Panel nach `notifications.jsx` (NotifPanel): Kopf mit Nicht-stören-`Menu` und Hinweis, `Tabs` Alle/Ungelesen/Offen mit Zählern, Tagesgruppen, Schnellaktion „Als gelesen markieren“, Klick öffnet den Eintrag auf der Center-Seite, leere Zustände, Fuß „Alle gelesen“ und „Alle anzeigen“. Die E2E-Anker `.notif-bell`, `.notif-badge`, `.notif-panel`, `.notif-item`, `.notif-item-title` bleiben. Neuer Test für Tabs, Gruppen, Gelesen und Nicht stören. SPDX im neuen Test.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/NotificationBell.test.ts
Doku: → T5
Abhängt von: T1

### T4 — Center-Seite (R-1078)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/pages/Notifications.svelte, apps/desktop/ui/src/pages/Notifications.test.ts, apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Neue Seite `#/notifications` (nur mit Server-Sitzung, nicht in der Sidebar, Eintrag in der Befehlspalette) nach `notifications.jsx` (NotificationsView): Leiste Postfach (Posteingang, Offen, Alle), Schweregrad und Kategorie mit Zählern; Liste mit Suche, Tagesgruppen und Mehrfachauswahl „Als gelesen markieren“; Detail mit Feldern und „Als gelesen markieren“; „Mehr laden“. Leiste und Detail über Container-Queries. Neuer Seitentest. SPDX in den neuen Dateien.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/pages/Notifications.test.ts src/components/AppShell.shell.test.ts
Doku: → T5
Abhängt von: T1

### T5 — Doku DE+EN und Changelog (R-1078)  [ ]
Komponente: desktop-ui · Dateien: docs/admin/index.html, docs/en/admin/index.html, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-notify-1.md
Änderung: Admin-Doku: Glocke, Panel, Live-Toasts, Nicht stören und Center-Seite; Entwickler-Doku: Seite `Notifications`, Store `dnd`, Toast mit Ton; Changelog-Fragment.
Task-Review: am Ende
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/models/notifications.test.ts
Doku: diese Task

## Entscheidungen
- T1: Nicht stören liegt je Workspace unter `ah.dnd.<workspace-id>`: die Workspace-Prozesse teilen einen localStorage.
- T1: „bis morgen“ endet um 07:00 Ortszeit am nächsten Kalendertag, auch kurz vor Mitternacht.
- T1: Der API-Client bekommt `offset` (der Server kann es schon, router.py:60), damit die Zentrale über 500 Einträge hinaus nachlädt; `api/notifications.ts` samt Test per set-files in T1, Verify erweitert.
- T1: Das Öffnen des Panels markiert nichts mehr gelesen (Spec); der alte Store-Test dazu ist durch den der neuen Regel ersetzt, eine geplante Verhaltensänderung, keine Schwächung.
- T1: Die dnd-Tests prüfen den Ablauf-Timer über das Verhalten, nicht über `vi.getTimerCount()`: jsdom legt je Storage-Event einen Timer an.
