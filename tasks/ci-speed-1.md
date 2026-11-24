<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CI schneller — Task-Ledger
Status: aktiv · Branch: feature/ci-speed-1 · Review: am Ende
Spec: docs/features/ci-speed-1.md (Roadmap R-1743, R-1725)
Heavy: none — CI-Workflow, Harness-Skript und Skill-Text; kein Stack-, Gateway-, PKI- oder Install-Pfad, die PR-CI und der Queue-Lauf fahren die neue Teilung selbst
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1743: Server-pytest in vier Shards  [x]
Komponente: server · Dateien: .github/workflows/ci.yml, docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/ci-speed-1.md, apps/server/tests/test_ci_shards.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @9d8b92bb4 2026-11-24T11:25:49+01:00
Review: am Ende (Branch-Review)
Änderung: In `server` und `python-lock-server` Matrix `shard: [1, 2, 3, 4]`, `PYTEST_SHARD: ${{ matrix.shard }}/4`, Jobname `… shard ${{ matrix.shard }}/4`, `SHARDS: "4"` in beiden Gate-Jobs; Kommentare nachziehen. cicd.html DE+EN: vier Shards. Fragment umlautfrei.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ci_shards.py tests/test_ci_workflow.py
Doku: docs/developer/cicd.html DE+EN · changelog.d/ci-speed-1.md

### T2 — R-1743, R-1725: früh einreihen, queue-wait.sh erkennt rote PR-Checks  [ ]
Komponente: scripts · Dateien: scripts/dev/queue-wait.sh, scripts/tests/queue_wait_test.sh, .claude/skills/feature-build/SKILL.md
Änderung: `queue-wait.sh` liest zusätzlich `statusCheckRollup.state` des letzten Commits; offen, nicht in der Queue, Auto-Merge an und `FAILURE`/`ERROR` → Exit 1 mit Grund „PR-Checks rot, Auto-Merge wartet“. `/feature-build` §4.7: nach `gh pr create` und erfüllten Prüf-Bedingungen gleich `review.sh final … && gh pr merge <n> --match-head-commit <geprüfter HEAD>` (Auto-Merge bei laufender CI), dann `queue-wait.sh`; Exit 1 wegen roter PR-Checks → `gh pr merge <n> --disable-auto`, dann wie rote CI. Test mit Gegenprobe.
Verify: bash scripts/dev/verify.sh scripts --strict -- queue_wait_test harness_consistency_test
Doku: → T1 (changelog.d/ci-speed-1.md)
