<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-design-3 — Task-Ledger
Status: aktiv · Branch: feature/kern-design-3 · Review: pro Task
Spec: docs/features/kern-design-3.md (Roadmap R-1064, R-1089)
Heavy: linux-full — Infrastruktur, Ansible und Monitoring ändern das DOM der Desktop-Journeys (server-crud, provisioning, monitoring-*); der Sammellauf fährt die GUI-E2E
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Vorlage `AdminCave/DesignSystem@244e890` (`ui_kits/adminhelper/ops.jsx`, `monitoring.jsx`). Stand `origin/main@4d1ad071`. Pfade unter `apps/desktop/ui/`, soweit nicht anders genannt. Bausteine aus `src/components/ui/`; ohne neue Funktion (Spec, Nicht-Ziele). Gebaut wird nach dem Merge von kern-verbindungen-1 (gemeinsam: `dictionaries.ts`, `e2e/test/lib/live.js`).

### T1 — Infrastruktur: Leiste, Detail-Kopf, Tabs und Übersicht (R-1064)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/ui/Tabs.svelte, apps/desktop/ui/src/components/ui/Tabs.test.ts, apps/desktop/ui/src/pages/Infrastructure.svelte, apps/desktop/ui/src/components/infra/ServerDetail.svelte, apps/desktop/ui/src/pages/Infrastructure.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/styles/app.css
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @e6890a74 2026-11-04T15:26:53+01:00
Review: approve (.ah-out/review/kern-design-3/T1.verdict.json)
Änderung: `ui/Tabs` setzt je Tab `data-tab={id}`. Infrastruktur nach `ops.jsx` (InfraView): Leiste mit `SearchField` und „+ Server“ (`data-action="server-new"`), Einträge mit Name, Host und Tags (`.srv-item`, `.srv-item-name` bleiben); Detail-Kopf mit Icon-Kachel, Name, Host und „Bearbeiten“ (`data-action="server-edit"`); Tabs über `ui/Tabs` (`.srv-tab`-Anker entfällt, `data-tab` bleibt); Übersicht als `Panel` mit `MetaList`. Neuer Test für Suche, Auswahl, Tab-Wechsel und Kopf-Aktionen; verwaiste `.infra-*`/`.srv-*`-Regeln raus. SPDX im neuen Test.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ui/Tabs.test.ts src/pages/Infrastructure.test.ts src/lib/i18n/i18n.test.ts
Doku: → T8

### T2 — Infrastruktur-Tabs Verbindungen, Tunnel, Monitoring, Provisionierung (R-1064)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/tabs/ConnectionsTab.svelte, apps/desktop/ui/src/components/infra/tabs/TunnelsTab.svelte, apps/desktop/ui/src/components/infra/tabs/MonitoringTab.svelte, apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.svelte, apps/desktop/ui/src/components/infra/tabs/MonitoringTab.test.ts, apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @5eb534ea 2026-11-04T15:37:41+01:00
Review: approve (.ah-out/review/kern-design-3/T2.verdict.json)
Änderung: Die vier Tabs als `Panel`s mit Bibliotheksknöpfen (`Button`, `Pill`, `Switch` wo heute ein Umschalter ist), Provisionierung mit `CodeBlock`. E2E-Anker bleiben: `.prov`, `.cmd-box`, `.prov-table`, `.mon-row .mon-name`, `.tpl-suggest`; Knöpfe, die eine Spec drückt, tragen `data-action` (`prov-mint`, `check-new`, `tpl-assign`). Tests ziehen auf die Anker nach.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra/tabs/MonitoringTab.test.ts src/components/infra/tabs/ProvisioningTab.test.ts src/lib/i18n/i18n.test.ts
Doku: → T8
Abhängt von: T1

### T3 — Ansible: Playbook-Leiste und Detail (R-1064)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/pages/Ansible.svelte, apps/desktop/ui/src/pages/Ansible.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/styles/app.css
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @92d11ad2 2026-11-04T15:48:26+01:00
Review: approve (.ah-out/review/kern-design-3/T3.verdict.json)
Änderung: Nach `ops.jsx` (AnsibleView): Leiste mit Playbooks (Name, Beschreibung, Meta, „Hochladen“), Detail mit Ziel-Auswahl (Server oder Tags wie heute) und „Ausführen“; kein Probelauf, kein Ausgabefeld (Spec, Nicht-Ziele). Neuer Seitentest für Auswahl, Zielmodus und Ausführen-Sperre gegen den Store. SPDX im neuen Test.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/pages/Ansible.test.ts src/lib/stores/ansible.test.ts src/lib/stores/ansible.pipeline.test.ts src/lib/i18n/i18n.test.ts
Doku: → T8

### T4 — Monitoring: Tabs und Übersicht (R-1064)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/pages/Monitoring.svelte, apps/desktop/ui/src/components/monitoring/MonitoringOverview.svelte, apps/desktop/ui/src/components/monitoring/MonSummaryCards.svelte, apps/desktop/ui/src/components/monitoring/MonServerList.svelte, apps/desktop/ui/src/components/monitoring/MonServerListItem.svelte, apps/desktop/ui/src/components/monitoring/MonServerGrid.svelte, apps/desktop/ui/src/components/monitoring/MonitoringOverview.test.ts, apps/desktop/ui/src/components/monitoring/MonServerGrid.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/styles/app.css
Änderung: Tabs über `ui/Tabs` (Zähler Alerts und Templates aus dem Store, `.mon-tabs` als Wrapper bleibt), Übersicht nach `monitoring.jsx`: Banner „Server ohne Checks“, Summary-Karten, `Segmented` Liste/Kacheln statt `.mon-view-toggle`, Hinweis „Auto-Refresh 30 s“, Liste als Leiste mit `Dot`, Kacheln mit `MonHeartbeatBar`. Zehn Dateien, weil Übersicht, Liste und Kacheln ein Layout teilen.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/MonitoringOverview.test.ts src/components/monitoring/MonServerGrid.test.ts
Doku: → T8

