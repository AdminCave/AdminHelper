<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-design-2 — Desktop-Shell, Dashboard und Einstellungen nach Mockup

Roadmap: R-1062 (Shell und Dashboard), R-1063 (Einstellungen), beide FEAT, Kevin 2026-11-02. Baut auf R-1061
(kern-design-1, gemergt #373) auf. Vorlage: `AdminCave/DesignSystem@244e890` (`ui_kits/adminhelper/chrome.jsx`,
`dashboard.jsx`, `settings.jsx`). Zeilenangaben `origin/main@594a0af5`, Pfade unter `apps/desktop/ui/src/`.

## Problem / Motivation

- **Shell (R-1062):** `components/AppShell.svelte` hat Sidebar, Header und Inhalt, aber keinen Workspace-Chip im
  Mockup-Stil, keine Befehlspalette und keine Tastenkürzel. Die Header-Suche (`AppShell.svelte:309`) filtert nur die
  Verbindungsliste. Eine Statusleiste mit Hub, Tunnel, Problemen und Zertifikat fehlt. `components/StatusBar.svelte`
  zeigt nur einen einzelnen Toast; eine zweite Meldung ersetzt die erste (`lib/stores/statusBar.ts:31-45`).
- **Dashboard (R-1062):** `pages/Dashboard.svelte` (94 Zeilen) zeigt vier Zähler nach Verbindungsart und die zuletzt
  genutzten Verbindungen. Monitoring-Probleme und Tunnel fehlen, obwohl die Stores sie im Servermodus kennen.
- **Einstellungen (R-1063):** `components/SettingsModal.svelte` (800 Zeilen) ist eine lange Seite mit zwei Gruppen
  (`workspace` ab Zeile 362, `device` ab Zeile 518). Sieben Funktionen teilen sich ein Script. Das Formular wird per
  `$effect` aus dem Store befüllt (`SettingsModal.svelte:88-112`); das ist die Klasse aus R-0715.

## Ziel & Nicht-Ziele

**Ziel**
- **Sidebar und Header:**
  - Sidebar nach Mockup: 232 px offen, 68 px eingeklappt; der aktive Eintrag fett mit 3-px-Balken; Workspace-Chip;
    unten Einstellungen, Workspace wechseln, Theme und Version.
  - Header: Seitentitel, Palette-Knopf mit Kürzel, Glocke, Avatar mit Namen, Abmelden.
  - Die Klassen, an denen die E2E-Journeys hängen, bleiben: `.sidebar-nav`, `.sidebar-item`, `.sidebar-bottom`,
    `.content-header-right .btn.ghost.small`, `.tunnel-indicator`.
- **Toast-Stapel:** `statusBar.ts` wird eine Queue mit höchstens drei sichtbaren Meldungen, gerendert mit
  `ui/Toast`. `showStatus`, `reportError` und `clearStatus` bleiben als API für ihre 47 Aufrufer.
- **Statusleiste (StatusFooter):** zeigt nur, wofür es Daten gibt:
  - Modus und Hub (Lokal, Sync, Server mit Host);
  - Tunnelzustand;
  - Zahl der Probleme (nur Servermodus, aus dem Monitoring-Store);
  - letzter Sync (Sync-Modus);
  - Gerätezertifikat (registriert ja/nein, Ablauf).
- **Befehlspalette:** Strg+K bzw. ⌘K öffnet sie. Sie bietet Verbindungen (Enter verbindet), Seiten (springen) und
  Aktionen (neue Verbindung, Einstellungen, Theme, Workspace wechseln). Pfeiltasten, Enter und Esc; höchstens neun
  Treffer; leerer Zustand „Nichts gefunden“. Die Trefferlogik liegt als reine Funktion in `lib/palette.ts`.
- **Dashboard nach Mockup:**
  - Stat-Karten: Verbindungen gesamt mit SSH/RDP/Web-Aufteilung, Server mit Agent und Probleme (die beiden nur im
    Servermodus).
  - Panel „Zuletzt genutzt“ mit Verbinden-Knopf.
  - Panel Monitoring mit Pills und den Problemservern samt `MonHeartbeatBar`, nur im Servermodus.
  - Panel Tunnel.
  - Knöpfe „Neue Verbindung“ und „Zur Liste“.
- **Einstellungen:**
  - `SettingsModal` wird in Unterkomponenten unter `components/settings/` zerlegt (R-0729, SettingsModal-Teil), ohne
    Verhaltensänderung.
  - Danach eine Sektions-Navigation nach Mockup: Allgemein (Sprache, Design, Passwörter, selbstsignierte
    Zertifikate), Workspace & Sync, RDP, Benachrichtigungen, Gerät.
  - Das Formular wird beim Öffnen einmal im Script initialisiert statt per `$effect` (R-0715 für diesen Dialog).
  - `.sm-panel` und alle `data-action`/`data-msg`-Attribute bleiben; `settings-enroll.live.js` wählt vorher die
    Sektion „Gerät“.

