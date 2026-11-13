<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-6 — Task-Ledger
Status: aktiv · Branch: feature/klein-nachlese-6 · Review: am Ende
Spec: docs/features/klein-nachlese-6.md (Roadmap R-1431)
Heavy: linux-full — Desktop-E2E-Spec, Lauf im Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1431: Theme-Wartefrist der Server-Seiten-Spec auf 30 s  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/monitoring-server-page.live.js
Änderung: `makeShot("server-page", 5000)` wird `makeShot("server-page", 30000)` (testing.md, Fristen: Wartegrenze mindestens 30 s).
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Testcode)
