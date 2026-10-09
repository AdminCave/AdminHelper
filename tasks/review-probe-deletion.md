<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# review-probe: eine reine Entfernung mit angekündigter Test-Löschung sperrt kein approve (R-0227) — Task-Ledger
Status: aktiv · Branch: harness/review-probe-deletion · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-09 (Harness-Kleinpaket aus R-0227, von Kevin am 2026-10-08 in der Triage als „zuerst“ angenommen; Delegation Kevin 2026-10-05; den PR merged Kevin). Entscheidungen: 1, 2, 4, 5, 6 wie empfohlen; 3 abweichend: `only-declared-deletion` wird nicht still angenommen, die Review-/Verdict-Zeile im Ledger nennt den Grund sichtbar (etwa „Probe: nur angekündigte Löschung“), weil das Paket ein Gate lockert
Spec: Roadmap R-0227 (Kurz-Ledger ohne Spec)
Heavy: none — Shell und Python unter scripts/dev mit hermetischen Tests, dazu Harness-Doku; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-09 von Worker A für die Aufsicht (adminhelper-ac); Kevin hat R-0227 am 2026-10-08 in der Triage als
„Harness-Kleinpaket, zuerst“ angenommen. Zeilenangaben main@b64253ca; beim Bau an Symbolen orientieren.

Befund: `review-probe.sh` legt nur die Test-Hunks auf die Basis und fragt, ob der neue Test ohne die Änderung rot
wäre. Bei einer reinen Entfernung — toter Code geht samt seinem Test, angekündigt als `Test-Löschung:` — besteht der
Test-Diff nur aus dieser Löschung: ohne die Änderung ist nichts rot, die Antwort ist `applicable: true,
red_without_change: false`, und `check-verdict` (`review.sh:1092`) sperrt das approve des Reviewers. Die Probe kennt
die Task nicht: `task-close.sh:406` ruft sie nur mit `--staged`. Eine reale Entfernung nimmt auch die Importe mit,
die nur der gelöschte Test brauchte (im Beweis `from datetime import datetime`), und die Leerzeilen davor.

Entwurf (für alle drei Tasks):
- `review.sh declared-only <component> (--staged | --commit <rev>) --task <ledger> <id>` beantwortet, ob der Diff
  unter den Testpfaden der Komponente (`component_tests`, `review.sh:142`) nur eine angekündigte Löschung ist:
  Exit 0, wenn er keine einzige hinzugefügte Zeile hat und jede entfernte Zeile entweder in der alten Spanne eines
  Tests liegt, den die Task als `Test-Löschung:` ankündigt und der nach den Regeln von `diff-scan` zählt (Grund,
  eindeutiger Name, wirklich weg, ganz weg — dieselben `declared()`/`heads()`, `review.sh:491`/`:435`), oder leer
  ist, oder eine Import-Zeile (Python `import …`/`from … import …`, Go-Importe, JS/TS `import … from`); sonst
  Exit 1. Die Ankündigung kommt wie bei `diff-scan` aus dem committeten Ledger: `HEAD` bei `--staged`, `<rev>` bei
  `--commit`.
- Gegenprobe, ausdrücklich: ein Test-Diff, der neben der angekündigten Löschung etwas anderes ändert — eine
  hinzugefügte Zeile (auch ein Ersatztest, tasks/README.md „Passt“), eine entfernte Zeile eines bleibenden Tests,
  ein entfernter Helfer oder eine Fixture —, ist keine reine Löschung: die Probe läuft wie bisher. Sonst würde
  `Test-Löschung:` zum Freifahrtschein.
- `review-probe.sh … --task <ledger> <id>`: ist der Test-Diff eine reine Löschung, antwortet die Probe ohne Lauf
  `{"applicable": false, "reason": "only-declared-deletion", "red_without_change": null}`. `task-close.sh` gibt
  `--task` mit. `--mutate` bleibt unberührt (der Mutant sitzt auf der ganzen Änderung).
- `check-verdict` (`review.sh:1099`) wertet `only-declared-deletion` wie `no-test-change`: kein Hindernis, keine
  Notiz „probe not run“.
- Nicht in diesem Ledger: Shell-Tests (`heads()` kennt Python, Go, JS/TS und Rust; eine Löschung in
  `scripts/tests/*.sh` wird weiter geprobt), ein entfernter Helfer, den nur der gelöschte Test nutzte (bleibt
  geprobt; ein Fall dafür wird eine eigene Zeile, wenn er auftritt).

Semantik: `DEVELOPMENT.md:556–558` „kein approve mit einem `blocker`, keins, wenn die Probe den neuen Test ohne die
Aenderung gruen fand“ — die Sperre gilt dem **neuen** Test; eine reine angekündigte Löschung bringt keinen. Und
`tasks/README.md:132` „**Passt:** toter Code geht samt seinem Test“ — der Fall, den `Test-Löschung:` erlaubt; das Gate
soll ihn nicht an einer Probe scheitern lassen, die für ihn keine Frage hat.

