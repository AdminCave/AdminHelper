<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Schutz nachziehen 2 (R-0125, R-0127, R-0133, R-0134, R-0130, R-0132) — Task-Ledger
Status: erledigt · Branch: harness/schutz-nachziehen-2 · Commit-Granularität: pro Task · Review: pro Task (feature-review; Harness-Pfade ⇒ Reviewer Opus) · Modell: Opus
Freigabe: Kevin, 2026-10-02 („Schutz 2 freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: docs/features/schutz-nachziehen-2.md (Roadmap R-0125, R-0127, R-0133, R-0134, R-0130, R-0132)
Heavy: none — nur der PreToolUse-Wächter, review.sh und ihre hermetischen Tests; kein Stack-, Gateway-, PKI- oder Install-Pfad, alles über verify.sh scripts.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-02 von der Aufsicht (adminhelper-ac) aus der Erkundung von Worker B; Entscheidungen Kevin 2026-10-02
(Spec, „Ziel & Nicht-Ziele“). Harness-Pfade ⇒ Bau nur interaktiv, durch Worker B in `../AdminHelper-harness-b`
(eigene Test-DB `adminhelper_test_harness_b`); keine Lane (`lane.sh` legt fest `feature/<slug>` an). Zeilenangaben
main@159d1c97. Wächter-Proben nur als JSON auf stdin wie `scripts/tests/hooks_test.sh`, nie als echte Befehle;
diff-scan-Proben in einem Scratch-Repo mit einer Kopie von `review.sh` wie `scripts/tests/review_scripts_test.sh`.
„Rot vorher“ heißt: heute frei bzw. `diff-scan: clean` gemessen (Worker B, 2026-10-02).

### T1 — Wächter: `[^…]`, Klammer-Expansion und `cd` in einen Glob mit wörtlichem Operand  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/harness-guard.sh, scripts/tests/hooks_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @f1c3dff1 2026-10-02T11:03:28+02:00
Review: approve (opus), nits applied
Änderung: (a) `reaches_root` (`:239–255`) normalisiert vor `fnmatch` `[^` zu `[!` (bash liest beides als Negation).
(b) Operanden werden vor `tmp_glob`/`rel` per Klammer-Expansion aufgelöst: nur Komma-Listen, verschachtelt, auf etwa
32 Ergebnisse gedeckelt; jedes Ergebnis wird geprüft. (c) `tmp_glob` (`:257–270`) prüft „hat Glob“ am aufgelösten
Pfad (cwd plus Wort), nicht nur am Wort, damit ein cwd aus einem Glob (`cd /t*`) zählt.
Rot vorher (verweigert danach, in jedem Modus): `rm -rf /[^x]mp/tmp.*`, `rm -rf /[^x]mp`, `rm -rf /{tmp,x}/tmp.*`,
`rm -rf /{tmp,var}`, `cd /t* && rm -rf claude-1000`. Gegenproben: `[!x]` bleibt verweigert, tiefe Scratchpad-Pfade
und `/home/*/x*` bleiben frei, die bestehende Liste freier Formen in hooks_test.sh bleibt grün.
Grenzen (Kopf + DEVELOPMENT.md): `{1..3}`-Sequenzen und Klammern in Variablen.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md Harness-Schutz (erkannte Formen, Grenzen)

### T2 — Wächter: Wegnehmen eines Vorfahren von Harness-Pfaden  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/harness-guard.sh, scripts/tests/hooks_test.sh, DEVELOPMENT.md, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @56d0cb06 2026-10-02T11:40:23+02:00
Review: request_changes -> fixed -> approve (opus, 2 rounds), nits applied
Änderung: Die Wegnehm-Verben (`rm`, `rmdir`, `shred`, `unlink`; `chmod`/`chown`/`chgrp`; die Quelle von `mv`) und
die Startpfade eines löschenden `find` (`find_delete`, `:276–308`) melden ihre Pfade auf eigenem Weg an die
Shell-Seite; dort trifft ein solcher Pfad auch, wenn er Vorfahr eines Musters aus `harness-paths.txt` ist (ein
Muster beginnt mit `<pfad>/`). Die Repo-Wurzel selbst ist Vorfahr von allem (heute liefert `rel()` für sie `None`,
`:173`). Ein Glob-Operand im Checkout zählt über sein wörtliches Verzeichnis (`glob_dir`, `:228`): `rm -rf ./*`
→ Wurzel, `rm -rf scripts/dev/*` → `scripts/dev`. `rmdir` kommt in den Harness-Zweig (`:707`). Alle anderen
Schreibformen bleiben bei der heutigen Regel (nur der Pfad selbst). Im autonomen Lauf verweigert, interaktiv eine
Warnung wie bei jedem Harness-Pfad.
Rot vorher (mit `AH_AUTONOMOUS=1`): `rm -rf .claude`, `rm -rf scripts/dev/hooks`, `chmod -R -x scripts/dev/hooks`,
`chown -R x .claude`, `rm -rf scripts/dev/*`, `rm -rf ./*`, `rm -rf scripts`, `find scripts -delete`,
`mv scripts/dev /tmp/x`. Gegenproben frei: `rm -f apps/web/dist/*.js`, `chmod -R +x apps/web/scripts`,
`rm -rf apps/web/node_modules`, `cp CLAUDE.md /tmp/x` (Lesen).
Grenzen: `git clean`, Löschen aus Python/anderen Interpretern.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md Harness-Schutz (Vorfahr-Regel, ihr Radius); CHANGELOG (Changed)

### T3 — Wächter: arithmetisches `<<` beginnt kein Here-Doc  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/harness-guard.sh, scripts/tests/hooks_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @4e89bc92 2026-10-02T11:56:28+02:00
Review: approve (opus), one round
Änderung: `logical_lines` (`:479–537`) zählt `((` und `$((` bis zum passenden `))` mit; darin sind `<<` und `<<=`
Operatoren, kein Here-Doc-Beginn (`:518`). Echte Here-Docs (`<<EOF`, `<<-EOF`, `<<'EOF'`) und der Here-String
(`:512`, R-0126) bleiben wie sie sind.
Rot vorher: `echo $((1<<3))` + Zeilenumbruch + `sed -i s/a/b/ CLAUDE.md` (autonom frei), `(( x <<= 1 ))` +
Zeilenumbruch + derselbe `sed` (autonom frei), `echo $((1<<3))` + Zeilenumbruch + `rm -rf /tmp/tmp.*` (interaktiv
frei). Gegenproben: die bestehenden Here-Doc-Fälle (Commit-Nachricht als Here-Doc bleibt frei).
Grenze: ein unquotiertes `let x<<=1` ist auch für bash ein Here-Doc.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Kopfkommentar)

