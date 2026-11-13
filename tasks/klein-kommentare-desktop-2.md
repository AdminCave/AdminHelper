<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-kommentare-desktop-2 — Task-Ledger
Status: bereit · Branch: feature/klein-kommentare-desktop-2 · Review: am Ende
Spec: docs/features/klein-kommentare-desktop-2.md (Roadmap R-1398)
Heavy: none — nur ein Kommentar
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1398: Kommentar zu `MonitorResourceDetails.problems` nennt `load_shed`  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @6eb239142 2026-11-13T10:33:50+01:00
Review: am Ende (Branch-Review)
Beweis: bau arch-monitoring-module-3 T2 2026-11-12 (apps/monitoring/app/checkers/agent.py `_grade_load_shed`) · Dedup-Key: ref:desktop-ui:types.ts:problems-comment
Änderung: Der Kommentar über `problems` in `MonitorResourceDetails` nennt zusätzlich den Schlüssel `load_shed` (nur `warning`, ohne Hysterese). Der Typ bleibt unverändert.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: keine (interner Kommentar)
