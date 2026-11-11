<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ui-desktop-2 — Task-Ledger
Status: aktiv · Branch: feature/klein-ui-desktop-2 · Review: am Ende
Spec: docs/features/klein-ui-desktop-2.md (Roadmap R-1289)
Heavy: none — reine UI-Logik mit Vitest
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1289: Puls und Funde-Tab nur für Admins  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/monitoringPulse.ts, apps/desktop/ui/src/lib/stores/monitoringPulse.test.ts, apps/desktop/ui/src/pages/Monitoring.svelte, apps/desktop/ui/src/pages/Monitoring.test.ts, changelog.d/klein-ui-desktop-2.md
Beweis: arch-monitoring-ui Abschlussprüfung 2026-11-10 (nit) · feature/arch-monitoring-ui@71a633acf apps/desktop/ui/src/lib/stores/monitoringPulse.ts:62 · Dedup-Key: REF:desktop-ui:monitoringPulse.ts:admin-gate
Semantik: apps/server/app/modules/monitoring_proxy/router.py:191 „Proxy for all monitoring requests (admins only).“
Änderung: Der Puls fragt nur, solange `session.isAdmin === true` (ein Wechsel der Rolle stoppt oder startet ihn wie An-/Abmelden); der Funde-Tab steht nur in der Tab-Liste, wenn die Session Admin ist. Tests: Nicht-Admin fragt nie und meldet keine Stille; Admin wie bisher; Tab fehlt für Nicht-Admin.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/monitoringPulse.test.ts src/pages/Monitoring.test.ts
Doku: keine (Changelog-Fragment changelog.d/klein-ui-desktop-2.md)
