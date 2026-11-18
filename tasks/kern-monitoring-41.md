<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-41 — Last-Schonung: Grenze für gehaltene Checks — Task-Ledger
Status: geplant · Branch: feature/kern-monitoring-41 · Review: am Ende
Spec: docs/features/kern-monitoring-41.md (Roadmap R-1400)
Heavy: none — nur Bewertung im Monitoring-Dienst (Router/Checker), kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Prüfung: `security` zusätzlich zum `reviewer` in der Abschlussprüfung.

## Tasks

### T1 — R-1400: Warnung ab Beginn, gehaltene Checks nach 15 min unknown  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/agent.py, apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_agent_load_shed.py
Änderung: `_LOAD_SHED_WARN_MINUTES` auf 0; `_spared_by_load_shed` hält einen Check nur bis 15 min nach
`load_shed_since`, danach bewertet die Report-Schleife ihn `unknown` („Not measured: load shedding since <Zeit> UTC“)
über `apply_result` mit Übergang und Alarm. Tests: Warnung ab Minute 0, gehalten vor 15 min, `unknown` ab 15 min mit
Übergang, nach Ende der Schonung wieder bewertet.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_load_shed.py
Doku: → T2

### T2 — Doku und CHANGELOG  [ ]
Komponente: monitoring · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-41.md
Änderung: „Schonung unter Last“ DE+EN: Warnung ab Beginn, `unknown` nach 15 min; Changelog-Fragment.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_load_shed.py
Doku: docs/admin/monitoring.html DE+EN · changelog.d/kern-monitoring-41.md
Task-Review: am Ende
Abhängt von: T1
