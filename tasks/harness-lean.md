<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness schlanker: Hauptsession baut, ein Reviewer prüft Code und Tests — Task-Ledger
Status: aktiv · Branch: feature/harness-lean · Review: am Ende
Spec: docs/features/harness-lean.md (Roadmap R-0915)
Heavy: none — Regel-, Skill- und Agenten-Texte, Shell-Skripte unter `scripts/dev` mit hermetischen Tests; kein Stack-, Gateway-, PKI-, Compose- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Auftrag Kevin 2026-10-28, einmaliger Ablauf: die Session baut alle Tasks selbst, ohne Sub-Agenten; danach
genau ein unabhängiger Reviewer über den Branch (daher `Review: am Ende`). Harness-Pfade auf Kevins Wort.

### T1 — verify.sh: volles Log in eine Datei, ins Modell nur Digest  [x]
Komponente: scripts · Dateien: scripts/dev/log-digest.sh, scripts/dev/verify.sh, scripts/tests/log_digest_test.sh, scripts/tests/verify_test.sh, scripts/tests/run.sh, .claude/settings.json
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @18821e0a 2026-10-28T12:30:45+01:00
Review: am Ende (Branch-Review)
Änderung: `log-digest.sh <log> [<rc>]` druckt aus einer `run.sh`-Ausgabe jede PASS/FAIL/SKIP-Zeile außer den per `--only`/`--` ausgelassenen (gezählt), jede `strict-failed:`-Zeile, je rotem Schritt Fehlerzeilen und Ende seines Abschnitts mit Zeilenbereich, die Summary, Exit und Logpfad; ohne Summary das Log-Ende. `verify.sh` schreibt die volle Ausgabe nach `.ah-out/logs/verify-*.log` (die letzten 30 bleiben), druckt den Digest, `--full` streamt zusätzlich; `last-verify.json` trägt `log`. Test neu, in die Liste des scripts-Blocks.
Verify: bash scripts/dev/verify.sh scripts --strict -- log_digest_test verify_test task_close_test
Doku: → T5

### T2 — review.sh final: Abschlussprüfung aus dem Branch-Urteil  [x]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/tests/review_scripts_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @3d5b59e7 2026-10-28T12:36:12+01:00
Review: am Ende (Branch-Review)
Änderung: `review.sh final <ledger>` liest `.ah-out/review/<slug>/branch.verdict.json` des Worktrees, verlangt `verdict`, `code.verdict` und `tests.verdict` = `approve`, einen `head`, nach dem nur Merges oder reine Ledger-Commits folgen, und höchstens drei `tests.probes`; keine offene `[ ]`/`[?]`-Task. Exit 0 mit dem PR-Abschnitt (Code, Tests, Gegenproben, Funde), 3 mit den Gründen, 2 Aufruf.
Verify: bash scripts/dev/verify.sh scripts --strict -- review_scripts_test
Doku: → T5

### T3 — Ledger-Format, REG-Ledger, Skript-Kommentare  [x]
Komponente: scripts · Dateien: tasks/README.md, tasks/templates/task.md, scripts/dev/ledger.sh, scripts/tests/ledger_test.sh, scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, scripts/dev/task-close.sh, scripts/dev/review-risk.txt
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @a755fa14 2026-10-28T12:40:54+01:00
Review: am Ende (Branch-Review)
Änderung: `tasks/README.md`: Task-Zuschnitt, `Doku:`-Formen (`→ T<n>` für die Doku-Task), Abschnitt `## Entscheidungen`, Status `bereit` ohne `tester`. `ledger.sh lint`: `Doku: → T<n>` nennt eine Task desselben Ledgers. Das REG-Ledger aus `heavy.sh` ohne `Modell: Opus`, mit der neuen DoD-Zeile. Kommentare in `task-close.sh` und `review-risk.txt` ohne `builder`.
Verify: bash scripts/dev/verify.sh scripts --strict -- ledger_test heavy_test task_close_test
Doku: keine (die Dateien sind selbst Regel und Format)

### T4 — Regeln, Agenten, Skills, Modelle  [ ]
Komponente: scripts · Dateien: CLAUDE.md, .claude/agents/builder.md, .claude/agents/tester.md, .claude/agents/reviewer.md, .claude/agents/security.md, .claude/agents/advisor.md, .claude/skills/feature-build/SKILL.md, .claude/skills/feature-plan/SKILL.md, .claude/skills/test/SKILL.md, .claude/rules/docs.md, .claude/rules/testing.md, .claude/settings.json, scripts/tests/harness_consistency_test.sh, scripts/tests/run.sh
Änderung: `CLAUDE.md` gekürzt auf Grundregeln mit Verweisen; Rollen Session/`reviewer` (task, branch)/`security`/`advisor`; `builder` und `tester` gelöscht; `/feature-build` und `/feature-plan` nach der Spec; Modelle in `settings.json` und Frontmatter; Doku-Regel. Neuer hermetischer Test prüft die Konsistenz von Regeln, Skills, Agenten, Settings und Skripten.
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test ledger_test
Doku: → T5

### T5 — Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md
Änderung: `DEVELOPMENT.md` (verify.sh-Log und Digest, Task schliessen, Entwicklung mit Claude Code), `cicd.html` DE+EN (Verify-Konvention, Review und Abschluss mit `review.sh final`), CHANGELOG `Changed`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test harness_consistency_test
Doku: DEVELOPMENT.md · docs/developer/cicd.html DE+EN · CHANGELOG

## Entscheidungen
