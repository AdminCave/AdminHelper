<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-44 — Top-5-Prozesse bei hoher Last — Task-Ledger
Status: geplant · Branch: feature/kern-monitoring-44 · Review: am Ende
Spec: docs/features/kern-monitoring-44.md (Roadmap R-1389)
Heavy: linux-full — apps/agent (Bericht)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Tasks

### T1 — R-1389: Agent sendet die Top-5-Prozesse ab 80 % CPU oder RAM  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/processes.go, apps/agent/internal/monitor/processes_test.go, apps/agent/internal/monitor/report.go, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-44.md
Änderung: neue Datei `processes.go` (SPDX): über der Schwelle zwei Stichproben der Prozesszeiten (ctx-begrenzt),
je fünf Prozesse nach CPU-Anteil und RSS, nur `comm`; `collectResources` hängt `top_processes` an. Tests mit
Fake-Prozessliste: unter der Schwelle kein Schlüssel, über CPU bzw. RAM die Listen, sortiert, höchstens fünf,
verschwundener Prozess fällt weg. `processes_test.go` mit SPDX.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: docs/admin/monitoring.html DE+EN · changelog.d/kern-monitoring-44.md

## Entscheidungen
