<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-design-2 — Task-Ledger
Status: aktiv · Branch: feature/kern-design-2 · Review: pro Task
Spec: docs/features/kern-design-2.md (Roadmap R-1062, R-1063)
Heavy: linux-full — Shell, Einstellungen und Dashboard ändern das DOM der Desktop-Journeys; der Sammellauf fährt die GUI-E2E
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Vorlage `AdminCave/DesignSystem@244e890` (`ui_kits/adminhelper/chrome.jsx`, `dashboard.jsx`, `settings.jsx`). Zeilenangaben `origin/main@594a0af5`. Pfade unter `apps/desktop/ui/`, soweit nicht anders genannt. Bausteine aus `src/components/ui/` (kern-design-1); E2E-tragende Klassen bleiben (Spec, Ziel).

### T1 — Sidebar und Header nach Mockup (R-1062)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/styles/app.css, apps/desktop/ui/src/components/ui/Avatar.svelte, apps/desktop/ui/src/components/ui/Avatar.test.ts, apps/desktop/ui/src/components/AppShell.shell.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @6c801f52 2026-11-02T19:02:21+01:00
Review: approve (.ah-out/review/kern-design-2/T1.verdict.json)
Änderung: Sidebar (`src/components/AppShell.svelte:217-299`) nach Mockup: 232/68 px, aktiver Eintrag mit `aria-current="page"`, fett und 3-px-Balken, Workspace-Chip, Fuß mit Einstellungen, Workspace wechseln, Theme, Version. Header (`AppShell.svelte:301-316`): Titel, Palette-Knopf mit `Kbd` (öffnet in T4; bis dahin ohne Ziel nicht rendern, T4 schaltet ihn ein), Glocke, `ui/Avatar` (Initialen) mit Namen, Abmelden bleibt `btn ghost small`. Die Verbindungssuche bleibt auf der Seite connections. Neue Dateien mit SPDX. Test: aktiver Eintrag, eingeklappte Breite per Klasse, Avatar-Initialen, E2E-Klassen vorhanden.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/AppShell.shell.test.ts src/components/ui/Avatar.test.ts src/components/AppShell.notifications.test.ts src/components/AppShell.workspace.test.ts
Doku: → T8

### T2 — Toast-Stapel statt Einzel-Toast (R-1062)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/statusBar.ts, apps/desktop/ui/src/lib/stores/statusBar.test.ts, apps/desktop/ui/src/components/StatusBar.svelte, apps/desktop/ui/src/components/StatusBar.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @2837cddf 2026-11-02T19:08:52+01:00
Review: approve (.ah-out/review/kern-design-2/T2.verdict.json)
Änderung: `statusBar.ts` führt eine Queue (je Meldung id, Text, Art, eigener Timer 6 s bzw. 10 s), höchstens drei sichtbar, die älteste fällt zuerst; `showStatus`, `reportError`, `clearStatus` bleiben in Signatur und Wirkung für die Aufrufer (`clearStatus` leert alle). `StatusBar.svelte` rendert den Stapel mit `ui/Toast`, jede Meldung einzeln schließbar, `role="status"` bzw. `role="alert"` für Fehler. Tests mit Fake-Timern: zwei Meldungen stehen gleichzeitig, Ablauf je Meldung, Obergrenze, Schließen.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/statusBar.test.ts src/components/StatusBar.test.ts
Doku: → T8

### T3 — Statusleiste mit vorhandenen Daten (R-1062)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/StatusFooter.svelte, apps/desktop/ui/src/components/StatusFooter.test.ts, apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/styles/app.css, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/stores/connections.ts, apps/desktop/ui/src/components/AppShell.shell.test.ts, apps/desktop/ui/src/components/AppShell.workspace.test.ts, apps/desktop/ui/src/components/AppShell.notifications.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @7fc71d26 2026-11-02T19:20:07+01:00
Review: approve (.ah-out/review/kern-design-2/T3.verdict.json)
Änderung: Neue `StatusFooter.svelte` (mono 11 px, SPDX) unter dem Inhalt: Modus und Hub-Host, Tunnelzustand, Probleme (nur Servermodus, Zahl aus dem Monitoring-Store), letzter Sync (nur Sync-Modus), Gerätezertifikat (registriert/nicht registriert, Ablauf). Keine Felder ohne Datenquelle (Spec, Nicht-Ziele). Texte DE+EN in `dictionaries.ts`. Test je Modus: welche Felder erscheinen, welche nicht.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/StatusFooter.test.ts src/components/AppShell.shell.test.ts
Doku: → T8
Abhängt von: T1

