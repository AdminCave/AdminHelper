<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Merge Queue: frueh einreihen — Task-Ledger
Status: aktiv · Branch: feature/harness-early-enqueue · Review: am Ende
Spec: Roadmap R-1751
Heavy: none — Skill-Text, Harness-Test und Doku; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- 2026-11-24: Kevin hat das Ruleset in der Session freigegeben ("mache du das alles"): 9 Checks neu Pflicht
  (Public repo guard, die drei image-lock-Sammel-Jobs, From-outside stack, embedded RDP, FreeBSD pkg repo, frps
  image, Schema fuzzing), Gruppengröße und Build-Konkurrenz 3. Nicht Pflicht bleiben `Changed paths` (Hilfsjob)
  und die Shard-Jobs (Namen hängen an der Shard-Zahl; ihre Sammel-Jobs sind Pflicht). Alle neuen Pflicht-Checks
  laufen auch auf `merge_group` (Lauf 45402595857 geprüft), sonst hinge die Queue.

### T1 — R-1751: /feature-build reiht gleich nach dem PR ein  [ ]
Komponente: scripts · Dateien: .claude/skills/feature-build/SKILL.md, scripts/tests/harness_consistency_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/harness-early-enqueue.md, tasks/harness-early-enqueue.md
Änderung: §4.7 ohne `gh pr checks --watch` und ohne "nicht vor dem Ende der PR-CI"; Einreihen direkt nach `gh pr create`, Auto-Merge wartet auf die Pflicht-Checks, rote PR-CI meldet `queue-wait.sh` als `checks red`. Hinweis: ein neuer CI-Job braucht Kevins Ruleset-Eintrag. Konsistenztest verbietet das Warten mit `gh pr checks <n> --watch`. cicd.html DE+EN: Ruleset-Werte.
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: docs/developer/cicd.html DE+EN · changelog.d/harness-early-enqueue.md
