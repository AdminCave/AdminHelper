<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ops-12 — Task-Ledger
Status: erledigt · Branch: feature/ops-12 · Review: am Ende
Spec: docs/features/ops-12.md (Roadmap R-1646)
Heavy: none — nur Harness-Skripte und ihre Bash-Tests, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Dateien:-Element mit Leerzeichen ist ein Fehler (R-1646)  [x]
Komponente: scripts · Dateien: scripts/dev/task-close.sh, scripts/dev/ledger.sh, scripts/tests/task_close_test.sh, scripts/tests/ledger_test.sh, tasks/README.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @f21d0f53c 2026-11-19T19:43:59+01:00
Review: am Ende (Branch-Review)
Änderung: `task-close.sh` bricht mit Exit 2 ab, wenn ein Element der `Dateien:`-Zeile nach dem Entfernen der Klammer-Notizen Leerzeichen trägt (statt nur das erste Wort zu stagen); `ledger.sh lint` meldet dasselbe als `ERROR`. Beide Tests bekommen den Fall (rot vorher) und eine Gegenprobe mit Klammer-Notiz; `tasks/README.md` nennt Notizen in Klammern.
Beweis: feature/kern-windows-2@29d1b059d scripts/dev/task-close.sh:127 · Dedup-Key: REF:harness:task-close.sh:TASK_FILES
Verify: bash scripts/dev/verify.sh scripts --strict -- task_close_test ledger_test
Doku: tasks/README.md
