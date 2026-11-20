<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-monitoring-4 — Task-Ledger
Status: aktiv · Branch: feature/klein-tests-monitoring-4 · Review: am Ende
Spec: docs/features/klein-tests-monitoring-4.md (Roadmap R-1600)
Heavy: none — ein Monitoring-Unit-Test
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1600: Wortlaut der ok-Meldung von agent_ping pinnen  [ ]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_agent_ping_checker.py
Beweis: Nit Abschlussprüfung klein-ui-desktop-5, 2026-11-18
Semantik: keine Stelle in docs/ — der fehlende Test selbst ist der Fund
Änderung: `test_fresh_agent_is_ok` prüft die Meldung wörtlich (`Agent active (last report 120s ago)`), mit einem Kommentar, dass `SecHeartbeat.svelte` beide Formen parst. Gegenprobe: mit geändertem Wortlaut im Checker wird der Test rot.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_ping_checker.py
Doku: keine (Test)
