<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Schutz nachziehen (R-0109, R-0110, R-0082) — Task-Ledger
Status: geplant · Branch: harness/schutz-nachziehen · Commit-Granularität: pro Task · Review: pro Task (feature-review; Harness-Pfade ⇒ Reviewer Opus) · Modell: Opus
Spec: docs/features/schutz-nachziehen.md (Roadmap R-0109, R-0110, R-0082)
Heavy: none — nur der PreToolUse-Wächter, die Git-Hooks, review.sh und ihre hermetischen Tests; kein Stack-, Gateway-, PKI- oder Install-Pfad, alles über verify.sh scripts.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-09-30 von der Aufsicht (adminhelper-ac) auf Kevins Wort (Runde A). Bau nur interaktiv in Worker B
(`../AdminHelper-harness-b`), **nach** `dev-tool-pins` und vor `harness-kleinfixes`; mit letzterem teilt sich
dieses Ledger `DEVELOPMENT.md` und `AUTONOMOUS.md` (andere Abschnitte) — nacheinander bauen, rebasen. Keine
Lane: `lane.sh new` legt fest `feature/<slug>` an. Den Wächter nie mit echten Lösch-Kommandos prüfen: jeder
Beweis ist ein JSON-Dokument auf stdin wie in `scripts/tests/hooks_test.sh`. Reviewer-Subagenten bekommen ein
eigenes Verzeichnis aus `mktemp -d -p <Scratchpad>` und löschen nur eigene Pfade mit vollem Pfad.

### T1 — Wächter: ein Glob über der Temp-Wurzel wird verweigert  [ ]
Komponente: scripts · Dateien: scripts/dev/hooks/harness-guard.sh, scripts/tests/hooks_test.sh, DEVELOPMENT.md
Änderung: `reaches_root` (harness-guard.sh:218–228) verweigert zusätzlich, wenn in `comps[:len(rc)]` ein
Glob-Zeichen steht, dieser Präfix per `fnmatch` zur Wurzel passt und `len(comps) >= len(rc)` gilt (Glob über der
Wurzel, beliebig tiefer Treffer). Die bestehende Regel (Treffer genau auf der Wurzel oder eine Ebene darunter)
bleibt; Globs, die erst unter der Wurzel stehen, bleiben frei, wie T10 sie freigab. Docstring nachziehen.
Test (hooks_test.sh, Block bei :532 ff.): verweigert in jedem Modus (interaktiv, `AH_AUTONOMOUS=1`, mit
Kill-Switch) werden `rm -rf /t*/claude-1000/*`, `rm -rf /t*/claude-1000/-home-*/*`, `rm -rf /tm?/claude-*/*`,
`rm -rf /*/claude-1000/*`, `rm -rf /var/t*/x/*`, `cd /t* && rm -rf claude-1000/*`; frei bleiben die gemessenen
Scratchpad-Aufräumer (`:594–610`) und `rm -rf /home/*/x*`.
Beweis: origin/main@8224e84c · `printf '%s' '{"tool_name":"Bash","tool_input":{"command":"rm -rf /t*/claude-1000/*"}}' | env -u AH_AUTONOMOUS -u TMPDIR bash scripts/dev/hooks/harness-guard.sh` → keine Ausgabe (erlaubt); erwartet `"permissionDecision":"deny"` (Explorer der Aufsicht, 2026-09-30)
Dedup-Key: bug:scripts:harness-guard.sh:temp-glob-bypasses · HEAD: 8224e84c
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md „Harness-Schutz und Kill-Switch" (:583–602): ein Satz, dass auch ein Glob über der Wurzel zählt

