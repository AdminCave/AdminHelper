<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-9 — Exponierte Container-Ports jenseits der Kappung — Task-Ledger
Status: aktiv · Branch: feature/kern-agent-9 · Review: am Ende
Spec: docs/features/kern-agent-9.md (Roadmap R-1524)
Heavy: none — nur Monitoring-Abgleich (module_sync), kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Tasks

### T1 — R-1524: gekappte exponierte Portliste gilt als unbekannt  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/module_sync.py, apps/monitoring/tests/test_module_sync.py, changelog.d/kern-agent-9.md
Beweis: reviewer kern-agent-6 T6 2026-11-16 · feature/kern-agent-6@80d09522f apps/agent/internal/discovery/discovery.go containerPorts · Dedup-Key: bug:agent:discovery:containerPorts-cap
Änderung: `_seen_ports` gibt ohne `listening` und bei einer exponierten Liste mit `MAX_CONTAINER_PORTS` Einträgen
keine gesehenen Ports zurück (der Agent entscheidet). Erst der rote Test (64 exponierte Ports, Hinweis-Port jenseits
des Schnitts → bisher „has no port“), dann der Fix; Changelog-Fragment.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py
Doku: changelog.d/kern-agent-9.md

## Entscheidungen
