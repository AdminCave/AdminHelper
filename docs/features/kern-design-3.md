<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-design-3 — Infrastruktur, Ansible und Monitoring nach Mockup

Roadmap: R-1064 (FEAT, Kevin 2026-11-02). Baut auf R-1061 (kern-design-1, Bibliothek `components/ui/`, gemergt #373)
und R-1062/R-1063 (kern-design-2, #374) auf. Vorlage: `AdminCave/DesignSystem@244e890`
(`ui_kits/adminhelper/ops.jsx` für Infrastruktur und Ansible, `monitoring.jsx`). Stand `origin/main@4d1ad071`, Pfade
unter `apps/desktop/ui/src/`.

## Problem / Motivation

Shell, Dashboard, Einstellungen und (mit kern-verbindungen-1) die Verbindungsliste nutzen die neue Bibliothek. Die drei
Betriebsseiten nicht:
- **Infrastruktur:** `pages/Infrastructure.svelte` und `components/infra/ServerDetail.svelte` bauen Liste, Kopf und
  Tab-Leiste aus eigenen Klassen (`.infra-*`, `.srv-*`, `.btn`). Die Tabs unter `components/infra/tabs/` sind eigene
  Tabellen und Knöpfe. Die Übersicht ist eine nackte `<dl>`.
- **Ansible:** `pages/Ansible.svelte` (416 Zeilen, davon 212 CSS) zeigt drei gestapelte Schritte (Playbook, Ziele,
  Ausführen) mit eigenem Markup.
- **Monitoring:** `pages/Monitoring.svelte` hat eine eigene Tab-Leiste (`.mon-tab`). Die Übersicht, das
  Server-Dashboard (`MonServerDashboard.svelte`, eigene `.mon-pill`), die Sektionen unter
  `components/monitoring/section/`, Alerts, Templates und Log nutzen eigene Klassen aus `styles/app.css`.

## Ziel & Nicht-Ziele

**Ziel:** dieselben Funktionen in der Gestalt des Mockups, mit den Bausteinen der Bibliothek (`Tabs`, `Panel`, `Pill`,
`Dot`, `MetaList`, `Segmented`, `Switch`, `SearchField`, `Button`, `EmptyState`, `CodeBlock`, `Tag`).
- **Infrastruktur:**
  - Leiste links (240 px, ab 1000 px Seitenbreite 300 px) mit `SearchField` und „+ Server“; Einträge mit Name, Host und
    Tags.
  - Detail-Kopf mit Icon-Kachel, Name, Host und „Bearbeiten“.
  - Tabs über `ui/Tabs`. Übersicht als `Panel` „Stammdaten“ mit `MetaList` (Host, OS, Tags, Notizen).
  - Verbindungen, Tunnel, Monitoring und Provisionierung in `Panel`s mit Bibliotheksknöpfen. Provisionierung zeigt
    den Befehl in `CodeBlock`.
- **Ansible:** Leiste links mit den Playbooks (Name, Beschreibung, Meta, Hochladen), Detail rechts mit Ziel-Auswahl
  (Server oder Tags, wie heute) und „Ausführen“.
- **Monitoring:**
  - Tabs über `ui/Tabs` mit Zähler bei Alerts und Templates (aus dem Store).
  - Übersicht: Banner „Server ohne Checks“, Summary-Karten, `Segmented` Liste/Kacheln, Liste als Leiste (210 px, ab
    960 px 280 px) plus Server-Dashboard.
  - Dashboard-Kopf mit `Dot`, `Pill`s und Knöpfen. Die Sektionen behalten Inhalt und Aufklappen, bekommen aber den
    Panel-Rahmen des Mockups.
  - Alerts, Templates und Log als `Panel`-Listen bzw. Karten-Grid.
- **`ui/Tabs`** bekommt je Tab ein `data-tab={id}`. Das ist der stabile Anker für die E2E-Specs und die Unit-Tests.
- Die Desktop-E2E-Specs (`server-crud`, `provisioning`, `monitoring-alerts`, `monitoring-check`) und `lib/live.js`
  folgen den neuen Ankern.

**Nicht-Ziele** (ohne Datenquelle auf der Seite oder neue Funktion; siehe offene Frage 1):
- Infrastruktur: Status-`Dot`/`Pill` je Server und im Kopf, Panel „Jetzt“ (Live-Werte), SSH/RDP-Schnellknöpfe im
  Kopf, Zähler an den Tabs Verbindungen und Tunnel. Die Seite lädt heute keine Monitoring-Daten für alle Server.
- Ansible: Schalter „Probelauf (--check)“ und das Ausgabefeld. Beides gibt es heute nicht; die Live-Ausgabe ist
  R-1073.
- Monitoring: „Auto-Refresh 30 s“ als Schalter. Der Store aktualisiert schon alle 30 s
  (`lib/stores/monitoring.ts`, `REFRESH_INTERVAL_MS`); die Übersicht zeigt das als Hinweis, ohne Abschalter.
- Monitoring-Modals (Check, Alert-Regel, Wartung, Template, Builtin-Update) bleiben unverändert; sie nutzen schon
  `ui/Modal`.

## Betroffene Komponenten & Dateien

Nur `desktop-ui` und `desktop-e2e`:
- `components/ui/Tabs.svelte` (+ Test)
- `pages/Infrastructure.svelte`, `components/infra/ServerDetail.svelte`, `components/infra/tabs/*.svelte`
- `pages/Ansible.svelte`
- `pages/Monitoring.svelte`, `components/monitoring/MonitoringOverview.svelte`, `MonSummaryCards`, `MonServerList*`,
  `MonServerGrid`, `MonServerDashboard`, `section/*`, `MonitoringAlerts`, `MonitoringTemplates`, `MonitoringLog`
- `styles/app.css` (alte `.infra-*`, `.srv-*`, `.ansible-*`, `.mon-*`-Regeln, soweit verwaist)
- `lib/i18n/dictionaries.ts`
- `apps/desktop/e2e/test/specs/{server-crud,provisioning,monitoring-alerts,monitoring-check}.live.js`,
  `apps/desktop/e2e/test/lib/live.js`

## Datenmodell / API / Migrationen

Keine. Kein Tauri-Command, kein Store-Feld, keine Server-API. Die Seiten lesen die vorhandenen Stores (`infra`,
`ansible`, `monitoring`).

## Externe Integrationen

Keine.

## Trade-offs & Alternativen

- **E2E-Anker:** Alte Klassen (`.btn.primary`, `.srv-tab`) an Bibliotheksknöpfe zu hängen, mischte zwei
  Stilsysteme. Gewählt: stabile Anker (`data-tab`, `data-action`, bestehende Namensklassen wie `.srv-item-name`,
  `.mon-row .mon-name`, `.mon-alert-name`, `.tpl-suggest`, `.prov-table`, `.cmd-box`) bleiben bzw. kommen dazu, die
  Specs wählen die Knöpfe über `data-action`. Wie in kern-verbindungen-1 T8.
- **Ellipsierte Namen:** `waitForRow` liest mit `getText()`, das bei `text-overflow: ellipsis` leer liefert. Die
  betroffenen Specs warten über `textContentOf` (wie `connection-editor.live.js` in kern-verbindungen-1).
- **Schnitt je Seite statt je Baustein:** Jede Task stellt eine Seite oder einen Seitenteil um und ist einzeln
  zurücknehmbar; die Unit-Tests der Seite beweisen das unveränderte Verhalten.

## Risiken & Rollback

- **E2E-Selektoren:** Der Sammellauf (`Heavy: linux-full`) fährt die GUI-E2E; lokal nur Lint der Specs.
- **Verwaiste CSS-Regeln:** Jede Task entfernt nur die Regeln ihrer Seite, die nach `grep` keinen Nutzer mehr haben.
- **Überlappung:** `dictionaries.ts` und `e2e/test/lib/live.js` ändert auch kern-verbindungen-1; gebaut wird nach
  dessen Merge.
- **Rollback:** je Task `git revert`, keine Datenänderung.

## Doku-Impact

- `docs/admin/index.html` und EN: falls Wege („Infrastruktur → Server → Provisionierung“, Monitoring-Tabs) sich in
  der Benennung ändern; sonst keine Änderung der Bedienwege.
- `docs/developer/desktop.html` (DE+EN): Zeilen zu Infrastruktur, Ansible und Monitoring (Aufbau, Bibliothek).
- Changelog: `changelog.d/kern-design-3.md`.

## Offene Fragen

1. **Mockup-Elemente ohne Datenquelle oder Funktion** (Status je Server und „Jetzt“ auf der Infrastruktur-Seite,
   SSH/RDP-Schnellknöpfe, Tab-Zähler, Ansible-Probelauf und Ausgabefeld). **Empfehlung:** weglassen, wie in
   kern-design-2. Die Zeile sagt „ohne neue Funktion“; Probelauf und Live-Ausgabe kämen als eigene Zeilen (Ausgabe:
   R-1073), Status auf der Infrastruktur-Seite als eigene FEAT-Zeile, wenn gewünscht.
