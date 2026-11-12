<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ci-2 — Task-Ledger
Status: erledigt · Branch: feature/klein-ci-2 · Review: am Ende
Spec: docs/features/klein-ci-2.md (Roadmap R-1328)
Heavy: none — nur Schritte eines CI-Jobs
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1328: minisign und gnome-keyring mit apt-Retry holen  [x]
Komponente: scripts · Dateien: .github/workflows/ci.yml
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @a87b66111 2026-11-12T11:55:19+01:00
Review: am Ende (Branch-Review)
Beweis: CI-Läufe 43031705413 (#473) und 43030657863 (#474) 2026-11-11 (Temporary failure resolving) · Dedup-Key: BUG:ci:ci.yml:apt-retry
Semantik: keine Stelle in docs/ — CI-Interna; das Muster setzt ci.yml selbst (apt_opts + retry.sh, Z. 845–852)
Änderung: „Install minisign“ und „Install gnome-keyring“ im Shell-Test-Job übernehmen das Muster der übrigen apt-Schritte (apt_opts, `retry.sh 3 180` für `update` und `install --download-only`, dpkg ohne Retry).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (CI-Interna)
