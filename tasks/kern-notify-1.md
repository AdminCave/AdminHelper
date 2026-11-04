<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-notify-1 — Task-Ledger
Status: erledigt · Branch: feature/kern-notify-1 · Review: pro Task
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

### T2 — Live-Toasts und Weiche über Nicht stören (R-1078)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/statusBar.ts, apps/desktop/ui/src/lib/stores/statusBar.test.ts, apps/desktop/ui/src/components/StatusBar.svelte, apps/desktop/ui/src/components/StatusBar.test.ts, apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/components/AppShell.notifications.test.ts, apps/desktop/ui/src/components/StatusFooter.svelte, apps/desktop/ui/src/components/StatusFooter.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @f039e905 2026-11-04T18:06:35+01:00
Review: approve (.ah-out/review/kern-notify-1/T2.verdict.json)
Änderung: `statusBar.ts` bekommt `showNotice({title, body, tone, sticky, onOpen})` neben `showStatus`/`reportError` (unverändert); der Stapel zeigt Ton, Text und „+N weitere“, kritische Toasts bleiben stehen. Die Shell schickt neue Feed-Einträge an Toasts und, falls eingeschaltet, an die OS-Benachrichtigung, beides nur, wenn `dnd.allows(severity)`; der Toast-Klick öffnet `#/notifications` mit dem Eintrag. Die Statusleiste zeigt „Nicht stören bis HH:MM“.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/statusBar.test.ts src/components/StatusBar.test.ts src/components/AppShell.notifications.test.ts src/components/StatusFooter.test.ts
Doku: → T5
Abhängt von: T1

### T3 — Glocke und Panel (R-1078)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/NotificationBell.svelte, apps/desktop/ui/src/components/NotificationBell.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @7b131bd9 2026-11-04T18:15:58+01:00
Review: approve (.ah-out/review/kern-notify-1/T3.verdict.json)
Änderung: Glocke als `IconButton` mit Badge (rot bei ungelesenem Kritischen, `bell-off` bei Nicht stören); Panel nach `notifications.jsx` (NotifPanel): Kopf mit Nicht-stören-`Menu` und Hinweis, `Tabs` Alle/Ungelesen/Offen mit Zählern, Tagesgruppen, Schnellaktion „Als gelesen markieren“, Klick öffnet den Eintrag auf der Center-Seite, leere Zustände, Fuß „Alle gelesen“ und „Alle anzeigen“. Die E2E-Anker `.notif-bell`, `.notif-badge`, `.notif-panel`, `.notif-item`, `.notif-item-title` bleiben. Neuer Test für Tabs, Gruppen, Gelesen und Nicht stören. SPDX im neuen Test.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/NotificationBell.test.ts
Doku: → T5
Abhängt von: T1

### T4 — Center-Seite (R-1078)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/pages/Notifications.svelte, apps/desktop/ui/src/pages/Notifications.test.ts, apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/AppShell.shell.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @2428b5db 2026-11-04T18:27:53+01:00
Review: approve (.ah-out/review/kern-notify-1/T4.verdict.json)
Änderung: Neue Seite `#/notifications` (nur mit Server-Sitzung, nicht in der Sidebar, Eintrag in der Befehlspalette) nach `notifications.jsx` (NotificationsView): Leiste Postfach (Posteingang, Offen, Alle), Schweregrad und Kategorie mit Zählern; Liste mit Suche, Tagesgruppen und Mehrfachauswahl „Als gelesen markieren“; Detail mit Feldern und „Als gelesen markieren“; „Mehr laden“. Leiste und Detail über Container-Queries. Neuer Seitentest. SPDX in den neuen Dateien.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/pages/Notifications.test.ts src/components/AppShell.shell.test.ts
Doku: → T5
Abhängt von: T1

### T5 — Doku DE+EN und Changelog (R-1078)  [x]
Komponente: desktop-ui · Dateien: docs/admin/index.html, docs/en/admin/index.html, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-notify-1.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @23656627 2026-11-04T18:29:40+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Admin-Doku: Glocke, Panel, Live-Toasts, Nicht stören und Center-Seite; Entwickler-Doku: Seite `Notifications`, Store `dnd`, Toast mit Ton; Changelog-Fragment.
Task-Review: am Ende
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/models/notifications.test.ts
Doku: diese Task

### T6 — Abschlussprüfung: Glocken-Doku und Center-Abruf nach Logout (R-1078)  [x]
Komponente: desktop-ui · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/desktop.html, docs/en/developer/desktop.html, apps/desktop/ui/src/lib/stores/notifications.ts, apps/desktop/ui/src/lib/stores/notifications.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @4801455e 2026-11-04T18:57:10+01:00
Review: approve (.ah-out/review/kern-notify-1/T6.verdict.json)
Änderung: Fund der Abschlussprüfung: Admin-Monitoring-Doku DE+EN sagt noch „Öffnen markiert als gelesen“ (seit T1 falsch); Quellbaum der Entwickler-Doku nennt 5 statt 6 Seiten; `loadCenter` füllt nach einem Logout während des Abrufs die geleerte Liste wieder (Generationszähler wie `activateNotifications`), mit Test.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/notifications.test.ts
Doku: diese Task

