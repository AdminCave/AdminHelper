<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-notify-1 — Benachrichtigungs-Oberfläche nach Mockup

Roadmap: R-1078 (FEAT, Kevin 2026-11-02). Baut auf R-1062 (kern-design-2, #374: Shell, Toast-Stapel, Statusleiste)
auf. Vorlage: `AdminCave/DesignSystem@244e890` (`ui_kits/adminhelper/notifications.jsx`, `chrome.jsx`). Stand
`origin/main@4d1ad071`, Pfade unter `apps/desktop/ui/src/`, soweit nicht anders genannt.

## Problem / Motivation

- **Glocke:** `components/NotificationBell.svelte` zeigt ein schlichtes Panel mit allen Einträgen und eigenen Klassen.
  Schon das Öffnen markiert alles als gelesen (`lib/stores/notifications.ts:86-89`). Es gibt keine Filter, keine
  Gruppen nach Tagen und keinen Weg zu einer Gesamtansicht.
- **Live:** Neue Einträge erscheinen nur als Badge und, falls eingeschaltet, als OS-Benachrichtigung
  (`AppShell.svelte:178`). Einen Toast in der App gibt es nicht.
- **Nicht stören:** gibt es nicht; kern-design-2 hat es aus der Statusleiste auf R-1078 verschoben.
- **Center-Seite:** gibt es nicht. Ältere Einträge als die 50 der Glocke sind in der App nicht zu sehen.

## Ziel & Nicht-Ziele

**Ziel:** Glocke, Panel, Live-Toasts, Nicht stören und eine Center-Seite in der Gestalt des Mockups. Grundlage sind
nur die vorhandenen Daten des Feeds (`severity` info/warning/critical, `category`, `title`, `body`, `sourceType`,
`sourceId`, `createdAt`, `read`) und die vorhandene API (`GET /api/notifications` mit `limit` ≤ 1000 und `offset`,
`unread-count`, `POST /api/notifications/read` mit `ids`).
- **Glocke:** `IconButton` mit Badge; rot, solange ein ungelesener kritischer Eintrag da ist. Bei aktivem
  Nicht stören zeigt sie das Symbol `bell-off`.
- **Panel:**
  - Kopf mit Titel und Menü „Nicht stören“; bei aktivem Nicht stören ein Hinweis „Ruhe bis HH:MM. Kritisches kommt
    trotzdem durch.“ mit „Beenden“.
  - Tabs **Alle / Ungelesen / Offen** mit Zählern. **Offen** heißt auf den heutigen Daten: ungelesen und Schweregrad
    Warnung oder Kritisch. Den Vorfall-Zustand bringt erst R-1079.
  - Einträge gruppiert nach **Heute / Gestern / Älter**, mit Schweregrad, Kategorie und Zeit. Schnellaktion
    „Als gelesen markieren“; ein Klick öffnet den Eintrag auf der Center-Seite und markiert ihn als gelesen.
  - Leere Zustände nach Tab; Fuß mit „Alle gelesen“ und „Alle anzeigen“ (Center-Seite).
  - Das Öffnen des Panels markiert nichts mehr als gelesen; sonst wäre „Ungelesen“ immer leer.
- **Live-Toasts:** Neue Einträge (dieselbe Erkennung wie heute für OS-Benachrichtigungen, ohne den Rückstand beim
  ersten Laden) erscheinen im vorhandenen Toast-Stapel mit Titel, Text und Ton nach Schweregrad.
  - Kritische Toasts bleiben stehen, bis man sie schließt; die übrigen gehen nach der heutigen Zeit.
  - Mehr als drei: „+N weitere“.
  - Ein Klick öffnet den Eintrag auf der Center-Seite.
- **Nicht stören:**
  - Dauer 1 Std., 4 Std. oder bis morgen 07:00 (Ortszeit), beenden jederzeit.
  - Gilt für die Toasts und die OS-Benachrichtigungen dieses Workspace-Fensters. Kritisches kommt immer durch.
    Feed, Badge und Center-Seite bleiben unverändert.
  - Gespeichert lokal je Workspace (`localStorage`, wie Theme und Monitoring-Ansicht), übersteht also einen
    Neustart bis zum Ablauf.
  - Die Statusleiste zeigt „Nicht stören bis HH:MM“.
- **Center-Seite** (`#/notifications`, nur mit Server-Sitzung):
  - Keine Sidebar-Seite. Erreichbar über „Alle anzeigen“, Toast-Klick und die Befehlspalette.
  - Leiste mit **Postfach** (Posteingang = ungelesen oder offen; Offen; Alle), **Schweregrad** und **Kategorie**
    (die Kategorien, die im Feed vorkommen), je mit Zähler.
  - Liste mit Suche (Titel, Text) und Tagesgruppen; Mehrfachauswahl mit „Als gelesen markieren“.
  - Detail mit Titel, Text, Schweregrad, Kategorie, Quelle (`sourceType`/`sourceId` als Text), Zeit und
    „Als gelesen markieren“.
  - Lädt bis zu 500 Einträge, dazu „Mehr laden“ (`offset`).
  - Leiste und Detail blenden sich wie in kern-verbindungen-1 über Container-Queries ein.

**Nicht-Ziele** (ohne Datenquelle oder mit eigener Zeile; offene Frage 1):
- Bestätigen, Behoben, Wieder öffnen, Stummschalten je Eintrag, Ausblenden, Notizen, Bündeln (×n), Zeitleiste,
  Postfächer Bestätigt/Behoben/Stumm, Kategorien des Mockups ohne Daten: alles **R-1079** (Arch-Session).
- „Als ungelesen markieren“: Die API kennt nur „gelesen“; ein Rückweg wäre eine API-Änderung. Kommt mit R-1079.
- Kanäle, Matrix Schweregrad × Kanal und Test-Knopf: R-1080. Ruhezeiten, Eskalation, Zusammenfassung und Ton:
  R-1081.
- Schnellknöpfe zum Server (Öffnen, Verbinden) im Detail: Die Infrastruktur-Seite hat keinen Deep-Link.
- Kein Server-, Monitoring- oder Agent-Code. Keine API- oder Tauri-Änderung.

## Betroffene Komponenten & Dateien

Nur `desktop-ui` und eine Desktop-E2E-Spec:
- `lib/stores/notifications.ts` (+ Test): kein Gelesen beim Öffnen, `markRead(ids)`, Center-Laden mit `offset`.
- `lib/models/notifications.ts` (neu, + Test): Tagesgruppen, „offen“, Filter.
- `lib/stores/dnd.ts` (neu, + Test): Nicht stören.
- `lib/stores/statusBar.ts`, `components/StatusBar.svelte` (+ Tests): Toasts mit Ton, Text, stehend und Klick.
- `components/AppShell.svelte` (+ `AppShell.notifications.test.ts`): Weiche Feed → Toast/OS mit Nicht stören, Route
  und Palette-Eintrag.
- `components/NotificationBell.svelte` (+ neuer Test), `components/StatusFooter.svelte` (+ Test).
- `pages/Notifications.svelte` (neu, + Test).
- `lib/i18n/dictionaries.ts`.
- `apps/desktop/e2e/test/specs/notification-push.live.js`, falls sich Anker ändern. Die Anker `.notif-bell`,
  `.notif-badge`, `.notif-panel`, `.notif-item` und `.notif-item-title` bleiben.

## Datenmodell / API / Migrationen

Keine. Der Feed liefert alle nötigen Felder; „Offen“ wird im Client abgeleitet.

## Externe Integrationen

Keine. Die OS-Benachrichtigung (`@tauri-apps/plugin-notification`) bleibt, wie sie ist; nur ihr Aufruf wird durch
Nicht stören gefiltert.

## Trade-offs & Alternativen

- **„Offen“ ohne Vorfall-Zustand:** Weglassen wäre ehrlicher, nähme dem Panel aber die Sicht auf das Wichtige. Die
  gewählte Ableitung (ungelesen und Warnung/Kritisch) ersetzt R-1079 später durch den echten Zustand; die Tabs
  bleiben dieselben.
- **Nicht stören lokal statt auf dem Server:** Für den Server wäre eine API nötig, und er kennt keine Toasts. Lokal je
  Workspace passt zur Desktop-Wirkung. Ruhezeiten mit Serverwirkung (E-Mail) sind R-1081.
- **Toasts im vorhandenen Stapel:** Ein zweiter Stapel konkurrierte um dieselbe Ecke. `statusBar.ts` bekommt einen
  Eintrag mit Ton, Text, Dauer und Ziel. `showStatus` und `reportError` bleiben für ihre Aufrufer, wie sie sind.
- **Gelesen beim Öffnen fällt weg:** Das ist eine sichtbare Änderung. Die Zeile verlangt aber „Ungelesen“, und das
  Mockup markiert erst beim Öffnen eines Eintrags. „Alle gelesen“ bleibt ein Klick.

## Risiken & Rollback

- **E2E:** `notification-push.live.js` klickt Glocke und Panel. Die Anker bleiben; der Sammellauf
  (`Heavy: linux-full`) beweist das.
- **Toast-Flut:** Viele neue Einträge auf einmal ergeben höchstens drei Toasts plus „+N weitere“. Die OS-Seite behält
  ihre Sammelmeldung ab drei.
- **Rollback:** je Task `git revert`, keine Datenänderung. Den Nicht-stören-Schlüssel in `localStorage` ignoriert ein
  älterer Stand.

## Doku-Impact

- `docs/admin/index.html` (DE+EN): Abschnitt Desktop um Glocke, Panel, Nicht stören und Center-Seite ergänzen.
- `docs/developer/desktop.html` (DE+EN): Seiten-Tabelle (`Notifications`), Stores (`dnd`, Toast mit Ton).
- Changelog: `changelog.d/kern-notify-1.md`.

## Offene Fragen

1. **Mockup-Elemente ohne Datenquelle** (Bestätigen/Behoben/Stumm, Ausblenden, Als ungelesen, Zeitleiste, Bündeln,
   Server-Schnellknöpfe). **Empfehlung:** weglassen und mit R-1079 bringen, wie in kern-design-2/-3. Die Zeile sagt
   „auf den vorhandenen Daten“, und R-1079 ist als Arch-Session nach R-1078 geplant.
2. **„Offen“ als „ungelesen und Warnung/Kritisch“** bis R-1079. **Empfehlung:** so; die Alternative wäre, den Tab
   erst mit R-1079 zu zeigen.