### T4 — Wächter: Eingabe-Umleitungen verlassen das Segment  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/harness-guard.sh, scripts/tests/hooks_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b3acf470 2026-10-02T12:30:47+02:00
Review: request_changes (regression) -> fixed -> approve (opus, 2 rounds)
Änderung: `is_redirect` (`:475–476`) erkennt jedes Operator-Token mit `<` als Umleitung. Bei `<`, `<&` und `<<<`
fällt das nächste Wort weg und wird nicht als geschrieben gemeldet; `<>` schreibt (heute schon über `>`). Die
Schleife in `run_segment` (`:594–604`) behandelt beide Richtungen.
Rot vorher: `< /dev/null rm -rf /tmp/tmp.*` (interaktiv frei), `<<< x tee CLAUDE.md`,
`cp /etc/hosts CLAUDE.md < /dev/null`, `cp /etc/hosts CLAUDE.md <<< x` (autonom frei). Gegenproben bleiben
verweigert: `2>/dev/null rm -rf /tmp/tmp.*`, `exec 3<> CLAUDE.md`; `wc -l < CLAUDE.md` bleibt frei (Lesen).
Grenze: Prozess-Substitution (`<(…)`).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md Harness-Schutz (Grenzen)

### T5 — diff-scan: entfernte Assertions zählen nur, wo Tests stehen  [x]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/tests/review_scripts_test.sh, DEVELOPMENT.md, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @5487f69d 2026-10-02T13:02:55+02:00
Review: request_changes (2 regressions) -> fixed -> approve (opus, 2 rounds)
Änderung: Ein `RA`-Fund (`:174–190`) zählt nur, wenn der Pfad eine Testdatei ist (`tests/`, `e2e/`, `test_*.py`,
`*_test.{py,go,sh}`, `*.test.*`, `*.spec.*`) **oder** die alte Zeile in einer Test-Spanne von `heads()` (`:271`)
liegt. Import-Zeilen (`use …`, `import …`, `from … import …`) zählen nie. Danach darf der zweite `else if`-Zweig
aus #63 (Rust `assert_*!`, Go `t.Fatal*`) in die erste Regel gefaltet werden — nur, wenn der Diff es ohne Umweg
zulässt.
Rot vorher (heute je `rc 3`, Fehlalarm; danach clean): entferntes `use pretty_assertions::assert_eq;` in einer
Datei unter `tests/`, entferntes `o.expect("boom")` in `apps/desktop/src-tauri/src/` außerhalb eines Tests,
entferntes `assert x` in `apps/server/app/helpers.py`. Muss rot bleiben: `assert` in `tests/test_*.py`, `assert!`
in einem inline `#[test]` unter `src/`, `t.Fatalf` in `*_test.go`.
Grenze: Helfer in `#[cfg(test)] mod tests` ohne `#[test]`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (diff-scan: wo entfernte Assertions zählen); CHANGELOG (Changed)

