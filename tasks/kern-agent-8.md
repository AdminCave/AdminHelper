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

### T1 — R-1523: Namensregeln urteilen bei Multicall-Binaries nach dem Applet  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/sensor_local_linux.go, apps/agent/internal/probe/sensor_local_freebsd.go, apps/agent/internal/probe/target.go, apps/agent/internal/probe/discover.go, apps/agent/internal/probe/guard_test.go, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-agent-8.md, apps/agent/internal/probe/sensor_local_linux_test.go, apps/agent/internal/probe/target_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @6db1d4251 2026-11-18T15:29:34+01:00
Review: approve (.ah-out/review/kern-agent-8/T1.verdict.json)
Änderung: eine Funktion bestimmt den Programmnamen aus `processName` und, bei busybox, toybox und dropbearmulti, aus
`processArgs` (Basisname von argv[0], ist es das Binary selbst argv[1]); unlesbares oder leeres argv ist
`ErrNotAllowed`. Alle Aufrufer der Namensregeln nutzen sie. Tests: `busybox tcpsvd` als Aktivator, `dropbearmulti
dropbear` nie geprüft, `busybox nc` als Weiterleiter (TCP und Unix-Socket), Link-Form unverändert, `busybox httpd`
weiter erlaubt, unlesbares argv abgewiesen.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: docs/admin/monitoring.html DE+EN · changelog.d/kern-agent-8.md

### T2 — R-1523: toybox wie busybox an jedem Namen mit seinem Präfix erkennen  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go
Änderung: Fund der Abschlussprüfung: toybox nimmt wie busybox jeden Namen, der mit `toybox` beginnt, als sich selbst
(`toy_find` in `main.c`; Release-Binaries `toybox-<arch>`); `isMulticall` erkennt bisher nur den exakten Namen. Dazu
die Namen in den Fehlern von `programName` auf 64 Zeichen gekürzt wie die übrigen. Tests: `toybox-x86_64 nc` als
Kernel-Name und als argv[0].
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: keine (die Doku nennt toybox schon; die Regel folgt dem Binary)

## Entscheidungen