### T5 — Monitoring: Server-Dashboard und Sektionen (R-1064)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/MonServerDashboard.svelte, apps/desktop/ui/src/components/monitoring/section/MonSectionHeader.svelte, apps/desktop/ui/src/components/monitoring/section/SecLive.svelte, apps/desktop/ui/src/components/monitoring/MonServerDashboard.test.ts, apps/desktop/ui/src/styles/app.css
Änderung: Dashboard-Kopf mit `Dot`, `Pill`s statt `.mon-pill`, `Button`s (SSH, Wartung, „+ Check“ mit `data-action="check-new"`) und Heartbeat; die Sektionen bekommen über `MonSectionHeader` und einen gemeinsamen Rahmen die Panel-Gestalt, Inhalt und Aufklappen bleiben. Die bestehenden `Sec*`-Tests müssen grün bleiben; neuer Dashboard-Test für Kopf und Pills. SPDX im neuen Test.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/MonServerDashboard.test.ts src/components/monitoring/section
Doku: → T8
Abhängt von: T4

### T6 — Monitoring: Alerts, Templates und Log (R-1064)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/MonitoringAlerts.svelte, apps/desktop/ui/src/components/monitoring/MonitoringTemplates.svelte, apps/desktop/ui/src/components/monitoring/MonitoringLog.svelte, apps/desktop/ui/src/components/monitoring/MonitoringAlerts.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/styles/app.css
Änderung: Alerts und Log als `Panel`-Listen (Alerts mit `Switch`, „+ Alert“ mit `data-action="alert-new"`, `.mon-alert-name` bleibt), Templates als Karten-Grid. Neuer Test für Alerts (Liste, Umschalten, Neu). SPDX im neuen Test.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/MonitoringAlerts.test.ts
Doku: → T8

### T7 — Desktop-E2E auf die neuen Anker (R-1064)  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/server-crud.live.js, apps/desktop/e2e/test/specs/provisioning.live.js, apps/desktop/e2e/test/specs/monitoring-alerts.live.js, apps/desktop/e2e/test/specs/monitoring-check.live.js, apps/desktop/e2e/test/lib/live.js, apps/desktop/e2e/test/specs/connection-crud.live.js, apps/desktop/e2e/test/specs/tunnel-crud.live.js, apps/desktop/e2e/test/specs/tunnel-create.live.js, apps/desktop/e2e/test/specs/tunnel-start.live.js
Änderung: Die vier Specs und `openServerTab` in `lib/live.js` wählen über `data-tab`/`data-action` statt `.btn.primary`/`.srv-tab`/`.srv-head .btn.small` und warten auf Namen über `textContentOf`. Lokal nur Lint; der Beweis ist der Sammellauf (Heavy).
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Testcode)
Abhängt von: T1, T2, T4, T5, T6

### T9 — Undefinierte Tokens: NotificationBell und Wächtertest (R-1089)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/NotificationBell.svelte, apps/desktop/ui/src/styles/tokens.test.ts
Änderung: `NotificationBell` nutzt definierte Tokens (`--radius-*`, `--surface-hover` statt `--radius`, `--bg-hover`); `tokens.test.ts` prüft, dass jedes `var(--x)` unter `src/` einen Token trifft, den `app.css`, `global.css` oder eine Komponente selbst deklariert (sonst fällt `var()` still auf den Browser-Default). Die Ansible-Fälle (`--bg-elev`, `--bg-accent`) räumt T3 ab; T9 läuft nach T3, damit der Wächter grün startet.
Beweis: grep var(--bg-elev apps/desktop/ui/src/pages/Ansible.svelte (main@1c313156) · Dedup-Key: bug:desktop-ui:Ansible.svelte:undefined-tokens
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/styles/tokens.test.ts
Doku: keine (interne Styles, kein dokumentiertes Verhalten)
Abhängt von: T3

### T8 — Doku DE+EN und Changelog (R-1064)  [ ]
Komponente: desktop-ui · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, docs/admin/index.html, docs/en/admin/index.html, changelog.d/kern-design-3.md
Änderung: Entwickler-Doku zu Aufbau von Infrastruktur, Ansible und Monitoring (Bibliothek, `data-tab`/`data-action`-Anker); Admin-Doku nur, wo sich sichtbare Namen der Wege ändern; Changelog-Fragment.
Task-Review: am Ende
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ui/Tabs.test.ts
Doku: diese Task

## Entscheidungen
- 2026-11-04 T2: Tunnel und Checks bekommen keinen `Switch` — heute gibt es dort keinen Umschalter, ein Toggle wäre neues Verhalten.
- 2026-11-04 T2: Provisionierung zeigt Befehle per `CodeBlock copyable={false}`, der Kopierknopf bleibt eigener erster Knopf der `.cmd-box` — die Status-Meldung und das Ausblenden des Tokens aus `copyText` bleiben erhalten.
- 2026-11-04 T7: Dateien um `connection-crud`, `tunnel-crud`, `tunnel-create`, `tunnel-start` erweitert — sie drücken `.conn-toolbar/.tun-toolbar .btn.primary`, das mit `Button` zu `.ui-btn-primary` wird.
- 2026-11-04 T3: keine automatische Playbook-Auswahl (Detail zeigt bis zur Wahl einen Hinweis); Bearbeiten im Detail-Kopf statt Hover-Overlay; Rail-Knopf „+ Playbook“ statt „Hochladen“, weil die Funktion Anlegen per Modal ist; ungenutzte Schlüssel ansible.step.* und der globale Ansible-Block in app.css entfallen.
