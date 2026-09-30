<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Schutz nachziehen: Wurzel-Glob, Commit-Hooks bei merge/cherry-pick/rebase, diff-scan-Lücken

Roadmap: R-0109, R-0110, R-0082 · Ledger: `tasks/schutz-nachziehen.md` · Branch: `harness/schutz-nachziehen`
Geplant 2026-09-30 von der Aufsicht (adminhelper-ac) auf Kevins Wort; Entscheidungen (Runde A) unten.

## Problem / Motivation

Drei Netze des Harness haben belegte Löcher. Alle drei sind Netze gegen **Versehen**, keine Sandbox; das
Vorhaben schließt die Formen, die ein Modell beim Aufräumen oder Committen tatsächlich trifft, und schreibt
die übrigen als Grenze auf.

**R-0109, Temp-Glob-Wächter.** Seit T10 von tmp-and-commit-guards (f71ef349) prüft `reaches_root`
(`scripts/dev/hooks/harness-guard.sh:218–228`) nur Globs, deren Pfad genau eine Wurzel oder einen Eintrag
direkt darin trifft (`len(comps) in (len(rc), len(rc) + 1)`). Ein Glob **über** der Wurzel, der tiefer
trifft, ist damit frei, obwohl er die Verzeichnisse aller Sessions löscht: `rm -rf /t*/claude-1000/*`,
`/t*/claude-1000/-home-*/*`, `/tm?/claude-*/*`, `/*/claude-1000/*`, `/var/t*/x/*`, `cd /t* && rm -rf
claude-1000/*`. Dazu fünf billige Parser-Lücken:
- `--` beendet die Optionen nicht: `words` (`:535`) verwirft jeden Operanden mit führendem `-`, also auch
  `rm -rf -- -home-…` nach `cd /tmp/claude-1000`;
- `|&` ist kein Trenner (`SEPARATORS`, `:131`), `… |& xargs rm -rf` läuft durch;
- der Tokenizer (`tokenize`, `:364–374`, shlex mit `punctuation_chars`) liefert `);` als **ein** Token, der
  Rumpf von `for d in $(ls -d /tmp/tmp.*); do rm -rf "$d"; done` wird nie ein eigenes Segment;
- `xargs` zählt nur, wenn sein Verb selbst löscht (`:551`), nicht `xargs sh -c 'rm …'`;
- als Lister zählen nur `ls`, `echo`, `printf` (`:574`), nicht `grep -l`/`-L`.

**R-0110, Commit-Hooks.** `scripts/dev/hooks/` enthält nur `pre-commit`. `git cherry-pick`, `git revert`,
`git rebase` und ein Merge mit automatischem Commit laufen an ihm vorbei (festgehalten als „known gap" in
`scripts/tests/review_scripts_test.sh:767–780`, dokumentiert in `DEVELOPMENT.md:630–632`). Eine private
Datei aus einem anderen Branch kommt so ungeprüft in den Verlauf. Dazu ist `chmod -x
scripts/dev/hooks/pre-commit` auch mit `AH_AUTONOMOUS=1` frei, während `sed -i` auf dieselbe Datei
verweigert wird: `chmod` ist kein Schreib-Verb des Wächters.

**R-0082, `review.sh diff-scan`.** Die Assertion-Regex (`scripts/dev/review.sh:173`,
`(^|[^A-Za-z_.])assert([^A-Za-z_]|$)`) schließt über den Unterstrich Rusts `assert_eq!`/`assert_ne!` aus; Go
hat gar keine Regel (keine der Go-Testdateien nutzt testify, ein gelöschtes `t.Fatalf`/`t.Errorf` ist nie ein
Fund); in `SKIP_PATTERNS` (`:51–52`) fehlen `describe.skip(` und dieselbe Klasse (`.only(`, `xdescribe(`,
`xtest(`, `.skipIf(`, `.todo(`, `test.fixme(`, `t.SkipNow(`, `pytest.mark.xfail`, `pytest.xfail(`, `#[ignore`
mit Begründung); und ein eingefügtes nacktes `return` vor den Asserts schaltet einen Test still ab.

## Ziel und Nicht-Ziele

Ziel:
- Ein Glob über einer Temp-Wurzel, der in ein geteiltes Verzeichnis oder darunter reicht, wird in jedem Modus
  verweigert; die tiefen Scratchpad-Aufräumer, die T10 freigab, bleiben frei.
- Die fünf Parser-Formen oben werden erkannt.
- `review.sh sec` läuft auch bei cherry-pick, revert, rebase und Merge-Commits; `harness.sh status` zeigt alle
  drei Hooks; `chmod` auf einen Harness-Pfad zählt als Schreiben.