### T4 — Befehlspalette mit Strg/⌘+K (R-1062)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/palette.ts, apps/desktop/ui/src/lib/palette.test.ts, apps/desktop/ui/src/components/CommandPalette.svelte, apps/desktop/ui/src/components/CommandPalette.test.ts, apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/styles/app.css, apps/desktop/ui/src/components/AppShell.shell.test.ts, apps/desktop/ui/src/components/AppShell.workspace.test.ts, apps/desktop/ui/src/components/AppShell.notifications.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @e0804ed9 2026-11-02T19:34:36+01:00
Review: approve (.ah-out/review/kern-design-2/T4.verdict.json)
Änderung: `lib/palette.ts` (rein, SPDX): Einträge aus Verbindungen, Seiten (je Modus wie die Sidebar) und Aktionen (neue Verbindung, Einstellungen, Theme, Workspace wechseln), Filter ohne Groß/Klein, höchstens neun Treffer. `CommandPalette.svelte` (SPDX): Overlay, Suchfeld, Pfeiltasten, Enter führt aus (Verbindung → vorhandener Connect-Weg), Esc schließt und gibt den Fokus zurück, „Nichts gefunden“. AppShell: `keydown` Strg+K/⌘K öffnet auch aus Eingabefeldern; der Header-Knopf aus T1 öffnet sie. Tests: Filter und Grenze, Tastatur, Kürzel aus einem Input, Fokus-Rückgabe.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/palette.test.ts src/components/CommandPalette.test.ts src/components/AppShell.shell.test.ts
Doku: → T8
Abhängt von: T1

### T5 — Dashboard nach Mockup (R-1062)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/pages/Dashboard.svelte, apps/desktop/ui/src/pages/Dashboard.load.test.ts, apps/desktop/ui/src/pages/Dashboard.layout.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/styles/app.css
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @0c84f73f 2026-11-02T19:50:24+01:00
Review: approve (.ah-out/review/kern-design-2/T5.verdict.json)
Änderung: Stat-Karten (Verbindungen gesamt mit SSH/RDP/Web, Server mit Agent und Probleme nur im Servermodus), Panel „Zuletzt genutzt“ mit Verbinden-Knopf, Panel Monitoring (Pills nach Zustand, Problemserver mit `MonHeartbeatBar`, nur Servermodus), Panel Tunnel, Knöpfe „Neue Verbindung“ und „Zur Liste“; Bausteine `ui/Panel`, `ui/Pill`, `ui/Button`. Keine Karte „Aktive Sitzungen“ (Spec). Neuer Test: Karten und Panels je Modus, Verbinden ruft den Connect-Weg; `Dashboard.load.test.ts` bleibt grün.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/pages/Dashboard.load.test.ts src/pages/Dashboard.layout.test.ts
Doku: → T8

### T6 — SettingsModal in Unterkomponenten (R-1063, R-0729, R-0715)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/SettingsModal.svelte, apps/desktop/ui/src/components/settings/GeneralSection.svelte, apps/desktop/ui/src/components/settings/WorkspaceSection.svelte, apps/desktop/ui/src/components/settings/RdpSection.svelte, apps/desktop/ui/src/components/settings/NotificationsSection.svelte, apps/desktop/ui/src/components/settings/DeviceSection.svelte, apps/desktop/ui/src/components/SettingsModal.seed.test.ts, apps/desktop/ui/src/components/settings/SettingsDialog.svelte, apps/desktop/ui/src/components/settings/DiagnosticsSection.svelte
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @6555a9b5 2026-11-02T19:56:20+01:00
Review: approve (.ah-out/review/kern-design-2/T6.verdict.json)
Änderung: Die Gruppen aus `SettingsModal.svelte:362-599` wandern mit ihren Funktionen (Enroll, Browser-Zertifikat, Diagnose, PIN- und Geräte-Reset, OS-Benachrichtigungen) in fünf Unterkomponenten (SPDX); das Modal hält Formularzustand und Speichern. Das Befüllen per `$effect` (`SettingsModal.svelte:88-112`) entfällt: der Formularrumpf mountet unter `{#if open}` und initialisiert sich im Script (R-0715). Verhalten, DOM-Attribute und Reihenfolge bleiben; die sechs SettingsModal-Tests beweisen das unverändert. Neuer Test: Tippen in ein Feld wird von einer Store-Änderung nicht zurückgesetzt, erneutes Öffnen setzt zurück. Sieben Dateien, eine Komponente; getrennt von T7, damit „unverändert“ einzeln belegt ist.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/SettingsModal.seed.test.ts src/components/SettingsModal.dialog.test.ts src/components/SettingsModal.enroll.test.ts src/components/SettingsModal.export.test.ts src/components/SettingsModal.identity.test.ts src/components/SettingsModal.save.test.ts src/components/SettingsModal.workspace.test.ts
Doku: keine (Refactor ohne sichtbare Änderung)

