# Harness: kein gemergter Ledger-Slug für einen neuen Zug — Task-Ledger
Status: bereit · Branch: feature/kern-harness-6 · Review: am Ende
Spec: docs/features/kern-harness-6.md (Roadmap R-1291)
Heavy: none — nur roadmap.py, sein hermetischer Test und Harness-Text, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1291: `status --ledger` und `add --ledger` lehnen einen Ledger-Pfad auf origin/main ab  [x]
Komponente: scripts · Dateien: scripts/dev/roadmap.py, scripts/dev/tests/test_roadmap.py, .claude/skills/feature-plan/SKILL.md, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @970f6d7bf 2026-11-11T10:22:07+01:00
Review: am Ende (Branch-Review)
Änderung: Helfer `on_main(path)` über `repo_git("cat-file", "-e", "origin/main:<pfad>")` (ohne git/Ref: False); in
`cmd_status` (im `change`, gegen die Spalte `Ledger` der Zeile) und `cmd_add` ein `UsageError` mit dem Rat, einen neuen
Slug zu nehmen. Tests auf `branch_repo` mit `refs/remotes/origin/main`: abgelehnt bei fremder Zeile, erlaubt bei
unveränderter Spalte, ohne Ref, für einen Pfad nur auf einem Branch, und für `add`. Erst rot. Satz in /feature-plan §3a.
Beweis: feature/kern-ca-7@a3bf186ae vs origin/main:changelog.d/kern-ca-7.md · Dedup-Key: bug:harness:roadmap:ledger-slug-reuse
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Abschnitt `--ledger`), .claude/skills/feature-plan/SKILL.md
