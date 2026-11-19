<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-agent-1 — Task-Ledger
Status: geplant · Branch: feature/klein-tests-agent-1 · Review: am Ende
Spec: docs/features/klein-tests-agent-1.md (Roadmap R-1625)
Heavy: none — nur Go-Unit-Test
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1625: abgewiesener Dial wartet auf Windows nicht auf den Accept  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/guard_test.go
Beweis: main-CI 2026-11-19 · Lauf 44467133925 Job 135367588705 @6b38c82fa · Dedup-Key: BUG:agent:internal/probe/guard_test.go:TestGuardChecksTheOwnersOfThePortAfterTheConnect
Semantik: keine Stelle in docs/ — Testhygiene; der Test benennt das Soll (Guard urteilt nach dem Connect)
Änderung: Die FreeBSD-Ausnahme vor dem Accept-Warten gilt auch für `windows` (`runtime.GOOS == "freebsd" || == "windows"`), Kommentar nennt das Warum. Dauerlauf `-count=50` auf Linux als Regressionsbeleg; Windows-Wackler ohne lokalen Weg: „nicht verifiziert“ im Commit-Body, die PR-CI fährt windows-latest.
Verify: bash scripts/dev/verify.sh agent --strict -- -run '^TestGuardChecksTheOwnersOfThePortAfterTheConnect$' ./internal/probe
Doku: keine (Tests)
