<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Kleinpaket 1: Werkzeug-Reste, Token-Muster, Test-Hygiene — Task-Ledger
Status: bereit · Branch: harness/kleinpaket-1 · Commit-Granularität: pro Task · Review: auto · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-05 (kleines Fund-Paket aus den in der Triage angenommenen Zeilen R-0165, R-0173, R-0183, R-0185; CLAUDE.md §2 „Entscheidungen“, Delegation Kevin 2026-10-05)
Spec: Roadmap R-0165, R-0183, R-0173, R-0185 (Kurz-Ledger ohne Spec)
Heavy: none — nur Harness-Skripte unter scripts/dev, ihre hermetischen Tests, Kommentare und Doku; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-05 von Worker B im Auftrag der Aufsicht (adminhelper-ac); die Freigabe gibt die Aufsicht (Kevins
Entscheidungs-Aufteilung, 2026-10-05). Kurz-Ledger mit `Review: auto` statt `am Ende` (Aufsicht). Bau interaktiv
(Harness-Pfade), keine Lane. Gemergt erst nach dem Runner-Pilot, damit der Pilot nicht über eine Harness-Änderung auf
`main` stolpert. Die Roadmap-Zeilen liegen im privaten Repo und sind in dieser Worktree nicht lesbar; ihren Status
zieht die Aufsicht nach. Zeilenangaben main@bf9cee5e.

### T1 — `ledger.sh lint` meldet Werkzeug-Reste in Ledger und Spec (R-0165)  [x]
Komponente: scripts · Dateien: scripts/dev/ledger.sh, scripts/tests/ledger_test.sh, tasks/README.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @7c76e197 2026-10-05T18:37:04+02:00
Review: approve (opus/xhigh; 1 nit) · round 1
Änderung: `ledger.sh lint` (`:285`) meldet als ERROR mit Datei:Zeile jede Zeile im Ledger und in der Spec, die sein
`Spec:`-Feld nennt (der erste Pfad unter `docs/features/`, falls die Datei existiert), die einen Rest eines
Werkzeugaufrufs trägt: ein schließendes Tag `content`, `invoke` oder `parameter`, oder ein öffnendes `invoke`- bzw.
`parameter`-Tag mit `name=`. Entschieden gegen `review.sh docs-pairs`: das prüft HTML-Paare unter `docs/`, Spec und
Ledger sind Markdown, und `lint` läuft schon über jedes echte Ledger (`ledger_test.sh`) und am Gate. Tests: ein
Fixture-Ledger und eine Fixture-Spec mit je einem Rest ⇒ ERROR mit Zeile; ohne Rest grün; gewöhnliches HTML in
Markdown (etwa `<details>`, `<!-- … -->`) bleibt grün. Die Fixtures setzen die Tags zur Laufzeit zusammen, damit keine
Datei im Repo den Rest wörtlich trägt.
Beweis: Roadmap R-0165 — ein Plan-Fork kam mit Werkzeug-Resten in Spec und Ledger durchs Gate (runner-vorarbeit-3).
Semantik: keine Stelle in docs/ beschreibt Werkzeug-Reste; `tasks/README.md:72` nennt, was `lint` prüft („Verify-Präfix,
[x] ohne Evidenz, Invariante“) — die Zeile bekommt den neuen Punkt.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: tasks/README.md (die `lint`-Zeile)

### T2 — `review.sh sec` erkennt Token-Muster in hinzugefügten Zeilen (R-0183)  [x]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/tests/review_scripts_test.sh, DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped · contracts: 1 ok @07928a90 2026-10-05T19:03:51+02:00
Review: approve (opus/xhigh; 3 nit) · round 1
Änderung: `sec_scan` und `sec_scan_merge` (`review.sh:672`, `:702`) melden eine hinzugefügte Zeile mit einem
Token-Muster als Treffer, ausgegeben nur als `Datei:Zeile (a token pattern)`, nie mit Inhalt: Proxmox
`<user>@<realm>!<tokenid>=<UUID>` (Proxmox-Wiki „Proxmox VE API“: `PVEAPIToken=USER@REALM!TOKENID=UUID`), die
GitHub-Präfixe `ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_` und `github_pat_` mit einer Mindestlänge (docs.github.com, „About
authentication to GitHub“, Token-Formate) und `sk-ant-` mit einer Mindestlänge (Anthropic-Schlüssel und das Abo-Token
aus `claude setup-token`; die Form steht in keiner offiziellen Doku: nicht verifiziert). Die Mindestlängen lassen die
Platzhalter in Code, Doku und Tests durch (`hooks_test.sh:1250`, `test_vm.py:136`, `redteam_test.sh:522`). Tests:
Fixtures setzen jedes Muster zur Laufzeit zusammen, damit die Testdatei selbst keins trägt; Treffer für `--staged`, für
`--range` und für einen Merge; die Ausgabe enthält den Token-Text nicht; die vorhandenen Platzhalter bleiben clean.
Beweis: `git log --all -E -G '<die Muster>'` über alle Branches: kein Treffer (2026-10-05) — ein Lauf von `sec` über die
ganze Historie (pre-push ohne Tracking-Refs) bleibt grün.
Semantik: `DEVELOPMENT.md:470` „`review.sh sec` (was nie ins oeffentliche Repo darf)“; Kopf von `review.sh` (`:54`):
„is something staged that this public repo must never hold“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Sätze zu `sec` und zum Public repo guard) · docs/developer/cicd.html + docs/en/developer/cicd.html
(was den Public repo guard rot macht) · CHANGELOG.md

