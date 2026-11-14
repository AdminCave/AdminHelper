<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ui-desktop-4 — Task-Ledger
Status: aktiv · Branch: feature/klein-ui-desktop-4 · Review: am Ende
Spec: docs/features/klein-ui-desktop-4.md (Roadmap R-1379)
Heavy: none — nur Desktop-UI-Komponente, Unit-Tests
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1379: Monitoring-Teile des Dashboards nur für Admins  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/pages/Dashboard.svelte, apps/desktop/ui/src/pages/Dashboard.layout.test.ts, apps/desktop/ui/src/pages/Dashboard.load.test.ts
Beweis: Nit klein-ui-desktop-3 Abschlussprüfung 2026-11-12 · Dedup-Key: REF:desktop-ui:Dashboard.svelte:monitoring-panel-admin
Änderung: `monitoringShown = serverMode && isAdmin`: Karten „Server“ und „Probleme“, Panel „Monitoring“ und das Laden von Servern und Monitoring nur dann; die Layout-Tests laufen als Admin, neuer Test: Nicht-Admin im Server-Modus sieht weder Karten noch Panel, `loadServers`/`loadMonitoring` laufen nicht, der Tunnel bleibt (erst rot).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/pages/Dashboard
Doku: keine (Nicht-Admins sahen einen Fehler statt einer Funktion)
