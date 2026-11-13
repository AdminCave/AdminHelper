<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Kommentare zu Swap und cpu_count, Komma in der Agent-Doku — Task-Ledger
Status: aktiv · Branch: feature/kern-freebsd-4 · Review: am Ende
Spec: docs/features/kern-freebsd-4.md (Roadmap R-1332)
Heavy: none — nur Kommentare und ein Satzzeichen in der Doku, kein Verhalten
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1332: Monitoring-Kommentare nennen FreeBSD  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/agent.py, docs/developer/agent.html, docs/en/developer/agent.html
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @aca35e9a9 2026-11-13T10:37:20+01:00
Review: am Ende (Branch-Review)
Änderung: die Kommentare an Swap (`agent.py:346`) und Load je CPU (`agent.py:360`) nennen „Linux, FreeBSD“ statt „Linux“;
dazu das Komma nach dem frpc-Pfad vor „das rc.d-Skript“ bzw. „the rc.d script“ (`agent.html:266` DE+EN).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_resources_checker.py
Doku: docs/developer/agent.html, docs/en/developer/agent.html (nur das Komma)

### T2 — R-1332: Desktop-Typkommentar nennt FreeBSD  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.ts
Änderung: der Kommentar an `swap` (`types.ts:363`) sagt „Linux and FreeBSD“ statt „Linux only“.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: keine (nur Kommentar)

## Entscheidungen
