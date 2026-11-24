<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-22 — Nachlese kern-agent-23 — Task-Ledger
Status: aktiv · Branch: feature/klein-nachlese-22 · Review: am Ende
Spec: docs/features/klein-nachlese-22.md (Roadmap R-1771)
Heavy: none — eine Doku-Zelle, Fehlertexte und Kommentare in Tests
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@c7d1f4bed`.

### T1 — Agent-Doku: Platten-Zelle nennt gopsutil/disk nur für Linux und Windows (R-1771)  [x]
Komponente: scripts · Dateien: docs/developer/agent.html, docs/en/developer/agent.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @20a654319 2026-11-24T22:06:17+01:00
Review: am Ende (Branch-Review)
Task-Review: am Ende
Beweis: reviewer/security kern-agent-23 2026-11-24 · apps/agent/internal/monitor/disks_other.go (`//go:build !freebsd`, `disk.Partitions`, `disk.Usage`), disks_freebsd.go (`getfsstat` statt `disk.Partitions`, R-1701)
Semantik: docs/developer/agent.html: "Unter FreeBSD holt disks_freebsd.go nur die Liste der Mounts mit einem getfsstat ohne Warten"
Dedup-Key: ref:agent:monitor_init_test.go:nachlese-kern-agent-23
Änderung: Der erste Satz der Zelle `collectDisks()` (DE+EN) nennt `gopsutil/disk` als gemeinsamen Code; richtig: Linux und Windows lesen über `disk.Partitions` und `disk.Usage` (`disks_other.go`), FreeBSD nimmt von gopsutil nur die Typen und die Rechnung.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Änderung selbst

### T2 — Agent-Tests: Fehlertexte nennen push.Init, TestPush* tragen den runCycle-Hinweis (R-1771)  [ ]
Komponente: agent · Dateien: apps/agent/cmd/adminhelper-agent/monitor_init_test.go, apps/agent/internal/monitor/plan_test.go, apps/agent/internal/monitor/loadgate_test.go, apps/agent/internal/monitor/reportstate_test.go, apps/agent/internal/monitor/servicelogs_linux_test.go
Beweis: reviewer/security kern-agent-23 2026-11-24 · monitor_init_test.go:56,66,131, apps/agent/internal/monitor/push/init.go:46 (`func Init`)
Semantik: keine Stelle in docs/ — gesucht: Testtexte sind kein dokumentiertes Verhalten
Dedup-Key: ref:agent:monitor_init_test.go:nachlese-kern-agent-23-tests
Änderung: In `monitor_init_test.go` heißt `monitor.Init` in den drei Fehlertexten `push.Init`. Die Tests, die `runCycle` fahren und `Push` im Namen tragen (`TestPushSendsTheProbesAndKeepsThemThroughALostPush`, `TestPushSendsTheStoredRefsAndKeepsTheBrakeUntilTheCredentialIsSetAnew`, `TestPushRunsTheDiscoveryThePlanAsksForOnce`, `TestPushKeepsTheLoadGateAfterALostPush`, `TestReportStatePushSavesOnlyAfterSuccess`, `TestPushSendsTheErrorLinesThePlanAsksForAndAgainAfterALostPush`), bekommen einen Kommentar: seit kern-agent-23 fährt der Test `runCycle` (Collect, dann Done), nicht `Push`; der Name bleibt.
Verify: bash scripts/dev/verify.sh agent --strict -- ./cmd/adminhelper-agent/ ./internal/monitor/
Doku: keine (nur Fehlertexte und Kommentare)
