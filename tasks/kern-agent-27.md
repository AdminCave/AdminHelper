<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-27 — Agent-Test wartet auf den hängenden stat — Task-Ledger
Status: bereit · Branch: feature/kern-agent-27 · Review: am Ende
Spec: Roadmap R-1820
Heavy: none — nur ein Go-Unit-Test, kein Produktcode
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- 2026-11-26 Kern-Zug statt klein-tests-agent: main ist seit 6735752 rot (Lauf 45861370705, auch im Rerun), das sperrt jede Session; #683 und #684 ändern apps/agent nicht, ein Revert hälfe nicht.

### T1 — R-1820: TestBoundedStatsAsksAHungMountOnlyOnce wartet, bis der hängende stat begonnen hat  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/disks_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @48bb6ce37 2026-11-26T18:08:47+01:00
Review: am Ende (Branch-Review)
Beweis: main@673575277, Lauf 45861370705 (Versuch 1 und 2), disks_test.go:132 „the hung mount was asked 0 times, want 1“
Dedup-Key: bug:agent:apps/agent/internal/monitor/disks_test.go:TestBoundedStatsAsksAHungMountOnlyOnce
HEAD: 8984d1230
Änderung: boundedStats markiert den Mount synchron als ausstehend, die Goroutine zählt den Aufruf erst, wenn sie läuft; unter -race auf einem ausgelasteten Runner prüft der Test vorher. Der Stub meldet den Eintritt des hängenden Mounts über einen Kanal, der Test wartet darauf (mit Frist), bevor er den zweiten Lauf startet und zählt. Kein Produktcode.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: keine (nur Test)
