<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ui-desktop-3 — Spec

## Problem
- **R-1333:** Der Monitoring-Proxy antwortet Nicht-Admins mit 403 (`apps/server/app/modules/monitoring_proxy/router.py`,
  `get_current_admin`). Der Desktop zeigt den Menüpunkt „Monitoring“ und die Seite aber jeder Server-Sitzung
  (`AppShell.svelte`, `navItems`, `serverOnly: true`); R-1289 hat deshalb nur den Funde-Tab und den Puls einzeln
  auf Admins beschränkt.
- **R-1358:** `ConnectionEditor.svelte` zeigt für eine Verbindung mit `serverId` das Namensfeld des Servers nur, wenn
  der Server in `$infraServers` steht. Solange die Liste nicht geladen ist, erscheint das freie Namensfeld mit dem
  Anzeigenamen; Umbenennen ergibt dann „web01 · web01 · X“.

## Ziel / Nicht-Ziele
- Menüpunkt und Route `/monitoring` nur für eine Admin-Sitzung (Nicht-Admin: Dashboard, wie bei jeder Seite ohne
  Berechtigung). Der Funde-Tab prüft die Rolle danach nicht mehr selbst. Der Puls (`monitoringPulse`) behält seine
  Prüfung: er läuft in der Shell, nicht in der Seite.
- Namensfeld des ConnectionEditors gesperrt, solange eine Verbindung mit `serverId` ihren Server noch nicht in der
  Liste hat (nur Admin im Server-Modus, sonst lädt die Liste nie). Wählt der Nutzer „kein Server“, wird das Feld frei.
- Keine neue Rolle, kein Server-Eingriff, keine Änderung der Proxy-Antwort.

## Dateien
`apps/desktop/ui/src/components/AppShell.svelte` (+ Test), `apps/desktop/ui/src/pages/Monitoring.svelte`
(+ `Monitoring.test.ts`), `apps/desktop/ui/src/components/ConnectionEditor.svelte` (+ Test), `changelog.d/klein-ui-desktop-3.md`.

## Datenmodell / API / Integrationen
Keine.

## Trade-offs
R-1358: Sperren statt den Anzeigenamen zu verbergen — der Nutzer sieht, dass etwas lädt, und kann nichts Falsches
speichern (Kevin 2026-11-12). Ist die Liste nicht ladbar, bleibt das Feld gesperrt, bis er den Server abwählt.

## Risiken & Rollback
Reine UI-Logik mit Vitest, je Task ein Commit, per Revert rückgängig.

## Doku-Impact
Keine: kein Handbuchtext nennt die Sichtbarkeit; Änderung steht im Changelog-Fragment.

## Offene Fragen
Keine.
