# kern-harness-16 — Nachlese der Harness-Prüfungen — Task-Ledger
Status: erledigt · Branch: feature/kern-harness-16 · Review: pro Task
Spec: docs/features/kern-harness-16.md (Roadmap R-1785, R-1819, R-1822)
Heavy: none — nur Harness-Skripte und ihre hermetischen Tests, kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- Kevin 2026-11-27: alle drei Zeilen angenommen, die Harness-Pfade ändern sich auf Kevins Wort.

### T1 — Teardown: Branch-Ref, Mountpunkte, gepinntes alpine (R-1785)  [x]
Komponente: scripts · Dateien: scripts/dev/worktree-teardown.sh, scripts/tests/worktree_setup_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @1fc33a2e7 2026-11-28T05:17:09+01:00
Review: approve (.ah-out/review/kern-harness-16/T1.verdict.json)
Änderung:
- `merge-base` prüft gegen `refs/heads/$BRANCH`.
- Ein fremder Pfad auf einem anderen Gerät als WT bricht mit einer Meldung ab.
- `alpine` wird per Digest gepinnt.

Tests: ein Tag mit dem Branch-Namen auf einem fremden Commit; ein gestubbter Mountpunkt.
Verify: bash scripts/dev/verify.sh scripts --strict -- worktree_setup_test
Doku: keine (Harness-Interna)

### T2 — ca-issuer-Schritt nur mit Pins, Kommentar aktuell (R-1785, R-1822)  [x]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/run_flags_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @977bf2d9c 2026-11-28T05:39:55+01:00
Review: approve (.ah-out/review/kern-harness-16/T2.verdict.json)
Änderung: Der Schritt ca-issuer pytest ruft `pip_dev` ohne Fallback und ohne `2>/dev/null` auf. Der Kommentar
nennt den CI-Job ca-issuer und die Datenbanktests der Suite.
Verify: bash scripts/dev/verify.sh scripts --strict -- run_flags_test
Doku: keine (Harness-Interna)

### T3 — verify.sh, filtered, task-close: keine geerbten oder alten Zustände (R-1819 1–3)  [x]
Komponente: scripts · Dateien: scripts/dev/verify.sh, scripts/tests/run.sh, scripts/dev/task-close.sh, scripts/tests/verify_test.sh, scripts/tests/task_close_test.sh, scripts/tests/run_flags_test.sh, DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @223bc9c84 2026-11-28T06:09:48+01:00
Review: approve (.ah-out/review/kern-harness-16/T3.verdict.json)
Änderung:
- `verify.sh` verwirft `AH_REQUIRED` und `AH_SCRIPT_TESTS*` vor dem Devenv.
- `filtered` legt seine Datei unter `$AH_OUT_DIR` an.
- `task-close.sh` löscht `last-verify.json` vor dem Lauf.

Tests: ein geerbter Wert wirkt nicht, der Devenv-Wert wirkt; ein altes Artefakt bei einem verify.sh, das grün
endet, ohne zu schreiben.
Verify: bash scripts/dev/verify.sh scripts --strict -- verify_test task_close_test run_flags_test
Doku: DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html

### T4 — Sperrliste und Risikoliste (R-1785, R-1819 4–5)  [x]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/dev/review-risk.txt, scripts/tests/review_scripts_test.sh, tasks/kern-harness-11.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b6eebc292 2026-11-28T06:22:20+01:00
Review: approve (.ah-out/review/kern-harness-16/T4.verdict.json)
Änderung:
- `review.sh sec`: Ein Verzeichnis `tasks/private`, das nicht durchsuchbar ist, gilt als Fehler.
- `review-risk.txt` nimmt auf: `apps/agent/internal/selfupdate/*`, `allowlist/*`, `execx/*`, `scripts/backup.sh`,
  `restore.sh`, `diagnostics.sh`.
- Die Entscheidungszeile zu T2 in `tasks/kern-harness-11.md` wird neutral gefasst.

Verify: bash scripts/dev/verify.sh scripts --strict -- review_scripts_test
Doku: keine (Harness-Interna)
