<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ui-desktop-2 — Spec

## Problem
- **R-1289:** Der Monitoring-Proxy des Servers (`apps/server/app/modules/monitoring_proxy/router.py`, `get_current_admin`)
  antwortet Nicht-Admins mit 403. Die Desktop-UI fragt trotzdem: der Puls (`apps/desktop/ui/src/lib/stores/monitoringPulse.ts`)
  holt `/status/summary` jede Minute, sobald irgendeine Session existiert, und `pages/Monitoring.svelte` zeigt den
  Funde-Tab. Bei einem Nicht-Admin schlägt jede Frage fehl; nach dem Limit meldet der Puls dann „Monitoring ohne
  Ergebnis seit N Min“, obwohl der Nutzer das Monitoring gar nicht sehen darf.

## Ziel / Nicht-Ziele
Der Puls läuft nur bei einer Session mit `isAdmin === true` (Wechsel Admin ↔ Nicht-Admin zählt wie Anmelden/Abmelden).
Der Funde-Tab erscheint nur für Admins. Nicht-Ziele: die übrigen Monitoring-Tabs und die Navigation ändern sich nicht
(dieselbe 403-Lage, aber nicht Teil der Zeile; als Beobachtung im Abschlussbericht); keine Server-Änderung.

## Betroffene Komponenten & Dateien
`apps/desktop/ui`: `src/lib/stores/monitoringPulse.ts`, `src/lib/stores/monitoringPulse.test.ts`,
`src/pages/Monitoring.svelte`, `src/pages/Monitoring.test.ts`.

## Datenmodell / API / Integrationen
Keine. `AuthSession.isAdmin` gibt es bereits (`lib/bridge/types.ts`).

## Trade-offs
Den Tab zu verstecken statt zu sperren genügt: ohne Tab ist `tab === 'findings'` über die UI nicht erreichbar.

## Risiken & Rollback
Gering; ein Commit.

## Doku-Impact
Keine (kein dokumentiertes Verhalten betroffen); Changelog-Fragment `changelog.d/klein-ui-desktop-2.md`.
