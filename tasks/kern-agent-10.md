<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-10 — Prozess-Metriken finden busybox-Applets — Task-Ledger
Status: bereit · Branch: feature/kern-agent-10 · Review: am Ende
Spec: docs/features/kern-agent-10.md (Roadmap R-1606)
Heavy: linux-full — apps/agent (Prozess-Sensor)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Tasks

### T1 — R-1606: processesNamed und dockerdRuns vergleichen das Applet  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_local.go, apps/agent/internal/probe/sensor_local_test.go, apps/agent/internal/probe/sensor_local_linux_test.go, changelog.d/kern-agent-10.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @14d3c4400 2026-11-19T05:05:59+01:00
Review: am Ende (Branch-Review)
Änderung: Ein gemeinsamer Vergleich (Prozessname, bei `isMulticall` das Applet über `programName`) für
`processesNamed` und `dockerdRuns`, wie `ownedBy` (`target.go:200`). Tests: Nahtstellen-Test (busybox-Applet
gefunden, nicht lesbares Applet nicht gezählt, gewöhnlicher Name wie bisher) und ein Linux-Test mit echtem
`busybox sleep`, beide erst rot.
Beweis: reviewer-Rand kern-agent-8 2026-11-18; der rote Linux-Test gegen origin/main zeigt ihn.
Dedup-Key: bug:agent:sensor_local.go:process-metrics-comm
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: changelog.d/kern-agent-10.md

## Entscheidungen