### T7 — CI-Fund: dynamische Schlüssel der Benachrichtigungen im Tot-Schlüssel-Test (R-1078)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/i18n/i18n.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @002f8b72 2026-11-04T19:13:48+01:00
Review: approve (.ah-out/review/kern-notify-1/T7.verdict.json)
Änderung: PR-CI rot: `i18n.test.ts` „has no unused translation keys“ meldet `notifications.empty.*`, `.day.*`, `.severity.*`, `.mailbox.*` als tot; sie werden per Template-String gebaut (`NotificationBell.svelte`, `pages/Notifications.svelte`). Die vier Präfixe in `DYNAMIC_PREFIXES` mit Fundstelle, wie die übrigen dynamischen Schlüssel.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/i18n/i18n.test.ts src/lib/stores/notifications.test.ts
Doku: keine (Testkonfiguration)

## Entscheidungen
- T1: Nicht stören liegt je Workspace unter `ah.dnd.<workspace-id>`: die Workspace-Prozesse teilen einen localStorage.
- T1: „bis morgen“ endet um 07:00 Ortszeit am nächsten Kalendertag, auch kurz vor Mitternacht.
- T1: Der API-Client bekommt `offset` (der Server kann es schon, router.py:60), damit die Zentrale über 500 Einträge hinaus nachlädt; `api/notifications.ts` samt Test per set-files in T1, Verify erweitert.
- T1: Das Öffnen des Panels markiert nichts mehr gelesen (Spec); der alte Store-Test dazu ist durch den der neuen Regel ersetzt, eine geplante Verhaltensänderung, keine Schwächung.
- T1: Die dnd-Tests prüfen den Ablauf-Timer über das Verhalten, nicht über `vi.getTimerCount()`: jsdom legt je Storage-Event einen Timer an.
- T2: Der Toast-Klick ist ein Knopf „Öffnen“ im Aktionsfeld des Toasts (zugänglich, ohne `Toast.svelte` zu ändern); er öffnet `#/notifications/<id>`, die Seite liest die id in T4.
- T2: Die neue Meldung erscheint immer (Status und Fehler antworten auf eine Aktion, die Spec lässt `showStatus`/`reportError` unverändert). Ein voller Stapel wirft unter den älteren zuerst den ältesten Toast, der von selbst ginge, stehen alle, den ältesten; eine neue Benachrichtigung, die von selbst ginge, wird dann selbst verworfen und gezählt. So verdrängt eine Info-Flut keinen kritischen Toast; „+N weitere“ zählt nur verdrängte Benachrichtigungen (sie bleiben in Glocke und Feed), bis der Stapel leer ist.
- T2: Die Weiche liegt immer an, nicht nur mit OS-Benachrichtigungen; `dictionaries.ts` per set-files dazu (Texte „Öffnen“, „+N weitere“, „Nicht stören bis …“).
- T3: Badge in Akzentfarbe, rot nur bei ungelesenem Kritischen; Kategorie roh (die Kategorien haben keine Übersetzung). Der Schlüssel `notifications.empty` weicht `notifications.empty.<tab>`. Das Menü bietet „Beenden“ nur bei aktivem Nicht stören; der Hinweis trägt es zusätzlich als Knopf.
- T4: Die Seite führt Center-Liste und Feed der Glocke zusammen (die Kopie im Feed ist die frischere), damit ein Eintrag, der nach dem Laden kam und per Toast geöffnet wird, im Detail steht. Die Seitenleiste markiert auf der Seite nichts; Titel „Benachrichtigungen“; Palette-Eintrag nur mit Server-Session. Mehrfachauswahl zählt und sendet nur ungelesene, die der Filter gerade zeigt. „Mehr laden“ steht auch unter leerer Trefferliste; Zeitstempel in der App-Sprache. Das Detail erscheint erst ab 900 px Breite (schmaler: nur die Liste, GUI-Lauf prüft das). `AppShell.shell.test.ts` per set-files dazu.
- T6: `loadCenter` merkt sich einen eigenen Zähler `logoutGen` (nur `deactivateNotifications` erhöht ihn) und verwirft eine Seite, die nach einem Logout ankommt; nicht `activationGen`, weil das `onMount` der Seite nach einem Login vor der Aktivierung in AppShell lädt (Prüfer-Fund). Gegenproben: ohne Wächter und mit `activationGen` je 1 failed. Doku: Satz „Öffnen markiert gelesen“ in admin/monitoring.html DE+EN ersetzt, Seitenzahl in developer/desktop.html auf 6.
- T7: Präfixe in `DYNAMIC_PREFIXES` statt literaler Schlüssel-Maps im Code: so führt der Test schon die übrigen per Template-String gebauten Schlüssel (`monitoring.history.tab.` u. a.). Gegenprobe ist der rote CI-Lauf 41883049700 (11 tote Schlüssel). Lehre: das Task-Verify fuhr nur die Dateien des Zugs, nicht `i18n.test.ts`.
