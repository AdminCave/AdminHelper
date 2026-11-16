<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: Verschachtelungstiefe in Request-Bodies begrenzen — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-34 · Review: pro Task
Spec: docs/features/kern-monitoring-34.md (Roadmap R-1455)
Heavy: none — nur der Monitoring-Dienst; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Tiefengrenze in find_unstorable und im Agent-Report (R-1455)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/core/bounds.py apps/monitoring/app/routers/agent.py apps/monitoring/tests/test_depth.py docs/developer/monitoring.html docs/en/developer/monitoring.html docs/developer/api-reference.html docs/en/developer/api-reference.html changelog.d/kern-monitoring-34.md
Änderung: `find_unstorable` zählt die Tiefe im Stack und weist ab `MAX_DEPTH = 32` mit eigenem Grund ab, ohne den Teilbaum als `input` zu spiegeln; `_refuse_unstorable_report` übernimmt das. Neuer Test (SPDX): tiefe `config`, `channel_config` und Agent-Report sind `422`, die Listen bleiben `200`, Tiefe genau an der Grenze geht durch, die Liveness zählt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_depth.py tests/test_nul.py
Doku: docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-monitoring-34.md

## Entscheidungen
