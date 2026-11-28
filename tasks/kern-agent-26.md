<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-26 — FreeBSD-Dienste: Liste gecacht, Abfrage alle 15 min — Task-Ledger
Status: aktiv · Branch: feature/kern-agent-26 · Review: am Ende
Spec: docs/features/kern-agent-26.md (Roadmap R-1706)
Heavy: linux-full — apps/agent (Sammellauf); dazu vor dem Merge ein Agent-Lauf auf einer FreeBSD-Pool-Box: zwei Läufe, der zweite ohne service-Aufrufe für den Block (self.collectors.services.cpu_ms)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- Kevin 2026-11-28 R-1706: Liste aus `service -e` cachen, bis sich rc.conf oder rc.conf.d ändert (mtime), Intervall für Dienste 15 min.

### T1 — R-1706: FreeBSD-Dienstblock aus dem Cache, Liste bis zur rc.conf-Änderung  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/rcservice.go, apps/agent/internal/monitor/services_freebsd.go, apps/agent/internal/monitor/services_linux.go, apps/agent/internal/monitor/services_windows.go, apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/reportstate.go, apps/agent/internal/monitor/cycle.go, apps/agent/internal/monitor/rcservice_test.go, apps/agent/internal/monitor/report_test.go, apps/agent/internal/monitor/reportstate_test.go, apps/agent/internal/monitor/servicelogs_linux_test.go, apps/agent/internal/monitor/servicelogs_windows_test.go, apps/agent/internal/monitor/services_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @8ef8ff1cb 2026-11-28T04:26:01+01:00
Review: am Ende (Branch-Review)
Änderung: `rcServiceHealth` nimmt den gespeicherten Cache und die Zeit: vor 15 min Alter liefert er den letzten Block ohne service-Aufruf; danach fragt er die Status ab, `service -e` nur bei geändertem Stempel (Spec). Der Cache liegt im Report-State, bleibt nach verlorenem Push erhalten, ein Fehler setzt keinen. Tests mit gefälschtem service(8) zählen die Aufrufe: zweiter Lauf binnen 15 min null, nach 15 min ohne `-e`, nach Stempeländerung mit `-e`, nach Fehler neu.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T2

### T2 — Doku und Changelog  [ ]
Komponente: scripts · Dateien: docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-agent-26.md
Änderung: FreeBSD-Spalte von `collectServiceHealth` nennt Cache, Stempel und 15 min; Fragment unter `### Changed`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/agent.html DE+EN · changelog.d/kern-agent-26.md
Task-Review: am Ende
