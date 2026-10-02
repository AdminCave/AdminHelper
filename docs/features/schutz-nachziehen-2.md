<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Schutz nachziehen 2: Glob-Formen, Verzeichnisebene, Here-Doc-Fehlleser, diff-scan-Bereich

Roadmap: R-0125, R-0127, R-0133, R-0134, R-0130, R-0132 · Ledger: `tasks/schutz-nachziehen-2.md` ·
Branch: `harness/schutz-nachziehen-2` · Stand: main@159d1c97
Geplant 2026-10-02 von der Aufsicht (adminhelper-ac) aus der Erkundung von Worker B; Entscheidungen Kevin 2026-10-02.

## Problem / Motivation

`schutz-nachziehen` (#63) hat die billigen Lücken des Wächters geschlossen; seine Reviews fanden weitere, die schon
auf main bestehen. Der Wächter (`scripts/dev/hooks/harness-guard.sh`) ist ein Netz gegen Versehen, keine Sandbox —
aber im autonomen Lauf (Stufe 7, Runner) ist er die einzige Sperre vor den Harness-Dateien, und diese Formen gehen
heute durch:

- **Glob-Formen (R-0125).** `reaches_root` (`:239–255`) vergleicht mit Pythons `fnmatch`, das `[^x]` als Literal
  liest; bash liest `^` wie `!`. `rm -rf /[^x]mp/tmp.*` ist frei. Klammer-Expansion (`rm -rf /{tmp,x}/tmp.*`) wird
  nirgends aufgelöst. `tmp_glob` (`:257–270`) prüft „hat Glob“ nur am Wort, nicht am aufgelösten Pfad:
  `cd /t* && rm -rf claude-1000` ist frei, `rm -rf /t*/claude-1000` wird verweigert.
- **Verzeichnisebene (R-0127).** Die Löschzweige schreiben den Pfad des Operanden nach `out` (`rm` `:707`,
  `chmod/chown/chgrp` `:717–731`, `mv`-Quelle `:752`); die Shell-Seite (`match()` `:789–798`) prüft ihn gegen
  `scripts/dev/harness-paths.txt`. Ein Vorfahr eines Harness-Pfads trifft kein Muster: `rm -rf .claude`,
  `rm -rf scripts/dev/hooks`, `chmod -R -x scripts/dev/hooks`, `chown -R x .claude`, `rm -rf scripts/dev/*`,
  `rm -rf ./*` sind im autonomen Lauf frei. `rmdir` steht zwar in `DELETERS` (`:151`, Temp-Regel), aber nicht im
  Harness-Zweig. Ein Glob im Checkout landet als Wort in `rel()`, das für die Repo-Wurzel `None` liefert (`:173–180`).
- **Arithmetisches `<<` (R-0133).** `logical_lines` (`:479–537`) liest jedes `<<` außerhalb von Quotes als Beginn
  eines Here-Docs (`:518`). In `$((1<<3))` oder `(( x <<= 1 ))` ist es ein Operator; der Wächter überspringt danach
  alle folgenden Zeilen eines mehrzeiligen Kommandos — derselbe Mechanismus wie R-0126 (#63).
- **Eingabe-Umleitungen (R-0134).** `is_redirect` (`:475–476`) kennt nur Tokens mit `>`. `<`, `<&`, `<<<` bleiben als
  Wörter im Segment: vor dem Verb verdecken sie es (`< /dev/null rm -rf /tmp/tmp.*`, `<<< x tee CLAUDE.md`), hinter
  `cp`/`mv` verschieben sie das Ziel (`cp /etc/hosts CLAUDE.md < /dev/null`).
- **diff-scan, entfernte Assertions (R-0130).** `review.sh diff-scan` wertet jede entfernte Zeile mit `assert` bzw.
  `expect(` als entfernte Assertion (`:174–190`), in jeder Datei — auch Rusts `.expect(` im Produktivcode, Imports
  (`use pretty_assertions::assert_eq;`) und Helfer-Definitionen. Eine entfernte Zeile trägt kein `review: ok`; es
  gibt im Diff keinen Ausweg.
- **diff-scan, Zusatzmuster (R-0132).** Nicht erkannt: `fit(`, `fdescribe(`, `.runIf(`, `.fails(`, `test.fail(`,
  `test.describe.fixme(`, `self.skipTest(`, `pytest.importorskip(`; Rückgaben mit Wert am Testanfang (`return None`,
  `return undefined;`, `return Ok(());`); eine Datei mit CRLF-Zeilen (die AR-Regex `:215` sieht das `\r`).

## Ziel & Nicht-Ziele

Ziel: die oben genannten Formen werden verweigert bzw. gemeldet, jede mit einem roten Test vorher; was bewusst offen
bleibt, steht als Grenze im Kopf des Wächters bzw. von `review.sh` und in `DEVELOPMENT.md`.

Entscheidungen Kevin 2026-10-02:
- R-0127: Die Vorfahr-Regel gilt nur für Wegnehm-Verben (`rm`, `rmdir`, `shred`, `unlink`, `chmod`, `chown`,
  `chgrp`, die Quelle von `mv`) und für die Startpfade eines löschenden `find`; Globs im Checkout zählen über ihr
  Verzeichnis (`rm -rf ./*` → die Repo-Wurzel, `rm -rf scripts/dev/*` → `scripts/dev`). Frei bleiben etwa
  `rm -f apps/web/dist/*.js` und `chmod -R +x apps/web/scripts`. Interaktiv bleibt es eine Warnung (Harness-Regel).
- R-0130: Eine entfernte Assertion zählt nur in einer Testdatei (`tests/`, `e2e/`, `test_*.py`, `*_test.{py,go,sh}`,
  `*.test.*`, `*.spec.*`) **oder** wenn die alte Zeile in einer Test-Spanne von `heads()` liegt (deckt Rust mit
  inline `#[test]` in `src/`); Import-Zeilen (`use`, `import`, `from … import`) zählen nie.
- `{1..3}`-Sequenzen bleiben eine dokumentierte Grenze; aufgelöst werden nur Komma-Listen `{a,b}`.
- `pytest.importorskip(` wird ein Skip-Muster (es schaltet ein ganzes Testmodul still ab; Ausweg `review: ok`).
- Ein Ledger mit sechs Tasks.

Nicht-Ziele (bleiben dokumentierte Grenzen): Prozess-Substitution, Klammern in Variablen, `{1..3}`, `git clean`,
Löschen aus Python, ein generisches `.fail(` (träfe `assert.fail(`), andere Rückgabewerte, Helfer in
`#[cfg(test)] mod tests` ohne `#[test]`.

## Betroffene Komponenten & Dateien

`scripts/dev/hooks/harness-guard.sh`, `scripts/tests/hooks_test.sh`, `scripts/dev/review.sh`,
`scripts/tests/review_scripts_test.sh`, `DEVELOPMENT.md` (Abschnitt Harness-Schutz, ab `:582`), `CHANGELOG.md`.

## Datenmodell / API / Migrationen

Keine.

## Externe Integrationen

bash-Glob-Semantik (`[^…]` gleich `[!…]`, Klammer-Expansion vor dem Globbing) laut `man bash`, Abschnitte „Pattern
Matching“ und „Brace Expansion“.

## Trade-offs & Alternativen

- Vorfahr-Regel für alle Schreibformen: größerer Radius, mehr Fehlalarme; die Wegnehm-Verben decken die gemessenen
  Fälle.
- RA nur in Testdateien: verlöre die 17 Dateien unter `apps/desktop/src-tauri/src` mit inline `#[test]`; nur in
  Spannen: verlöre Helfer-Assertions in `tests/` außerhalb einer Testfunktion.
- `{1..3}` auflösen: mehr Code für einen Fall, der bisher nicht vorkam.

## Risiken & Rollback

- Fehlalarme der Vorfahr-Regel auf gewollte Aufräum-Befehle im Checkout; die Gegenproben im Test halten die freien
  Formen fest. Rollback: Revert je Task.
- R-0130 macht diff-scan an Produktivcode nachsichtiger; die Gegenproben halten fest, dass Assertions in Tests und in
  inline-Rust-Tests rot bleiben.

## Doku-Impact

`DEVELOPMENT.md` (Harness-Schutz: was der Wächter jetzt erkennt, welche Grenzen bleiben; diff-scan-Bereich),
Kopfkommentare von `harness-guard.sh` und `review.sh`, `CHANGELOG.md`.

## Offene Fragen

Keine; entschieden am 2026-10-02.