### T2 — Wächter: `--`, `|&`, `);`, `xargs sh -c`, `grep -l/-L`; Grenzen aufschreiben  [ ]
Komponente: scripts · Dateien: scripts/dev/hooks/harness-guard.sh, scripts/tests/hooks_test.sh, DEVELOPMENT.md, CHANGELOG.md
Änderung: (1) nach `--` zählt jedes Wort als Operand (`words`, :535); (2) `|&` ist ein Pipe-Trenner (`SEPARATORS`,
:131, und die Pipe-Logik bei :572); (3) ein Token aus reiner Interpunktion wie `);` wird vor dem Segmentieren in
seine Operatoren aufgetrennt (nach `tokenize`, :364–374); (4) `xargs` mit einer verschachtelten Shell (`sh`/`bash`
`-c '…'`), deren Kommando löscht, zählt wie `xargs rm` (:551); (5) `grep -l`/`-L` gelten als Lister (:574).
Kopf-Kommentar (:18–26, :56–66) und DEVELOPMENT.md nennen die verbleibenden Grenzen: Prozess-Substitution,
`mapfile`/`readarray`, eine Liste ohne Glob mit Laufzeit-Pfad (`ls /tmp | while read d; do rm -rf /tmp/$d`),
`cat … | xargs rm`.
Test (hooks_test.sh): verweigert `cd /tmp/claude-1000 && rm -rf -- -home-x*`, `ls -d /tmp/tmp.* |& xargs rm -rf`,
`for d in $(ls -d /tmp/tmp.*); do rm -rf "$d"; done`, `ls /tmp/tmp.* | xargs sh -c 'rm -rf "$@"' _`,
`grep -l x /tmp/*.x | xargs rm`; frei bleiben dieselben Formen in einem eigenen Verzeichnis
(`$SP/…`, `/tmp/foo.XXXX/…`) und die bestehende Liste freier Formen (:532–576).
Beweis: origin/main@8224e84c · jede der fünf Formen als JSON auf stdin an den Wächter → frei; Gegenprobe `rm -rf /tmp/tmp.*`, `… | xargs rm`, `rm -rf $(ls -d /tmp/tmp.*)` → verweigert (Explorer der Aufsicht, 2026-09-30)
Dedup-Key: bug:scripts:harness-guard.sh:temp-glob-bypasses · HEAD: 8224e84c
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (:583–602, „Nicht erfasst"); CHANGELOG [Unreleased] Changed: der Temp-Wächter erkennt mehr Formen
Abhängt von: T1

### T3 — Commit-Hooks auch bei merge, cherry-pick, revert und rebase; `chmod` als Schreib-Verb  [ ]
Komponente: scripts · Dateien: scripts/dev/hooks/prepare-commit-msg, scripts/dev/hooks/pre-merge-commit, scripts/dev/harness.sh, scripts/dev/hooks/harness-guard.sh, scripts/tests/review_scripts_test.sh, scripts/tests/hooks_test.sh, DEVELOPMENT.md, AUTONOMOUS.md, CHANGELOG.md
Änderung: Zwei neue Hooks (Modus 100755, SPDX-Kopf wie `pre-commit`), beide
`exec bash "$ROOT/scripts/dev/review.sh" sec --staged`; der Kopf-Kommentar von `prepare-commit-msg` sagt, dass
der Sequencer ihn undokumentiert ruft (git 2.47.3 gemessen) und der Test das bewacht. `harness.sh status`
(`precommit_line`, :47–59) prüft alle drei Hooks auf Ausführbarkeit und nennt fehlende einzeln. Der Wächter zählt
`chmod`, `chown`, `chgrp` auf einen Pfad als Schreiben (Harness-Regel: autonom verweigert, interaktiv gewarnt).
Test: die beiden „known gap"-Fälle (review_scripts_test.sh:767–780) umdrehen — cherry-pick und revert eines
`tasks/sec-*.md` werden verweigert, HEAD bleibt; dazu `merge --no-ff` eines Branches mit sec-Datei (abgebrochen,
kein Merge-Commit) und `rebase` über einen solchen Commit (stoppt mit der sec-Meldung); ein sauberer
cherry-pick und Merge gehen durch. Die Fixture `$HFIX` bekommt alle drei Hooks. hooks_test.sh: `chmod -x
scripts/dev/hooks/pre-commit` mit `AH_AUTONOMOUS=1` → deny; `harness.sh status` meldet einen fehlenden
`pre-merge-commit` als `NOT armed`.
Beweis: origin/main@8224e84c · review_scripts_test.sh:775–780 grün als „known gap" (cherry-pick und revert committen eine sec-Datei); Explorer-Messung git 2.47.3 mit prepare-commit-msg: cherry-pick rc 128, merge rc 1, rebase stoppt
Dedup-Key: bug:scripts:pre-commit:merge-and-bypass-gaps · HEAD: 8224e84c
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md „pre-commit-Hook" (:614–632: drei Hooks, was sie abdecken, die verbleibenden Grenzen aus der Spec, kein Runner-Deny für `.git/**` und warum); AUTONOMOUS.md (:271–273); CHANGELOG [Unreleased] Changed

### T4 — diff-scan: gelöschte Rust-`assert_*!` und Go-`t.Fatal*`/`t.Error*` sind Funde  [ ]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/tests/review_scripts_test.sh
Änderung: Die RA-Regex (review.sh:173) trifft `assert`, `assert_eq!`, `assert_ne!`, `assert_matches!` usw.
(`assert(_[a-z]+)?!?` mit derselben Wortgrenze). In `*_test.go` zählt eine gelöschte Zeile mit
`t.(Fatal|Fatalf|Error|Errorf|Fail|FailNow)(` als RA-Satz; außerhalb von `*_test.go` bleibt `err.Error()` frei.
Der Inhalts-Check mit `Test-Löschung:` (heads(), :247–291) gilt für beide wie für Python.
Test (review_scripts_test.sh, Stil der bestehenden diff-scan-Fälle): gelöschtes `assert_eq!(a, b);` in einem
Rust-Test → rc 3; gelöschtes `t.Fatalf("x")` in `x_test.go` → rc 3; gelöschtes `return err.Error()` in `x.go`
→ clean; der ganze Test samt Kopf mit `Test-Löschung:` → clean.
Beweis: origin/main@8224e84c · Scratch-Repo mit kopiertem review.sh, gelöschtes `assert_eq!`/`assert_ne!` bzw. `t.Fatalf`/`t.Errorf` gestaged, `review.sh diff-scan --staged` → `diff-scan: clean`, rc 0; Gegenprobe gelöschtes `assert v == 1` → rc 3 (Explorer der Aufsicht, 2026-09-30)
HEAD: 8224e84c (die Zeile R-0082 trägt keinen Dedup-Key)
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T5)