### T1 — review.sh: `declared-only` und `check-verdict` für `only-declared-deletion` (R-0227)  [x]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/tests/review_scripts_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @8f9e2a06 2026-10-09T09:48:24+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Das Verb `declared-only` nach dem Entwurf, mit `declared()`/`heads()` des Python-Teils von `diff-scan`,
nicht mit einer zweiten Kopie der Spannen-Logik; die Usage im Kopf von review.sh nennt es. `check-verdict`
(`:1099`) nimmt `only-declared-deletion` in die Gründe ohne Notiz. Tests in `review_scripts_test.sh` an einem
Fixture-Repo: die Form des Beweises (ein angekündigter Test samt seinem Import und den Leerzeilen davor, dazu die
Entfernung im Code) ⇒ Exit 0; Gegenproben ⇒ Exit 1: dieselbe Löschung plus eine hinzugefügte Zeile (ein
Ersatztest), plus eine entfernte Assertion eines bleibenden Tests, plus ein entfernter Helfer; eine Löschung ohne
Ankündigung; eine Ankündigung ohne Grund; ein angekündigter Test, dessen Rumpf teilweise bleibt; eine Ankündigung nur
im Arbeitsbaum, nicht committet. `--commit <rev>` liest die Ankündigung aus dem Ledger dieses Commits.
`check-verdict` mit einem approve und `{"applicable": false, "reason": "only-declared-deletion"}` ⇒ brauchbar, ohne
„probe not run“ (die Schleife `review_scripts_test.sh:2175`).
Rot vorher: die neuen Tests scheitern auf main (kein Verb `declared-only`, Exit 2; `check-verdict` notiert
„probe not run: only-declared-deletion“).
Beweis: main@b64253ca · Bau server-kleinkram-1 T2 (Commit `d2a0c4c4`, Worker B, 2026-10-07; als Handcommit auf Kevins Wort geschlossen) · `bash scripts/dev/review-probe.sh server --commit d2a0c4c4 -- tests/test_enrollment_mint.py` mit `ruff` auf dem PATH → `{"applicable": true, "reason": "", "red_without_change": false}` (der Test-Diff ist nur die angekündigte Löschung samt Import, ohne die Änderung 12 passed); `check-verdict` sperrt damit jedes approve (`review.sh:1092`)
Dedup-Key: bug:scripts:review-probe.sh:declared-deletion
HEAD: b64253ca
Verify: bash scripts/dev/verify.sh scripts --strict

### T2 — review-probe.sh `--task` und task-close: keine Probe für eine reine Löschung (R-0227)  [ ]
Komponente: scripts · Dateien: scripts/dev/review-probe.sh, scripts/dev/task-close.sh, scripts/tests/review_probe_test.sh, scripts/tests/task_close_test.sh
Änderung: `review-probe.sh` nimmt `--task <ledger> <id>`; nach den Antworten ohne Lauf (`no-test-change`,
`only-test-change`, `:181`) fragt es `review.sh declared-only` mit derselben Komponente und demselben Modus und
antwortet bei Exit 0 ohne Lauf mit `only-declared-deletion`; Exit 1 heißt: wie bisher proben. Der Kopf
(`:32–43`) nennt den Grund. `task-close.sh` (`:406`) gibt `--task "$LEDGER" "$ID"` mit. Tests:
`review_probe_test.sh` — eine reine angekündigte Löschung ⇒ `only-declared-deletion` und kein Aufruf von verify.sh;
Gegenprobe: dieselbe Löschung plus eine andere Änderung im Test-Diff ⇒ die Suite läuft; ohne `--task` läuft sie wie
bisher. `task_close_test.sh` — der Fund selbst: Code entfernt, Test als `Test-Löschung:` committet angekündigt, der
Reviewer-Stub sagt approve ⇒ task-close schließt (Exit 0) statt Exit 3 „probe found the new test green“; die
Gegenprobe mit einer zusätzlichen Test-Änderung endet weiter mit Exit 3.
Rot vorher: die neuen Fälle scheitern auf dem Stand von T1 ohne diese Änderung (die Probe kennt `--task` nicht, Exit 2).
Verify: bash scripts/dev/verify.sh scripts --strict
Abhängt von: T1

### T3 — Doku: was die Probe bei einer angekündigten Löschung tut (R-0227)  [ ]
Komponente: scripts · Dateien: tasks/README.md, DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md
Änderung: `tasks/README.md`, Abschnitt `Test-Löschung:` (`:86`): ein Satz, dass die Probe einen Test-Diff, der nur
aus angekündigten Löschungen (samt ihren Importen und Leerzeilen) besteht, als `only-declared-deletion` nicht
probt, und dass alles daneben — ein Ersatztest, eine Änderung an einem bleibenden Test — weiter geprobt wird.
`DEVELOPMENT.md` (`:556–567`): der neue Grund in der Liste der Probe und bei `check-verdict`, dazu `declared-only`
als eigener Punkt der Liste ab `:545`. `docs/developer/cicd.html` und `docs/en/developer/cicd.html` (der Satz
„Probe: … ohne Teständerung oder nur mit Tests ist sie nicht anwendbar“, DE `:299`, EN `:293`): auch eine reine
angekündigte Löschung. CHANGELOG `[Unreleased]` → Fixed.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: das ist die Doku-Task (DE und EN der cicd-Seite im selben Commit)
Abhängt von: T1, T2