- `diff-scan` findet gelöschte Rust- und Go-Assertions, die fehlenden Skip-Muster und ein nacktes `return` in
  einem Test (Python, Go, Rust, TS/JS).

Nicht-Ziele (dokumentierte Grenzen, Kevin 2026-09-30):
- Wächter: Prozess-Substitution (`done < <(ls …)`), `mapfile`/`readarray`, eine Liste ohne Glob mit einem zur
  Laufzeit gebauten Pfad (`ls /tmp | while read d; do rm -rf /tmp/$d`), `cat … | xargs rm` (Inhalt statt
  Namen).
- Commit-Schutz: direktes Schreiben in `.git/config`, `include.path`, `git config --edit`, `eval`/`$(…)`, ein
  git-Alias, `git` über seinen exec-path, Plumbing (`commit-tree`, `update-ref`), ein Fast-Forward-Merge (er
  erzeugt keinen Commit). Kein Runner-Deny `Edit(./.git/**)`: unter `dontAsk` ohne passende Allow-Regel wird
  das schon heute verweigert, und Bash-Schreibwege deckt eine Edit-Regel nicht ab (nur dokumentieren).
- Kein CI-Schritt `review.sh sec` (eigene Zeile R-0123).

## Betroffene Komponenten und Dateien

| Datei | Änderung | Task |
|---|---|---|
| `scripts/dev/hooks/harness-guard.sh` | `reaches_root` für Globs über der Wurzel; `--`, `\|&`, `);`, `xargs sh -c`, `grep -l/-L`; `chmod` als Schreib-Verb; Kopf-Kommentar der Grenzen | T1, T2, T3 |
| `scripts/tests/hooks_test.sh` | rote Fälle je Form, freie Gegenproben | T1, T2, T3 |
| `scripts/dev/hooks/prepare-commit-msg`, `scripts/dev/hooks/pre-merge-commit` (neu, 100755, SPDX) | `exec bash <root>/scripts/dev/review.sh sec --staged` wie `pre-commit` | T3 |
| `scripts/dev/harness.sh` | `status` prüft alle drei Hooks auf Ausführbarkeit | T3 |
| `scripts/tests/review_scripts_test.sh` | „known gap" umdrehen, Merge- und Rebase-Fälle; diff-scan-Fälle je Sprache | T3, T4, T5 |
| `scripts/dev/review.sh` | Regex für `assert_*!`, Go-`t.Fatal*`/`t.Error*` als RA, neue Skip-Muster, AR-Satz „nacktes `return` in einem Test" | T4, T5 |
| `DEVELOPMENT.md` (Harness-Schutz `:553–632`, Task schließen `:419–421`), `AUTONOMOUS.md` (`:261–273`), `CHANGELOG.md` | Doku | T1–T3, T5 |

Alle Code-Dateien sind Harness-Pfade (`scripts/dev/harness-paths.txt`): Branch `harness/`, Bau interaktiv in
Worker B (`../AdminHelper-harness-b`), Reviewer Opus. `CLAUDE.md` bleibt: der Satz in §2 („der pre-commit-Hook
fährt vor jedem Commit `review.sh sec`") stimmt weiter.

## Datenmodell / API / Migrationen

Keine. Git-Hook-Vertrag (githooks(5), git 2.47): Exit ≠ 0 bricht ab. `prepare-commit-msg` bekommt
`$1` = Nachrichtendatei, `$2` = Quelle, `$3` = SHA; `review.sh sec --staged` braucht keins davon.

## Externe Integrationen

git 2.47.3, githooks(5): „pre-merge-commit … invoked by git-merge(1) … Exiting with a non-zero status …
causes the git merge command to abort before creating a commit". git-commit(1): `--no-verify`/`-n` umgeht nur
pre-commit und commit-msg, **nicht** prepare-commit-msg. Dass der Sequencer (cherry-pick, revert, rebase)
`prepare-commit-msg` aufruft, ist **nicht dokumentiert**, aber unter 2.47.3 gemessen (Explorer der Aufsicht,
2026-09-30, Hooks in `.git/hooks` eines Scratch-Repos):

| Vorgang | laufende Hooks |
|---|---|
| cherry-pick, revert | prepare-commit-msg, post-commit |
| merge --no-ff | pre-merge-commit, prepare-commit-msg, commit-msg |
| rebase | pre-rebase, prepare-commit-msg je Commit, post-rewrite |
| commit-tree, update-ref | keiner |

Mit `prepare-commit-msg` = `review.sh sec --staged`: cherry-pick eines `tasks/sec-x.md` bricht mit rc 128 ab,
merge mit rc 1, rebase stoppt mit der sec-Meldung; ein sauberer Commit geht durch (`sec` ~20 ms).

## Trade-offs und Alternativen

- **Wurzel-Glob:** verweigert wird, wenn in `comps[:len(rc)]` ein Glob-Zeichen steht, der Präfix per
  `fnmatch` zur Wurzel passt und `len(comps) >= len(rc)` gilt, also die Form vor T10 plus die Bedingung „Glob
  **über** der Wurzel". Die T10-Fehlalarme (tiefe Scratchpad-Pfade mit wörtlichem `/tmp/claude-…`) bleiben
  frei, weil ihr Glob unter der Wurzel steht. Verworfen: „jeder Glob irgendwo unter /tmp" (13 legitime
  Aufräumer in 34 513 echten Befehlen).
