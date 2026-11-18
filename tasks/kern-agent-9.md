<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-9 — Exponierte Container-Ports jenseits der Kappung — Task-Ledger
Status: bereit · Branch: feature/kern-agent-9 · Review: am Ende
Spec: docs/features/kern-agent-9.md (Roadmap R-1524)
Heavy: none — nur Monitoring-Abgleich (module_sync), kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Tasks

### T1 — R-1524: gekappte exponierte Portliste gilt als unbekannt  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/module_sync.py, apps/monitoring/tests/test_module_sync.py, changelog.d/kern-agent-9.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @ddcf3cb8c 2026-11-18T23:48:31+01:00
Review: am Ende (Branch-Review)
Beweis: reviewer kern-agent-6 T6 2026-11-16 · feature/kern-agent-6@80d09522f apps/agent/internal/discovery/discovery.go containerPorts · Dedup-Key: bug:agent:discovery:containerPorts-cap
Änderung: `_seen_ports` gibt ohne `listening` und bei einer exponierten Liste mit `MAX_CONTAINER_PORTS` Einträgen
keine gesehenen Ports zurück (der Agent entscheidet). Erst der rote Test (64 exponierte Ports, Hinweis-Port jenseits
des Schnitts → bisher „has no port“), dann der Fix; Changelog-Fragment.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py
Doku: changelog.d/kern-agent-9.md

### T2 — Doku: volle exponierte Liste beim Rückfall  [x]
Komponente: monitoring · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/features/kern-agent-9.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @3f9797663 2026-11-18T23:52:09+01:00
Review: am Ende (Branch-Review)
Änderung: Entwickler-Doku (`_seen_ports`): eine exponierte Liste mit 64 Einträgen zählt als keine gesehenen Ports;
Spec-Zeilenverweise und Doku-Impact nachgezogen (Fund der Abschlussprüfung).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py
Doku: docs/developer/monitoring.html DE+EN
Task-Review: am Ende

## Entscheidungen