**Nicht-Ziele** (kommen mit ihren eigenen Zeilen)
- Mockup-Elemente ohne Datenquelle im Produkt (siehe offene Frage 1):
  - Statusleiste: „Sitzungen“ und „Nicht stören“;
  - Dashboard: Karte „Aktive Sitzungen“;
  - Einstellungen: Sektion Terminal, „letzte Sitzungen wiederherstellen“, „Zwischenablage teilen“.

  Terminal kommt mit R-1069/R-1070ff, Nicht stören mit R-1078.
- Die Verbindungssuche im Header bleibt, bis kern-verbindungen (R-1065ff) die Liste neu baut.
- Das Benachrichtigungs-Panel hinter der Glocke ist R-1078.
- R-0719 (feste Strings): Die berührten Dateien formatieren schon mit `currentLocale()`
  (`SettingsModal.svelte:149`). Die Fundstellen der Zeile liegen in anderen Dateien, die Zeile bleibt offen.

## Betroffene Komponenten & Dateien

Nur `desktop-ui`, dazu eine E2E-Spec:
- Shell: `components/AppShell.svelte`, `styles/app.css`
- neue Komponenten: `components/ui/Avatar.svelte`, `components/StatusFooter.svelte`,
  `components/CommandPalette.svelte`, `lib/palette.ts`
- `lib/stores/statusBar.ts`, `components/StatusBar.svelte`
- `pages/Dashboard.svelte`
- `components/SettingsModal.svelte`, neu `components/settings/*.svelte`
- `lib/i18n/dictionaries.ts`
- `apps/desktop/e2e/test/specs/settings-enroll.live.js`

## Datenmodell / API / Migrationen

Keine. Kein neuer Tauri-Command und keine neuen `Settings`-Felder (`src-tauri/src/models.rs`, struct `Settings`).
Die Statusleiste und das Dashboard lesen vorhandene Stores: settings, workspace, tunnel, monitoring, connections.

## Externe Integrationen

Keine. Die Tastenkürzel laufen über DOM-`keydown` im Webview, ohne globalen Tauri-Shortcut. Ein globales Kürzel
würde auch außerhalb des Fensters greifen; das ist nicht gewollt.

## Trade-offs & Alternativen

- **Sektionen als Tabs oder als scrollende Seite mit Sprungmarken:** Die scrollende Seite ließe die E2E-Spec
  unverändert, weicht aber vom Mockup ab, das je Sektion eine Seite zeigt. Empfehlung und Wahl: Tabs nach Mockup; die
  Spec klickt die Sektion „Gerät“ an.
- **Erst zerlegen, dann umgliedern (T6 vor T7):** Die bestehenden SettingsModal-Tests beweisen beim Zerlegen
  „Verhalten unverändert“. Die Umgliederung ändert danach nur Anordnung und Navigation. Zwei Commits, beide einzeln
  zurücknehmbar.
- **Toast-Queue statt Toast-Store neu:** Die API bleibt, damit die 47 Aufrufer nicht wandern müssen.

## Risiken & Rollback

- **E2E-Selektoren:** Die Desktop-Journeys hängen an den oben genannten Klassen. Sie bleiben erhalten, und der
  Sammellauf (`Heavy: linux-full`) fährt die GUI-E2E.
- **Kürzel-Konflikte:** Strg+K darf in Eingabefeldern nicht verloren gehen. Die Palette öffnet auch aus einem Feld
  heraus, und Esc gibt den Fokus zurück. Das deckt ein Test ab.
- **Rollback:** Jede Task ist ein eigener Commit und einzeln per `git revert` zurücknehmbar. Es gibt keine
  Datenänderung.

## Doku-Impact

- `docs/index.html` und `docs/en/index.html` nennen Pfade in den Einstellungen („Einstellungen → Diagnose“,
  Browser-Zertifikat). Sie werden auf die Sektionen umgestellt.
- `docs/developer/desktop.html` (DE+EN) beschreibt die Shell (Statusleiste, Palette, Toast-Stapel) und
  `components/settings/`.
- Changelog: `changelog.d/kern-design-2.md`.

## Offene Fragen

1. **Mockup-Elemente ohne Datenquelle:** Sitzungen und Nicht stören in der Statusleiste, Aktive Sitzungen im
   Dashboard, die Terminal-Sektion sowie Wiederherstellen und Zwischenablage in den Einstellungen.
   **Empfehlung:** weglassen. Sie kommen mit ihren Feature-Zeilen (Terminal R-1069/R-1070ff, Nicht stören R-1078).
   Ein Platzhalter ohne Funktion wäre ein sichtbares Versprechen ohne Verhalten. Die Terminal-Sektion aus dem Titel
   von R-1063 übernimmt damit kern-terminal-1.