### T7 — Einstellungen mit Sektions-Navigation (R-1063)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/SettingsModal.svelte, apps/desktop/ui/src/components/settings/GeneralSection.svelte, apps/desktop/ui/src/components/settings/WorkspaceSection.svelte, apps/desktop/ui/src/components/settings/DeviceSection.svelte, apps/desktop/ui/src/components/SettingsModal.nav.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/e2e/test/specs/settings-enroll.live.js, apps/desktop/ui/src/components/settings/SettingsDialog.svelte
Änderung: Dialog 860 px mit Navigation links (`data-section`): Allgemein (Sprache, Design/Theme, Passwörter, selbstsignierte Zertifikate), Workspace & Sync, RDP, Benachrichtigungen, Gerät (Registrierung, Zertifikat, Browser-Zertifikat, Diagnose, Resets). Start auf Allgemein, Pfeiltasten in der Nav. `.sm-panel` und alle `data-action`/`data-msg` bleiben; die SettingsModal-Tests wählen wo nötig die Sektion. `settings-enroll.live.js` klickt in `openSettings()` die Sektion „Gerät“ (läuft im Sammellauf). Neuer Test: Nav wechselt Sektion, Speichern sammelt über Sektionen.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/SettingsModal.nav.test.ts src/components/SettingsModal.dialog.test.ts src/components/SettingsModal.enroll.test.ts src/components/SettingsModal.export.test.ts src/components/SettingsModal.identity.test.ts src/components/SettingsModal.save.test.ts src/components/SettingsModal.workspace.test.ts src/components/SettingsModal.seed.test.ts
Doku: → T8
Abhängt von: T6

### T8 — Doku DE+EN und Changelog (R-1062, R-1063)  [ ]
Komponente: desktop-ui · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, docs/index.html, docs/en/index.html, changelog.d/kern-design-2.md
Änderung: Entwickler-Doku: Shell (Statusleiste, Palette, Toast-Stapel), `components/settings/`. Nutzer-Doku: Pfade „Einstellungen → Gerät → Diagnose“ und Browser-Zertifikat unter „Gerät“, Strg/⌘+K. Changelog umlautfrei.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/AppShell.shell.test.ts
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- Mockup-Elemente ohne Datenquelle (Sitzungen, Nicht stören, Aktive Sitzungen, Terminal-Sektion, Wiederherstellen, Zwischenablage) baut dieser Zug nicht; sie kommen mit R-1069/R-1070ff und R-1078 (Spec, offene Frage 1, Empfehlung an Kevin am Gate).
- Sektionen als Tabs nach Mockup; die E2E-Spec wählt „Gerät“ (Spec, Trade-offs).
- T3: „Letzter Sync“ hatte keine Quelle; der connections-Store merkt sich die Zeit der letzten erfolgreichen Sync-Antwort (`lastSyncedAt`, nur im Speicher). Probleme zählen aktivierte Checks mit warning/critical aus der letzten Monitoring-Ladung, erst nach der ersten Ladung sichtbar; Gerätezertifikat nur im Servermodus, unlesbar → Feld entfällt.
- T4: Palette-Knopf im Header mit eigener Klasse `header-palette-btn` statt `.btn.ghost.small` (logout/tunnel-start-Specs greifen den ersten solchen Knopf als Abmelden); Aktionen nutzen vorhandene Texte (`connections.new`, `settings.label`, `theme.toggle`, `workspace.openLauncher`); Strg/⌘+K greift auch in Eingabefeldern, ohne Alt.
- T5: Dashboard-Stile scoped in `Dashboard.svelte`; die verwaisten globalen Regeln (`.dash-stats`, `.stat-*`, `.dash-grid`, `.dash-panel*`, `.dash-list*`, `.dash-actions`) aus `app.css` entfernt, `.dash-empty` bleibt (Connections). Monitoring lädt beim Öffnen einmal (`loadServers` → `loadMonitoring`), ohne Polling; `Dashboard.load.test.ts` mockt Monitoring als geladen, damit sein Laden-Text nur die Verbindungen meint.
- T6: Das Gate `{#if $settingsModalOpen}` bleibt in `SettingsModal.svelte` (AppShell und die Tests rendern es dauerhaft), Formularzustand, Speichern und Overlay liegen im neuen `settings/SettingsDialog.svelte`, das bei jedem Oeffnen mountet; gemeinsame Feld-Stile per `:global` unter `.sm-panel`. Diagnose ist eine sechste Sektion (`DiagnosticsSection.svelte`), die Fuenf-Gruppen-Liste der Task hatte sie bei Geraet; T7 ordnet sie dort ein. DeviceSection fragt Registrierung und Identitaet in jedem Modus ab wie zuvor das Modal.
