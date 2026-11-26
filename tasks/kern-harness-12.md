# Harness: Texte, heavy.sh, clippy, review.sh risk, approve und Test-Loeschung — Task-Ledger
Status: aktiv · Branch: feature/kern-harness-12 · Review: pro Task
Spec: docs/features/kern-harness-12.md (Roadmap R-0441, R-0578, R-0579, R-0580, R-0745, R-1096, R-1123, R-1754, R-1755)
Heavy: none — Harness-Skripte und Texte; heavy.sh wird hermetisch in heavy_test.sh geprueft, clippy laeuft in der PR-CI
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- Kevin 2026-11-25 (Notiz jeder Zeile): „faellig, Harness-Pfad freigegeben, Session baut und merged kern-harness-12“ —
  deckt die Harness-Pfade dieses Zugs und den Merge, auch `.github/workflows/ci.yml` aus R-1096 (die Zeile nennt
  `ci.yml` in ihrer Quelle).
- R-1753 und R-1189 fahren nicht mit (verschoben 2026-11-26: kern-harness-11 bzw. kern-ruff-1).
- T3: `cargo clippy --all-targets -- -D warnings` fand im Testcode nichts; keine Rust-Datei aendert sich. cicd.html nennt nur `fmt`/`clippy`/`test`, keinen Aufruf: keine Doku-Aenderung; geaendert sind nur run.sh und ci.yml.

### T1 — Texte: frps-Image im test-Skill, Pflicht-Checks in feature-build und cicd  [x]
Komponente: scripts · Dateien: .claude/skills/test/SKILL.md, .claude/skills/feature-build/SKILL.md, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @c7aff3129 2026-11-26T11:10:55+01:00
Review: approve (.ah-out/review/kern-harness-12/T1.verdict.json)
Änderung: test/SKILL.md nennt frps als lokal gebautes `adminhelper-test/frps` (aus `apps/frps`, `docker-compose.test.yml`). feature-build §4.7 und cicd.html DE+EN: Pflicht sind die Checks aus `ci.yml`; `nightly.yml` laeuft bei eigener Aenderung auch auf PRs, ist dort nicht Pflicht.
Beweis: Dedup-Key REF:harness:SKILL.md:test_frps_image (R-0441), R-1754
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html

### T2 — heavy.sh: geleaste GUI-Box nach totem Job festhalten, gueltige REG-Slugs  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @aa5ef4b29 2026-11-26T11:21:47+01:00
Review: approve (.ah-out/review/kern-harness-12/T2.verdict.json)
Änderung: part_job schreibt nach erfolgreichem `warm_lease` die Stage `leased`; die Auswertung setzt bei `leased` (wie bei `run`) `GUI_HELD=1` und meldet den Teil als infra. `reg_finding` bildet den Slug kleingeschrieben und kuerzt den Namen `reg-<datum>-<slug>` auf hoechstens 40 Zeichen ohne Bindestrich am Ende. Tests: toter Job nach Lease → Box freigegeben bzw. notiert; Schrittname mit Grossbuchstaben und Ueberlaenge → Slug besteht die Pruefung aus `worktree-setup.sh`.
Beweis: R-0745, R-1123 (reg-2026-11-03-backup-restore-crown-jewel-DR, 42 Zeichen)
Verify: bash scripts/dev/verify.sh scripts --strict -- heavy_test
Doku: keine (interne Harness-Logik, kein dokumentiertes Verhalten)

### T3 — clippy mit --all-targets in run.sh und CI  [x]
Komponente: desktop-rs · Dateien: scripts/tests/run.sh, .github/workflows/ci.yml, docs/developer/cicd.html, docs/en/developer/cicd.html (dazu die Rust-Dateien unter apps/desktop/src-tauri/, die clippy im Testcode beanstandet; per set-files nachgetragen), CONTRIBUTING.md, CLAUDE.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @57a62e02c 2026-11-26T11:23:41+01:00
Review: approve (.ah-out/review/kern-harness-12/T3.verdict.json)
Änderung: `cargo clippy --all-targets -- -D warnings` in `run.sh` (desktop-cargo) und im CI-Job Desktop-Backend; die Funde im Testcode beheben, ohne einen Test abzuschwaechen.
Beweis: Dedup-Key ref:harness:scripts/tests/run.sh:desktop-cargo (R-1096)
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html (nur falls dort der clippy-Aufruf steht)

### T4 — review.sh risk: --range A..B ab der Merge-Base  [x]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/tests/review_scripts_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b6d08ffb0 2026-11-26T11:29:04+01:00
Review: approve (.ah-out/review/kern-harness-12/T4.verdict.json)
Änderung: `risk --range A..B` und `A...B` diffen ab `git merge-base A B`; die Musterliste kommt weiter vom Basis-Stand. Test: main rueckt nach dem Abzweigen mit einer Risikodatei vor → `risk --range main..branch` zaehlt sie nicht.
Beweis: R-1755
Verify: bash scripts/dev/verify.sh scripts --strict -- review_scripts_test
Doku: keine (Verhalten entspricht der dokumentierten Absicht von --range)

### T5 — roadmap.py approve: Ledger, Plan-Branch und Kevins Marke  [x]
Komponente: scripts · Dateien: scripts/dev/roadmap.py, scripts/dev/tests/test_roadmap.py, CLAUDE.md, .claude/skills/feature-plan/SKILL.md, .claude/skills/feature-build/SKILL.md, .claude/skills/roadmap/SKILL.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @bdcdaa9c3 2026-11-26T11:33:11+01:00
Review: approve (.ah-out/review/kern-harness-12/T5.verdict.json)
Änderung: `approve` verweigert (Exit ≠ 0, Grund auf stderr) eine Zeile ohne Spalte `Ledger`, ohne Branch `feature/<slug>` (lokal oder `origin`) und ohne `Kevin JJJJ-MM-TT` in der Notiz. Regeltext in CLAUDE.md §4 und den drei Skills: ein diktiertes Vorhaben bekommt am Gate die Notiz `Kevin JJJJ-MM-TT: diktiert`. Tests je Verweigerungsgrund und der Erfolgsfall.
Beweis: R-0580, R-0579 (Details privat)
Verify: bash scripts/dev/verify.sh scripts --strict -- ledger_test
Doku: CLAUDE.md, .claude/skills/ (Ablauf-Regeln)

### T6 — ledger.sh lint: Test-Loeschung unter Risikopfad braucht Kevins Entscheidung  [ ]
Komponente: scripts · Dateien: scripts/dev/ledger.sh, scripts/tests/ledger_test.sh, tasks/README.md, .claude/skills/feature-plan/SKILL.md
Änderung: Nennt eine `Test-Loeschung:` eine Datei, die ein Muster aus `scripts/dev/review-risk.txt` trifft, verlangt `lint` die Task auf `[?]` oder eine Zeile `Kevin JJJJ-MM-TT:` mit dem Dateinamen in `## Entscheidungen`. Tests: Risikopfad ohne Entscheidung rot, mit `[?]` gruen, mit Entscheidung gruen, Nicht-Risikopfad gruen.
Beweis: R-0578 (Details privat)
Verify: bash scripts/dev/verify.sh scripts --strict -- ledger_test
Doku: tasks/README.md, .claude/skills/feature-plan/SKILL.md
