<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Kleinfixes: Verify-Zeile, REG-Ledger, Doku-Drift — Task-Ledger
Status: erledigt · Branch: harness/harness-kleinfixes · Commit-Granularität: pro Task · Review: am Ende (Harness-Pfade ⇒ Reviewer Opus) · Modell: Opus
Freigabe: Kevin, 2026-09-30 („alle freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: docs/features/harness-kleinfixes.md (Roadmap R-0104, R-0119, R-0111)
Heavy: none — nur Harness-Skripte, ihre hermetischen Tests und Doku; kein Stack-, Gateway-, PKI- oder Install-Pfad, keine VM.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-09-30 von der Aufsicht (adminhelper-ac) auf Kevins Wort.
Branch `harness/`, weil `verify.sh`, `task-close.sh`, `heavy.sh` und `AUTONOMOUS.md` Harness-Pfade sind:
Bau interaktiv, keine Lane. Worker B baut dieses Ledger **nach** `harness/schutz-nachziehen`: beide ändern
DEVELOPMENT.md und AUTONOMOUS.md (andere Abschnitte), also seriell und vor dem Merge die Kombination prüfen.

### T1 — `verify.sh` nimmt mehrere Komponenten, `task-close.sh` fährt die Verify-Zeile, wie sie dasteht  [x]
Komponente: scripts · Dateien: scripts/dev/verify.sh, scripts/dev/task-close.sh, scripts/tests/verify_test.sh, scripts/tests/task_close_test.sh, DEVELOPMENT.md, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @e557168c 2026-09-30T17:20:08+02:00
Review: Review am Ende (Kurz-Ledger, Opus über den Branch-Diff)
Änderung: `verify.sh` (Argument-Schleife `:45–55`) nimmt mehrere Komponenten und reicht sie an
`run.sh quick --only a b` weiter (`:109–113`); mehrere Komponenten plus `-- args` ist Exit 2 mit klarer
Meldung, `all` bleibt allein gültig. `last-verify.json` trägt im Feld `component` die Liste.
`task-close.sh` (`:184–196`) liest die Komponentenliste aus einer Verify-Zeile in der Form
`bash scripts/dev/verify.sh <a> [<b> …] --strict [-- args]` oder `bash scripts/tests/run.sh <layer> --strict --only <a> [<b> …]`
und ruft `verify.sh <liste> --strict`; enthält die Liste die `Komponente:` der Task nicht, ist das Exit 2.
Prosa-Zeilen behalten den heutigen Rückfall auf die Task-Komponente samt Hinweis. Die Evidenz (`:276–289`)
nennt die gelaufenen Komponenten, z. B. `run.sh[quick] web desktop-e2e: … passed, … failed, … skipped`.
DEVELOPMENT.md Abschnitt „Schnelltest einer Komponente: verify.sh“ (`:205ff`) und der `task-close.sh`-Absatz
beschreiben die Liste und die Evidenz-Form.
Test: `task_close_test.sh` bekommt nach dem Prosa-Fall (`:333–347`) einen Fall mit
`Verify: bash scripts/tests/run.sh quick --strict --only web desktop-e2e` bei `Komponente: web` → erwartet
in `.ah-out/verify-called.txt` `web desktop-e2e --strict` (heute `web --strict`), dazu `--only scripts` bei
`Komponente: web` → Exit 2. `verify_test.sh:84` („second component -> exit 2“) wird zu „zwei Komponenten →
run.sh quick --only server web“, dazu zwei Komponenten plus `--` → Exit 2.
Beweis: origin/main@8224e84c · Ledger stufe-5c T2 (Worker 5c, 2026-09-27): Verify `--only web desktop-e2e`,
Evidenz `run.sh[quick]` nur `web`; der neue task_close-Fall ist gegen das heutige `task-close.sh` rot.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (verify.sh-Liste, Evidenz-Form); CHANGELOG [Unreleased] Changed

### T2 — Das REG-Ledger aus `heavy.sh` hat die Form von `/feature-plan --kurz`  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, tasks/README.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @89eea107 2026-09-30T17:29:35+02:00
Review: Review am Ende (Kurz-Ledger, Opus über den Branch-Diff)
Änderung: `write_reg_ledger` (`scripts/tests/heavy.sh:640–673`) schreibt `Branch: feature/$1` statt `fix/$1`
(`:653`; `$1` ist der Ledger-Name, also derselbe Slug, den das `--kurz`-Gate als `feature/<slug>` anlegt).
Der Schritt-Befehl `bash scripts/tests/run.sh all --strict --step "<schritt>"` wandert aus der Task-`Verify:`
(`:664`) in die Begründung der `Heavy: linux-full — …`-Zeile (`:655`). Die Task-`Verify:` wird zum Platzhalter
`bash scripts/dev/verify.sh <komponente> --strict`, den `/feature-plan --kurz` mit der Komponente füllt.
`tasks/README.md:178–186` (Absatz `reg-<datum>-<schritt>.md`) beschreibt Branch, Heavy-Zeile und Platzhalter.
Test: `heavy_test.sh` (REG-Block `:516–540`) prüft zusätzlich `Branch: feature/reg-…` im Kopf, den
`--step`-Befehl in der `Heavy:`-Zeile und die Platzhalter-`Verify:`; der vorhandene `ledger.sh lint`-Check
(`:537`) bleibt grün. Die neuen Asserts sind gegen das heutige `heavy.sh` rot.
Beweis: origin/main@8224e84c · `heavy.sh:653` `Branch: fix/$1`, `:664` schwere Verify in der Task; feature-build
(`SKILL.md` „Vor dem Start“) forkt einen fehlenden Branch von main — der Plan-Commit auf `feature/<slug>` fehlte
dort (aus dem Skill-Text abgeleitet, nicht live geprüft).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: tasks/README.md (REG-Ledger-Absatz)

### T3 — Doku-Drift: die Git-Verben stehen nicht mehr unter `ask`  [x]
Komponente: scripts · Dateien: DEVELOPMENT.md, AUTONOMOUS.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @65fc0776 2026-09-30T17:34:20+02:00
Review: Review am Ende (Kurz-Ledger, Opus über den Branch-Diff)
Änderung: Nur Text. `DEVELOPMENT.md:413–414` („`git add` steht seit Stufe 4 unter `ask`“), `:449–451` und
`AUTONOMOUS.md:252–254` sagen künftig, was gilt: `git add|commit|checkout|restore|stash` sind in den
Runner-Settings hart verboten, in Kevins Sessions frei (eine Abfrage, die immer bestätigt wird, hielt nur den Bau
auf), committet wird über `task-close.sh`; unter `permissions.ask` stehen nur `bootstrap_linux.sh`,
`harness.sh off` und `ledger.sh mark-done`. Der historische Satz in `docs/features/harness-stufe-4.md` bleibt.
Beweis: origin/main@8224e84c · `.claude/settings.json` `permissions.ask` hat drei Einträge (ohne Git-Verben);
`scripts/tests/hooks_test.sh:998–1012` hält `never_ask = {git add, commit, checkout, restore, stash}` fest.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md, AUTONOMOUS.md (die Task ist die Doku)

### T4 — Nachbesserungen aus dem Gesamt-Review: Verify-Parsing am Commit-Gate, Doku  [x]
Komponente: scripts · Dateien: scripts/dev/task-close.sh, scripts/tests/task_close_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @7e0054ee 2026-09-30T18:00:00+02:00
Review: approve (opus, focused review of T4 after the Kurz-Ledger's final review)
Herkunft: Opus-Gesamt-Review des Kurz-Ledgers (2026-09-30, approve mit nits); am Commit-Gate lohnt die Nachbesserung.
Änderung: (1) task-close.sh nimmt Argumente nur, wenn nach den Komponenten und den Flags `--strict`/`--tree <p>`
direkt `--` folgt — nicht mehr jedes `--` im ersten Befehl (`verify.sh scripts --strict und danach cargo clippy -- -D
warnings` gäbe sonst `-D warnings` weiter; das alte sed verlangte `--strict --`). (2) `all` neben weiteren Komponenten
ist wie der Argument-Fall Exit 2 per `die`, nicht 74 über verify.sh. (3) Der Hinweis für eine `run.sh`-Zeile ohne
`--only` sagt das statt „not a verify.sh call“. (4) Kopfkommentar von task-close.sh: `git add` steht nicht mehr unter
`ask` (hart verboten beim Runner, frei in Kevins Sessions), ebenso der Kommentar in task_close_test.sh. (5)
`docs/developer/cicd.html` und `docs/en/developer/cicd.html`, Abschnitt Verify-Konvention: die Form mit mehreren
Komponenten und die `run.sh … --only`-Form.
Test: task_close_test.sh — Prosa mit `--` nach `--strict` → keine Argumente; `all web` → Exit 2, nichts gelaufen;
`run.sh quick --strict` ohne `--only` → Rückfall mit dem neuen Hinweis.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: cicd.html DE+EN (Verify-Konvention)
Abhängt von: T1
