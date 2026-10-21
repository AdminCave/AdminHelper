<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness: die Session gibt geplante Vorhaben selbst frei — Task-Ledger
Status: bereit · Branch: feature/harness-self-approve · Review: pro Task
Spec: docs/features/harness-self-approve.md (Roadmap R-0567)
Heavy: none — Regel- und Skill-Texte, `scripts/dev/roadmap.py` (Python-Stdlib) und Shell-Tests unter `scripts/` mit hermetischen Fixtures; kein Stack-, Gateway-, PKI-, Compose- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Harness-Vorhaben auf Kevins Wort vom 2026-10-21 (CLAUDE.md §4). Jede Task berührt Harness-Pfade: zum `reviewer`
kommt `security` (`review.sh risk`). Die neuen Texte stehen wörtlich in der Spec, Abschnitt „Neue Texte“; die Tasks
übernehmen sie und brechen um wie der Bestand. Zeilenangaben origin/main@82e4a7b8, beim Bau neu greppen.

### T1 — roadmap.py: `approve` behält die Notiz der Zeile  [x]
Komponente: scripts · Dateien: scripts/dev/roadmap.py, scripts/dev/tests/test_roadmap.py, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @8a69747e 2026-10-21T10:08:28+02:00
Review: approve (.ah-out/review/harness-self-approve/T1.verdict.json)
Änderung: Zuerst der Test `test_approve_and_revoke_keep_the_note` in `test_roadmap.py`: eine Zeile mit der Status-Spalte `geplant (Semantik-Frage: x)` steht nach `approve` als `freigegeben (Semantik-Frage: x)` im Abschnitt „Geplant“, nach `approve --revoke` wieder als `geplant (Semantik-Frage: x)`, `lint` ohne Fund; auf HEAD dreimal identisch rot (die Spalte ist danach `freigegeben`). Dann `cmd_approve` (`scripts/dev/roadmap.py:730-742`): das Statuswort wird ersetzt, der Text dahinter in der Status-Spalte bleibt wörtlich, in beide Richtungen. Hilfetexte `:16` und `:1152`, dazu `DEVELOPMENT.md:600`, nach der Spec. `test_approve_and_revoke` und `test_approve_only_from_geplant_and_revoke_only_from_freigegeben` bleiben unverändert grün. Der neue Test läuft im Schritt `scripts/dev pytest` desselben Laufs; `-- session_status_test` engt nur den Shell-Block ein (der Test ruft `roadmap.py show --wip`).
Beweis: origin/main@82e4a7b8 · `roadmap.main(["--file", <Fixture mit R-0003 „geplant (Semantik-Frage: x)“>, "--today", "2026-09-25", "approve", "R-0003"])` → Status-Spalte `freigegeben`, die Notiz ist weg; Ursache `scripts/dev/roadmap.py:737` `roadmap.set_status(args.id, new, None, args.today)`
HEAD: 82e4a7b8
Verify: bash scripts/dev/verify.sh scripts --strict -- session_status_test
Doku: DEVELOPMENT.md („Die Roadmap als Skript“, `approve`)

### T2 — CLAUDE.md und tasks/README.md: die Session gibt nach dem Plan-Commit selbst frei  [x]
Komponente: scripts · Dateien: CLAUDE.md, tasks/README.md, CHANGELOG.md, docs/features/harness-self-approve.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @91680e41 2026-10-21T10:23:15+02:00
Review: approve (.ah-out/review/harness-self-approve/T2.verdict.json)
Änderung: Die Texte der Spec für CLAUDE.md §2 (`:24-27`), §4 (`:61-65`), §8 (`:127`), §11 (`:171`) und `tasks/README.md` (`:21`, `:88-89`); der CHANGELOG-Eintrag der Spec oben unter `## [Unreleased]` → `### Changed` (umlautfrei). Kein neuer Test: reiner Regeltext ohne Code; den mechanischen Teil der neuen Regel (`[?]` im Plan, `aktiv` nur mit offener `[ ]`-Task) prüft der Test aus T3. Prüf-grep danach leer (heute sechs Treffer): `grep -n -E 'Freigabe eines Plans|freigegeben \(nur Kevin\)|er tippt .*approve|eine Freigabe setzen|Kevins .roadmap.py approve.|den Kevin liest' CLAUDE.md tasks/README.md`.
Verify: bash scripts/dev/verify.sh scripts --strict -- ledger_test
Doku: CHANGELOG (Changed); CLAUDE.md und tasks/README.md sind selbst die Regeln
Abhängt von: T1

### T3 — /feature-plan und /feature-build: Freigabe am Gate, Fragen-Tasks aus dem Gate, Notiz bei `status`  [x]
Komponente: scripts · Dateien: .claude/skills/feature-plan/SKILL.md, .claude/skills/feature-build/SKILL.md, scripts/tests/ledger_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ee216de0 2026-10-21T10:32:58+02:00
Review: approve (.ah-out/review/harness-self-approve/T3.verdict.json)
Änderung: Die Texte der Spec für feature-plan (`:3`, `:10`, `:69`, `:118-121`, `:137`, `:139-142`) und feature-build (`:3`, §2 `:27-31` samt dem Satz zur Notiz unter der Liste, §3 vor `:66`, §4.1 `:70-71`). `ledger_test.sh` bekommt im Abschnitt „lint“ den Gate-Weg als Fall: ein Ledger mit `Status: geplant`, dessen eine Task per `ledger.sh mark-question` auf `[?]` steht, lintet sauber (Exit 0); derselbe Ledger mit `Status: aktiv` und nur noch `[?]`-Tasks, keiner `[ ]`, ist Exit 1 mit „no open [ ] task left“, der Grund, warum eine Zeile, deren Tasks alle an Kevin-Fragen hängen, `geplant` bleibt. Prüf-grep danach leer (heute sieben Treffer): `grep -n -E 'menschlichen Freigabe|auf Freigabe warten|Kevin kann beide freigeben|Freigabe ist Kevins|nachdem Kevin die Roadmap-Zeile|! python3 scripts/dev/roadmap.py approve' .claude/skills/feature-plan/SKILL.md .claude/skills/feature-build/SKILL.md`.
Verify: bash scripts/dev/verify.sh scripts --strict -- ledger_test
Doku: keine weitere (die Skill-Texte sind die Anleitung)
Abhängt von: T2

### T4 — /roadmap-Skill und cicd.html: wer annimmt, wer freigibt  [x]
Komponente: scripts · Dateien: .claude/skills/roadmap/SKILL.md, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @e5b32d16 2026-10-21T10:39:30+02:00
Review: approve (.ah-out/review/harness-self-approve/T4.verdict.json)
Änderung: Die Texte der Spec für den roadmap-Skill (`:17-19`, `:80-81`) und die REG-Zeile der Tabelle in `docs/developer/cicd.html:184` und `docs/en/developer/cicd.html:182`, HTML-Entities wie im Bestand. `python3 scripts/dev/doc-smoke.py --paths --env --strict` bleibt Exit 0 (das fährt der CI-Job ops-scripts über die echten Seiten). Kein neuer Test: Regel- und Doku-Text. Prüf-grep danach leer (heute vier Treffer): `grep -n -E 'Freigabe tippt|tippt Kevin selbst|Die Freigabe bleibt Kevins Haken|Releasing it stays' .claude/skills/roadmap/SKILL.md docs/developer/cicd.html docs/en/developer/cicd.html`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html (REG-Zeile)
Abhängt von: T2
