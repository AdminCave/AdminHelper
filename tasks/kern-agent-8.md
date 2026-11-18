<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-8 — Task-Ledger
Status: aktiv · Branch: feature/kern-agent-8 · Review: pro Task
Spec: docs/features/kern-agent-8.md (Roadmap R-1523)
Heavy: linux-full — `apps/agent` (Wächter); kein PKI-, Install- oder Stack-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Prüfung: `security` zusätzlich zu `reviewer` bei T1 (Wächter).

## Tasks

### T1 — R-1523: Namensregeln urteilen bei Multicall-Binaries nach dem Applet  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/sensor_local_linux.go, apps/agent/internal/probe/sensor_local_freebsd.go, apps/agent/internal/probe/target.go, apps/agent/internal/probe/discover.go, apps/agent/internal/probe/guard_test.go, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-agent-8.md
Änderung: eine Funktion bestimmt den Programmnamen aus `processName` und, bei busybox, toybox und dropbearmulti, aus
`processArgs` (Basisname von argv[0], ist es das Binary selbst argv[1]); unlesbares oder leeres argv ist
`ErrNotAllowed`. Alle Aufrufer der Namensregeln nutzen sie. Tests: `busybox tcpsvd` als Aktivator, `dropbearmulti
dropbear` nie geprüft, `busybox nc` als Weiterleiter (TCP und Unix-Socket), Link-Form unverändert, `busybox httpd`
weiter erlaubt, unlesbares argv abgewiesen.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: docs/admin/monitoring.html DE+EN · changelog.d/kern-agent-8.md

## Entscheidungen