### T5 — diff-scan: fehlende Skip-Muster und ein nacktes `return` in einem Test  [ ]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/tests/review_scripts_test.sh, DEVELOPMENT.md, CHANGELOG.md
Änderung: `SKIP_PATTERNS` (:51–52) bekommt `describe.skip(`, `.skipIf(`, `.todo(`, `xdescribe(`, `xtest(`,
`test.fixme(`, `it.only(`, `test.only(`, `describe.only(`, `t.SkipNow(`, `@pytest.mark.xfail`, `pytest.xfail(`;
`#[ignore]` wird zum Präfix `#[ignore` (trifft auch `#[ignore = "…"]`). Neuer Satz: eine **hinzugefügte** Zeile,
die nur `return` ist (Python, Go, Rust `return;`, TS/JS `return;`), innerhalb der Spanne eines Tests im neuen
Stand (heads(), :247–291) ist ein Fund; `review: ok <grund>` auf der Zeile hebt ihn auf wie jeden anderen.
Kopf-Kommentar von review.sh (:16–26) nennt die Klassen.
Test: je Muster ein hinzugefügter Fall → rc 3 mit dem Muster in der Ausgabe; `return` in einem Python-, Go-, Rust-
und TS-Test → rc 3; `return` in einer Nicht-Test-Funktion derselben Datei → clean; mit `# review: ok <grund>` →
clean; `sys.exit(` bleibt frei (Wortgrenze, bestehender Fall).
Beweis: origin/main@8224e84c · `describe(` → `describe.skip(` und ein eingefügtes `return` im Python-Test gestaged → `diff-scan: clean`; ebenso `#[ignore = "flaky"]`, `xdescribe(`, `it.todo(`, `it.only(`, `t.SkipNow()`, `@pytest.mark.xfail` (Explorer der Aufsicht, 2026-09-30)
HEAD: 8224e84c (die Zeile R-0082 trägt keinen Dedup-Key)
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md „Task schliessen" (:419–421: was diff-scan erkennt, der Ausweg `review: ok`; Doku-Zeilen, die ein Muster zitieren, tragen `<!-- review: ok … -->` wie DEVELOPMENT.md:606); CHANGELOG [Unreleased] Changed
Abhängt von: T4