### T6 — diff-scan: weitere Skip-Muster, Rückgaben mit Wert, CRLF  [x]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/tests/review_scripts_test.sh, DEVELOPMENT.md, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @a713b7fb 2026-10-02T13:25:31+02:00
Review: approve (opus, one round; nits on wording, limits and core.autocrlf taken in)
Änderung: `SKIP_PATTERNS` (`:54–57`) bekommt `fit(`, `fdescribe(`, `.runIf(`, `.fails(`, `test.fail(`,
`.skipTest(`, `pytest.importorskip(`; `test.fixme(` wird zu `.fixme(`, damit auch `test.describe.fixme(` trifft. Die
AR-Regel (`:212–216`) schneidet `\r` vor dem Abgleich ab und nimmt zusätzlich `return None`, `return undefined;`
und `return Ok(());`.
Rot vorher (heute je clean): jedes der acht hinzugefügten Muster in einer neuen Zeile; `return None` (py),
`return undefined;` (ts), `return Ok(());` (rs) am Anfang eines Tests; eine CRLF-Datei mit nacktem `return` in
einem Test. Gegenproben: `assert.fail(` bleibt frei, `sys.exit(` und `profit(` bleiben frei (Wortgrenze),
`return None` außerhalb eines Tests bleibt frei.
Grenzen: kein generisches `.fail(`; andere Rückgabewerte.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (diff-scan-Muster); CHANGELOG (Changed)

### T7 — Nachbesserungen aus /code-review: gequotete Operatoren, Glob-Operanden, ((, verschachteltes return  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/harness-guard.sh, scripts/dev/review.sh, scripts/tests/hooks_test.sh, scripts/tests/review_scripts_test.sh, DEVELOPMENT.md, CHANGELOG.md, tasks/README.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @a611cee5 2026-10-02T14:33:11+02:00
Review: approve (opus, two rounds: round 1 request_changes on the nested-function matcher, fixed per language; round 2 approve)
Herkunft: `/code-review` über den Branch-Diff (2026-10-02); nur Regressionen und Fehlalarme, die dieser Branch
selbst eingeführt hat. Neue Umgehungen gingen als Roadmap-Kandidaten an die Aufsicht.
Änderung: (1) Wächter (T4-Regression, immer-an-Regeln): ein Wort, das nur aus gequoteten oder escapten
Operatorzeichen besteht (`"<"`, `'>'`, `\<`), wird vor shlex markiert und bleibt ein Wort; das Zeilen-Merkmal
`lt` und `unquoted_has` entfallen. (2) Wächter (T2): ein Glob-Operand eines wegnehmenden Verbs — auch einer, der
erst über ein `cd` in einen Glob entsteht — wird gegen den echten Baum aufgelöst, jeder Treffer zählt; mit
Variable bleibt der Rückfall über das Verzeichnis. (3) Wächter (T3): ein Kommentar (`#` am Wortanfang) zählt nicht — kein `((`, kein Here-Doc, keine
Quote darin öffnet etwas.
(4) diff-scan (T6): ein `return` in einer verschachtelten Funktion im Test oder ohne folgenden Code zählt nicht;
der Meldetext heißt `early return in a test`. (5) `tasks/README.md` „Test-Löschung“: diff-scan wertet gelöschte
Assertions nur, wo Tests stehen (R-0130).
Rot vorher: `wc -l < notes.txt; git commit -m "<" -n`, `sort < in.txt; rm -rf "<" /tmp/tmp.*` und
`diff <(ls) x; rm -rf '<' /tmp/tmp.*` frei; autonom `rm -f *.log` und `rm -f scripts/tests/*.tmp` verweigert,
`cd scripts/d* && rm -rf hooks` frei; `# see ((a` vor einem Here-Doc mit `rm -rf /tmp/tmp.*` verweigert, `# cat <<X` bzw.
`# it's` vor `rm -rf /tmp/tmp.*` frei;
`return None` in einem verschachtelten Stub und ein letztes `return Ok(());` gemeldet.
Gegenproben: `rm -rf scripts/d*`, `rm -rf ./*`, `rm -rf scripts/$X/*` (autonom) bleiben verweigert;
`if cond:` + `return` mitten im Test bleibt ein Fund; `echo "<" > CLAUDE.md` schreibt weiter CLAUDE.md.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Harness-Schutz, diff-scan); CHANGELOG (Changed); tasks/README.md
