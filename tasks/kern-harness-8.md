# Adressfilter im PR-Text, .github-Skripttests im scripts-Block, Commit-Betreff geprüft — Task-Ledger
Status: bereit · Branch: feature/kern-harness-8 · Review: am Ende
Spec: docs/features/kern-harness-8.md (Roadmap R-1325, R-1352, R-1359)
Heavy: none — nur Harness-Skripte und ihre hermetischen Tests; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1325: IPv6-Filter lässt a::b-Pfade stehen  [x]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/tests/review_scripts_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b92ef2be4 2026-11-12T14:28:13+01:00
Review: am Ende (Branch-Review)
Beweis: reviewer branch kern-terminal-6 2026-11-11 (`pty::tests::closing_` → `pty::tests<addr>losing_`)
Änderung: `addr()` (`review.sh:401`) lässt eine geparste IPv6-Adresse stehen, wenn direkt davor oder dahinter ein
Wortzeichen steht; die Fixture in `review_scripts_test.sh:910` bekommt `pty::tests::closing_` und `std::fs::read`,
der Test verlangt sie unverändert, die bisherigen Leak-Fälle bleiben rot ohne Maskierung.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Harness-intern)

### T2 — R-1352: scripts-Block fährt .github/scripts/*_test.sh  [x]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/run_flags_test.sh, scripts/tests/harness_consistency_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @439f7adc7 2026-11-12T15:01:48+01:00
Review: am Ende (Branch-Review)
Änderung: Ein Eintrag mit `/` in `AH_SCRIPT_TESTS` gilt relativ zu `$ROOT` (`run.sh:709`); die vier
`.github/scripts/*_test`-Einträge stehen in `AH_SCRIPT_TESTS_DEFAULT` (`run.sh:688`). `run_flags_test.sh` prüft einen
Pfad-Eintrag (grün und rot), `harness_consistency_test.sh` verlangt jedes `.github/scripts/*_test.sh` in der Liste.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Harness-intern)

### T3 — R-1359: commit-msg und task-close verlangen einen Conventional-Commit-Betreff  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/commit-msg, scripts/dev/task-close.sh, scripts/tests/review_scripts_test.sh, scripts/tests/task_close_test.sh, scripts/tests/guard_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @1c35ba5de 2026-11-12T15:22:34+01:00
Review: am Ende (Branch-Review)
Änderung: `commit-msg` und `task-close.sh` (Schritt 1, vor dem Verify, Exit 2) lesen die erste Zeile, die weder leer
noch `#…` ist, und verlangen `<typ>[(scope)][!]: <text>` (Typen in der Spec) oder `Merge `, `Revert "`,
`fixup!`/`squash!`/`amend!`. Tests: freier Betreff und Betreff `Task: …` rot, konformer und Merge-Betreff grün; die
Fixture-Commits unter scharfen Hooks bekommen konforme Betreffs. `DEVELOPMENT.md:609` nennt die Prüfung.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md

### T4 — Abschlussprüfung: IPv6 hinter Wort mit Doppelpunkt, #-Zeilen ohne Editor  [x]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/dev/hooks/commit-msg, scripts/dev/task-close.sh, scripts/tests/review_scripts_test.sh, scripts/tests/task_close_test.sh, scripts/tests/harness_consistency_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @256962d78 2026-11-12T15:50:40+01:00
Review: am Ende (Branch-Review)
Beweis: reviewer branch + security branch 2026-11-12 @167f0c986 (`node:fd00::1`, `IPv6:2001:db8::5` bleiben im PR-Text stehen; `-m "# c\n\nfix: y"` committet den Betreff `# c`)
Änderung: `addr()` fällt bei einem angrenzenden Wortzeichen in die Wiederholung hinter dem ersten einfachen
Doppelpunkt statt den Treffer stehen zu lassen; die Fixture bekommt `node:`, `IPv6:`, `eth0:`, `Source:`. `commit-msg`
überspringt `#`-Zeilen nur, wenn git einen Editor startet (`GIT_EDITOR` ≠ `:`), `task-close.sh` nur leere Zeilen;
Tests für beide Richtungen. `harness_consistency_test` verlangt dieselbe `SUBJECT_RE` in beiden Dateien;
`DEVELOPMENT.md` umbrochen, Schrittliste nennt die Betreffprüfung.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md

## Entscheidungen
