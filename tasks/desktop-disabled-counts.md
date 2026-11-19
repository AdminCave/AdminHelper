<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-Monitoring: deaktivierte Checks nicht mitzählen — Task-Ledger
Status: bereit · Branch: feature/desktop-disabled-counts · Review: am Ende
Spec: Roadmap R-1640
Heavy: none — nur Desktop-UI-Modell (`lib/models/monitoring.ts`), kein Stack-, Gateway-, PKI-, Agent- oder Install-Pfad; keine API-Änderung
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Zusammenfassung und schlechtester Status ohne deaktivierte Checks (R-1640)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/models/monitoring.ts, apps/desktop/ui/src/lib/models/monitoring.test.ts, changelog.d/desktop-disabled-counts.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @18e555142 2026-11-19T15:13:36+01:00
Review: am Ende (Branch-Review)
Beweis: Code-Lesung an origin/main@39a08c2a7: `worstStatus` (`lib/models/monitoring.ts:28`) und `computeSummary` (`:218`) zählen jeden Check mit `state`, auch `enabled === false`; ein abgeschalteter Check behält seinen letzten Status eingefroren. Davon leben Server-Kopf (`MonServerDashboard.svelte:87-88`, Pills, Problemzahl, Ampel), Kartenrang (`:176`) und Kartenfarbe (`cardStatus`, `ModuleCard.svelte:35`), Sektionen (`section/Sec*.svelte`), Serverliste und -raster (`groupChecksByServerWithSummary`), Übersichtskarten (`MonSummaryCards.svelte:13`) und die Wahl des schlechtesten Servers (`stores/monitoring.ts:80`). Nur `pages/Dashboard.svelte:56` und `StatusFooter.svelte:57` filtern schon selbst. Kevin 2026-11-19: nach dem Deaktivieren eines Checks oder eines Checks unter einer Karte bleiben Zähler und Zahl rot.
Dedup-Key: bug:desktop:lib/models/monitoring.ts:computeSummary-enabled
HEAD: 39a08c2a7
Semantik: docs/developer/monitoring.html — „GET /status/summary zählt je Status nur eingeschaltete Checks (ein abgeschalteter behält seinen letzten Status eingefroren)“; docs/adr/0004-monitoring-neuordnung.md §12.2 — „das Objekt zeigt ‚nicht erhoben‘ statt des eingefrorenen Status“.
Änderung: `worstStatus` und `computeSummary` überspringen Checks mit `enabled === false` (der Parametertyp von `worstStatus`/`cardStatus` bekommt `enabled?: boolean | null`); damit folgen alle Aufrufer an einer Stelle, `total` zählt wie `/status/summary` nur eingeschaltete. Erst der rote Test in `monitoring.test.ts` (kritischer abgeschalteter + ok eingeschalteter Check: Summary ohne critical, worst `ok`, `cardStatus` `ok`, `groupChecksByServerWithSummary` ohne den Check in `summary`/`worst`), dann der Fix. Changelog-Fragment `### Fixed`, umlautfrei.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/models/monitoring.test.ts
Doku: changelog.d/desktop-disabled-counts.md (keine Doku-Seite beschreibt die Desktop-Zähler; die Semantik-Stelle gilt schon so)

## Entscheidungen
- 2026-11-19 T1: Der Filter sitzt in `worstStatus`/`cardStatus`/`computeSummary` statt bei jedem Aufrufer, damit alle Zähler (Server-Kopf, Karten, Sektionen, Serverliste/-raster, Übersicht, Wahl des schlechtesten Servers) an einer Stelle folgen; `total` zählt wie `/status/summary` nur eingeschaltete. `computeSummary` prüft `'enabled' in c`, weil `MonCheckSummary` kein `enabled` trägt. Das Web-Frontend hat keine Monitoring-Ansicht (nur Wörterbuch-Einträge), dort nichts zu tun. Zusätzlich lokal: `npm run check` Exit 0, vitest über `src/components/monitoring src/lib src/pages` 1669 passed.