### T3 — Test-Hygiene und veraltete Trust-Sätze (R-0173, R-0185)  [x]
Komponente: scripts · Dateien: scripts/tests/review_cli_probe_test.sh, scripts/tests/skill_consistency_test.sh, scripts/dev/runner-setup.sh, tasks/harness-stufe-4.md, scripts/tests/runner_setup_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ae97db6d 2026-10-05T19:51:31+02:00
Review: approve (opus/xhigh; 2 nit) · round 2
Änderung: (a) `review_cli_probe_test.sh` unsettet `CLAUDE_PROJECT_DIR`, damit die Fake-CLI nicht mit dem Projekt der
aufrufenden Session läuft; ein Fall mit gesetzter Variable endet wie ohne. (b) Die Fence-Leser in
`skill_consistency_test.sh` — `head_template` (`:89`) und `build_task_findings` aus Stufe 7a — erkennen eingerückte
Fences; je ein Fixture-Fall mit eingerücktem Fence. (c) `runner-setup.sh:450` („From stage 7 on the runner needs it“)
und die Meldung `:480` sowie `tasks/harness-stufe-4.md:225–229` sagen statt „ab Stufe 7 nötig“, dass der Pilot misst, ob
der Worker den Trust braucht, und dass `--trust` nur `/srv/ah/repo` abdeckt, nicht die Lanes.
Beweis: Roadmap R-0173 und R-0185, aus den Reviews von 7a (T2: eingerückte Fences; 6b/7a: `CLAUDE_PROJECT_DIR` der
aufrufenden Session in der CLI-Probe).
Semantik: `DEVELOPMENT.md`, „Getrusteter Workspace“, Stand nach Stufe 7a (PR #80): „ob er den Trust braucht, misst der
Pilot“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Tests und Kommentare; DEVELOPMENT.md sagt es seit 7a)
Abhängt von: PR #80 (Stufe 7a) gemergt — `build_task_findings` und der Trust-Satz kommen mit 7a; vor dem Bau
`origin/main` hineinmergen

### T4 — Nachbesserung aus dem Branch-Review  [x]
Komponente: scripts · Dateien: .claude/skills/feature-plan/SKILL.md, scripts/tests/skill_consistency_test.sh, scripts/dev/ledger.sh, scripts/tests/ledger_test.sh, scripts/dev/review.sh, scripts/tests/review_scripts_test.sh, scripts/dev/runner-setup.sh, scripts/tests/runner_setup_test.sh, DEVELOPMENT.md, CHANGELOG.md, .github/workflows/ci.yml
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped · contracts: 8 ok @8ff9b6d7 2026-10-06T01:39:15+02:00
Review: approve (opus/xhigh; 1 nit) · round 1
Änderung: Aufsicht 2026-10-05 aus dem `/code-review` über den Branch, je mit Test: (A1) der Gate-Schritt von
`feature-plan` fährt `ledger.sh lint` vor dem Plan-Commit, `skill_consistency_test` hält das fest; (A3) `head_template`
zieht die Einrückung einer eingerückten Fence vom Inhalt ab; (A4) `lint` nimmt den ersten `docs/features/`-Pfad
irgendwo in der `Spec:`-Zeile (auch in Backticks); (A5) ein Token-Rumpf aus höchstens zwei verschiedenen Zeichen ist
ein Platzhalter, kein Token; (A6) Meldung und Kommentar zum Trust in `runner-setup.sh` sagen „Kevin entscheidet“;
(B9) `sec --range` prüft auch die Nachricht jedes Commits mit derselben Muster-Funktion und nennt nur Commit und Art,
nie den Treffer; kein Fehlalarm auf einer gewöhnlichen Merge-Nachricht. A7/A8 nur, wenn sie im selben Zug trivial
abfallen. Nicht hier (Roadmap): die Zeilennummern nach „No newline at end of file“, weitere Werkzeug-Tags, weitere
Proxmox-Formen, ein commit-msg-Hook.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md und CHANGELOG.md, falls B9 die beschriebene Reichweite von `sec` ändert
Abhängt von: T1–T3