- **Beide Hooks statt nur `pre-merge-commit`** (Kevin): nur so sind cherry-pick und rebase abgedeckt. Der Preis
  ist die undokumentierte Abhängigkeit; die umgedrehten Tests werden rot, falls git sie aufgibt
  (Kanarienvogel). Nebenwirkung: bei `git commit` läuft `sec` zweimal (~40 ms), und ein `git commit -n` in
  Kevins eigener Shell fährt `sec` trotzdem (über prepare-commit-msg); sein Ausweg bleibt `git config --unset
  core.hooksPath`.
- **`chmod` als Schreib-Verb** (Harness-Regel: autonom verweigert, interaktiv gewarnt), nicht als eigene
  „Umgehung in jedem Modus". Verworfen: jede Modusänderung unter `scripts/dev/hooks/` in jedem Modus
  verweigern (mehr Regel, als der Fund verlangt).
- **diff-scan:** Muster als feste Strings wie bisher (`#[ignore` als Präfix statt `#[ignore]`, damit
  `#[ignore = "flaky"]` trifft); Go-Assertions nur in `*_test.go` (`err.Error()` außerhalb bleibt frei); die
  `return`-Heuristik über die vorhandenen `heads()` (`review.sh:247–291`) für alle vier Sprachen, Ausweg
  `review: ok <grund>` wie bei jedem Fund (Kevin: alle vier).

## Risiken und Rollback

- Ein Fehlalarm der Wurzel-Glob-Regel trifft alle Sessions ohne Kill-Switch. Rollback: Revert von T1.
- Ein kaputtes `review.sh` blockiert jetzt auch Merge, cherry-pick und rebase (fail-closed). Ausweg in Kevins
  Shell: `git config --unset core.hooksPath`.
- Ein git, das prepare-commit-msg im Sequencer nicht mehr ruft, öffnet die Lücke still wieder; die Tests zeigen
  es beim nächsten Lauf.
- Die `return`-Heuristik kann legitime frühe Returns in Test-Hilfsblöcken treffen (etwa ein `return` in einer
  inneren Funktion eines Tests). Ausweg: `review: ok <grund>`; ist es zu laut, fällt T5 auf „nur Python"
  zurück (Frage an Kevin, kein stilles Umschneiden).
- Die neuen Hooks wirken in jedem Worktree erst mit dem Branch, der sie trägt (relativer `core.hooksPath`).

## Doku-Impact

`DEVELOPMENT.md` „Harness-Schutz und Kill-Switch" (Grenzen des Wächters, die Hook-Liste statt „nur git commit
fährt ihn"), „Task schließen" (was diff-scan erkennt), `AUTONOMOUS.md` PreToolUse-Absatz (drei Hooks),
Kopf-Kommentare von `harness-guard.sh` und `review.sh`, `CHANGELOG.md` (Changed/Security-neutral: „Commit-Hooks
laufen auch bei merge, cherry-pick und rebase").

## Entscheidungen (Kevin, 2026-09-30, Runde A)

1. Reihenfolge Worker B: erst `dev-tool-pins` (Frist Audit am 2026-10-05), dann dieses Vorhaben, dann
   `harness-kleinfixes`.
2. R-0109: Wurzel-Glob plus die fünf Parser-Formen; Prozess-Substitution, mapfile, `$d`-Listen und `cat|xargs`
   bleiben dokumentierte Grenzen.
3. R-0110: `prepare-commit-msg` und `pre-merge-commit`; `chmod` als Schreib-Verb; `.git/config`-Schreiben,
   `include.path`, `commit-tree` usw. als Grenzen; kein Runner-Deny `Edit(.git/**)`.
4. R-0082: alle Muster der Zeile plus dieselbe Klasse, dazu die `return`-Heuristik für py/go/rs/ts.

## Offene Fragen

Keine für das Gate. Beim Bau: ist die `return`-Heuristik in T5 auf dem echten Repo zu laut (Fehlalarme in
bestehenden Tests zählen nicht, diff-scan sieht nur den Diff), meldet der Worker `[?]` statt umzuschneiden.
