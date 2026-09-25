<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Bewusst gelöschte Tests: ein erlaubter Weg durch `diff-scan` — Task-Ledger (Kurz)
Status: aktiv · Branch: harness/test-deletion-gate · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Spec: dieses Ledger (Harness-Vorhaben, Roadmap R-0079)
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: nein — der Diff berührt `scripts/dev/review.sh`, `scripts/dev/task-close.sh`, `scripts/tests/review_scripts_test.sh` und die Ledger-Doku.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Hängt ab von: —

## Warum

`review.sh diff-scan` wertet jede gelöschte Assertion als „der Diff kauft sich sein Grün“. Die einzige
Ausnahme, `# review: ok <Grund>`, muss **an** der Zeile stehen, und eine gelöschte Zeile kann nichts
tragen. Wer toten Code samt seinem Test entfernt, kommt deshalb nicht durch `task-close.sh`.
Belegt am 2026-09-23: T10 von R-0067 sollte den ungenutzten Typ `SafeText` samt seinem Test löschen.
Der Stand war gebaut, grün und reviewt, aber `task-close` hat ihn verweigert. Worker 2 hat richtig am
Gate gestoppt, der Patch liegt unter `tasks/private/patches/r0079-safetext-delete.patch`.

Der Schutz selbst ist richtig und soll bleiben: Eine Assertion aus einem **weiterlebenden** Test zu
löschen, ist genau der Fall, den `diff-scan` fangen soll. Der erlaubte Weg darf nur den anderen Fall
öffnen: Ein Test verschwindet **als Ganzes**, und die Task sagt das vorher.

## Entschieden am Gate (Kevin, 2026-09-23)

1. **Regel:** Der ganze Test muss gehen, und die Task muss es ankündigen (unten). Eine Ankündigung je Datei allein reicht nicht.
2. **Freigabe:** erteilt. Worker 2 baut im Haupt-Checkout, die Aufsichts-Session verifiziert.

3. **Nach dem adversarialen Review (Kevin, 2026-09-25):** Die Ankündigung wird **nur aus dem committeten Ledger** (`HEAD`) gelesen, nicht aus dem Arbeitsbaum. Den Nachbau (T4) macht die Aufsichts-Session in einem eigenen Worktree.

## Die Regel

Eine gelöschte Assertion ist **kein** Fund, wenn beide Bedingungen gelten:

1. **Der ganze Test geht.** Im selben zusammenhängenden Block gelöschter Zeilen (`-U0`) steht vor der
   Assertion auch die Definition des Tests: `def test_…`/`async def test_…` (pytest), `func Test…` (Go),
   `it(`/`test(` (vitest/jest) oder `fn …` hinter einem gelöschten `#[test]` (Rust). Eine Assertion, die
   aus einem Test verschwindet, dessen Kopf stehen bleibt, bleibt ein Fund.
2. **Die Task kündigt es an.** Die Task im Ledger trägt eine Zeile
   `Test-Löschung: <datei>::<test> — <Grund>` (mehrere durch `;` getrennt). `diff-scan` bekommt dafür
   den Task-Bezug (`--task <ledger> <id>`, `task-close.sh` reicht ihn durch). Ohne `--task`, also bei
   einem Aufruf von Hand, bleibt die Prüfung so streng wie heute.

Das Ergebnis steht sichtbar im Lauf, etwa `diff-scan: clean (1 declared test deletion:
apps/server/tests/test_text_bounds.py::test_safetext_passes_everything_but_nul)`.

### T1 — `diff-scan` kennt angekündigte Test-Löschungen  [x]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/dev/task-close.sh, scripts/tests/review_scripts_test.sh
Evidenz: run.sh[quick]: 5 passed, 0 failed, 12 skipped @28a266e8 2026-09-23T19:30:18+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: `review.sh diff-scan` nimmt optional `--task <ledger> <id>` an und liest aus der Task die `Test-Löschung:`-Zeile. Im awk-Lauf merkt sich jeder zusammenhängende Block gelöschter Zeilen den zuletzt gelöschten Test-Kopf, also Dateiname plus Testname. Eine gelöschte Assertion wird nur übergangen, wenn dieser Kopf existiert und `<datei>::<test>` angekündigt ist. Übergangene Löschungen werden gezählt und in der Erfolgszeile genannt. `task-close.sh` ruft `diff-scan --staged --task "$LEDGER" "$ID"`. Tests mit Fixture-Repos, jeder muss bei Rücknahme rot werden:
- ganzer Test gelöscht und angekündigt ⇒ clean, mit Nennung;
- ganzer Test gelöscht, aber nicht angekündigt ⇒ Fund;
- nur eine Assertion aus einem bleibenden Test gelöscht, obwohl angekündigt ⇒ Fund;
- angekündigt ist ein anderer Test derselben Datei ⇒ Fund;
- ohne `--task` ⇒ Fund wie heute;
- je ein Go-, ein vitest- und ein Rust-Fall für die Kopf-Erkennung.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (T2)

### T2 — Das Feld ist dokumentiert und wird gelintet  [x]
Komponente: scripts · Dateien: scripts/dev/ledger.sh, scripts/tests/ledger_test.sh, tasks/README.md, AUTONOMOUS.md, DEVELOPMENT.md
Evidenz: run.sh[quick]: 5 passed, 0 failed, 12 skipped @abd08cb3 2026-09-23T19:37:47+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: `tasks/README.md` beschreibt `Test-Löschung:`. Dazu gehört, wann das Feld passt: toter Code samt Test, oder ein Test, der durch einen genaueren ersetzt wird. Und wann es nicht passt: ein roter Test, der „weg soll“. `ledger.sh lint` prüft die Form (`<pfad>::<name> — <Grund>`, der Grund ist Pflicht). Ein fehlender Grund ist ein Fehler, denn eine Löschung ohne Begründung ist genau das, was das Gate verhindern soll. `AUTONOMOUS.md` nennt den Weg dort, wo `diff-scan` beschrieben ist. Tests: gültige Zeile ⇒ lint ok; ohne Grund ⇒ Fehler; ohne `::` ⇒ Fehler.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: tasks/README.md · AUTONOMOUS.md
Abhängt von: T1

### T3 — Review-Befunde: ein angekündigter Kopf deckt nur seinen eigenen Test  [x]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/tests/review_scripts_test.sh, scripts/dev/ledger.sh, scripts/tests/ledger_test.sh, tasks/README.md
Evidenz: run.sh[quick]: 5 passed, 0 failed, 12 skipped @dac361de 2026-09-23T20:08:05+02:00
Review: approve (sonnet, Re-Review der Gesamt-Review-Befunde)
Änderung: Aus dem Gesamt-Review (Sonnet, `request_changes`). (1) Blocker: `head` blieb bis zum Blockende stehen, eine gelöschte Assertion aus einer Funktion hinter dem angekündigten Test (Helfer, Produktionscode) erbte ihn. Neu beendet eine gelöschte, nicht leere Zeile, die höchstens so tief eingerückt ist wie der Kopf, den Test (die nächste Funktion, das schließende `}`); nur die `)`, die eine mehrzeilige Signatur schließt, gehört noch dazu. (2) Blocker: ein Kopf, der gelöscht und im selben Diff wieder hinzugefügt wird (etwa mit geänderter Signatur), galt als ganzer Test weg. Neu macht ein hinzugefügter Kopf gleichen Namens in derselben Datei die Löschung zum Fund. (3) wichtig: ein `;` im Grund zerriss im Lint eine gültige Zeile. Neu trennt `;` nur vor dem nächsten `<datei>::`, gleich in `ledger.sh lint` und `diff-scan`. Tests: je Befund ein Fall (Python und Rust), rot gegen den Stand von T2; dazu die mehrzeilige Signatur, die sauber bleibt.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: tasks/README.md (die Regel genauer)
Abhängt von: T2

## Abschluss (2026-09-23, Worker 2)

- **Gesamt-Review** (Sonnet, frischer Kontext, `git diff main...`): erst `request_changes`, mit zwei
  Blockern (ein Kopf erbte die Assertion einer folgenden Funktion; ein gelöschter und wieder
  hinzugefügter Kopf galt als ganzer Test weg) und einem wichtigen Punkt (`;` im Grund). Beide Blocker
  waren im Scratch-Repo nachgestellt. Alle drei behoben in T3; die Re-Review-Runde gab `approve`. Offen
  bleibt ein Nit, bewusst so: ein hinzugefügtes Rust-`fn` gleichen Namens zählt als wiedergekehrter
  Kopf, auch wenn es kein Test ist (zu streng, nicht zu lasch).
- **Gesamt-Schnellcheck** `run.sh quick --strict` auf dac361de: `16 passed, 1 failed, 0 skipped,
  12 test-skips`. Der eine Fehlschlag war `ledger_test` mit der Invariante dieses Ledgers
  (`aktiv` ohne offenes `[ ]`), die dieser Commit auflöst. T3 berührt nur `scripts/` und `tasks/`;
  die `scripts`-Schicht lief dafür beim Schließen von T3 grün.
- **Schwere Suite:** entfällt, siehe `Heavy: nein` im Kopf; der Diff berührt keinen Stack-, Gateway-,
  PKI- oder Install-Pfad.
- **Außerhalb des Scopes, gemeldet:** Die ältere Assertion-Regex in `diff-scan` erkennt `assert_eq!`
  und `assert_ne!` in Rust nicht (der Unterstrich ist ausgeschlossen); eine gelöschte `assert_eq!`
  war schon vorher kein Fund. Außerdem lässt `task-close.sh` beim Schließen der letzten Task den
  Status auf `aktiv`, sodass dieser Commit für sich `ledger_test` rot macht, bis der Status-Commit folgt.

## Danach, als eigenes Kurz-Ledger (nicht in diesem Branch)

`SafeText` löschen, eine Task auf `fix/safetext-delete`. Sie wendet den gesicherten Patch an und trägt
`Test-Löschung: apps/server/tests/test_text_bounds.py::test_safetext_passes_everything_but_nul — der
Typ hat seit R-0067 keinen Nutzer mehr`. Das ist zugleich der erste echte Lauf der neuen Regel durch
`task-close.sh`. Harness und Produktcode bleiben dabei in getrennten Branches.

### T4 — Die Prüfung am Inhalt statt am Diff-Text (adversarialer Review)  [x]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/tests/review_scripts_test.sh, tasks/README.md, AUTONOMOUS.md, DEVELOPMENT.md
Evidenz: run.sh[quick]: 5 passed, 0 failed, 12 skipped @ab184f01 2026-09-25T08:59:12+02:00
Review: adversarialer Opus-Review 2026-09-25 (request_changes) → Nachbau; Re-Review folgt
Änderung: Der adversariale Opus-Review (2026-09-25) hat vier Umgehungen nachgestellt, alle am Diff-Text vorbei.
- **Gleichnamige Tests:** Zwei `describe`-Blöcke teilen sich einen Test-Namen, git richtet den behaltenen Kopf am toten aus, und eine Assertion des weiterlebenden Tests rutscht durch.
- **`++ x` als Dateikopf:** Die Inhaltszeile `++ x` erscheint im Diff als `+++ x` und schaltet die Datei um.
- **Ankündigung ohne Grund:** `diff-scan` nimmt sie an.
- **Verschobener Test:** Er gilt in einer anderen Datei als gelöscht.

Dazu Kevins Entscheidung: nur die committete Ankündigung zählt. Neu:
- `diff-scan` liest die Ankündigung aus `HEAD:<ledger>`.
- `---`/`+++` sind nur Kopf zwischen `diff --git` und dem ersten `@@`.
- Gelöschte Assertions gehen als Datensätze an eine Prüfung am Inhalt: Grund Pflicht; Name im alten Stand genau einmal; im neuen Stand weg; keine Datei des Diffs bekommt einen Kopf dieses Namens dazu; die alte Zeilennummer der Assertion liegt im alten Rumpf des Tests.
- Bei einem Fund nennt die Meldung, warum eine Ankündigung nicht zählte.

Tests: je ein Fall pro Umgehung, dazu „nur im Arbeitsbaum angekündigt“ und „gleichnamiger Test, der schon anderswo stand“ (Ankündigung bleibt gültig). Gegenprobe: dieselben Tests gegen `review.sh` von ab184f01 ⇒ 7 rot, fünf davon mit rc 0, also echte Umgehungen.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: tasks/README.md · AUTONOMOUS.md · DEVELOPMENT.md

### T5 — Zweiter adversarialer Review: Selbst-Ankündigung, `-diff`, Zeilen-Zählung, Kommentar-Köpfe  [x]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/dev/task-close.sh, scripts/tests/review_scripts_test.sh, scripts/tests/task_close_test.sh, tasks/README.md
Evidenz: run.sh[quick]: 5 passed, 0 failed, 12 skipped @db310375 2026-09-25T09:22:51+02:00
Review: zweiter adversarialer Opus-Review 2026-09-25 (request_changes) → Nachbau; Abschluss-Review folgt
Änderung: Der zweite adversariale Opus-Review (2026-09-25) fand an der Inhaltsprüfung selbst mit einem Diff keinen Weg vorbei, aber vier Umgehungen daneben.
- **Selbst-Ankündigung (Blocker):** `task-close.sh` staget das ganze Ledger, eine `Test-Löschung:`-Zeile reist also beim Schließen einer Task mit und gilt in der nächsten als committet.
- **`-diff` in einer `.gitattributes` (Blocker, älter als R-0079):** Sie macht `diff-scan` und `sec` blind.
- **Einzelnes `\r` und `\f`:** Sie verschieben Zeilen bzw. Einrückung.
- **Test-Köpfe in Kommentaren:** Sie gelten als Tests.

Neu:
- `task-close.sh` verweigert (Exit 4), wenn sich die `Test-Löschung:`-Zeilen gegenüber `HEAD` ändern.
- Jede Diff-Lesung in `review.sh` läuft über `git -c core.quotePath=false diff --text --no-ext-diff --no-textconv --no-color` mit festen Präfixen. `sec` erkennt Köpfe wie `diff-scan` nur vor dem ersten `@@`.
- Der Prüf-Teil liest Bytes und trennt nur an `\n`. Die Einrückung zählt nur Leerzeichen und Tabs, und die Pfade kommen `-z`-getrennt.
- Neue Invariante: Jede nicht leere Zeile des alten Rumpfs ist gelöscht, der ganze Test geht also.
- Pfade mit Leerzeichen führen zu einem Fund statt zu einem Absturz.

Tests: je ein Fall pro Umgehung, dazu der Leerzeichen-Pfad. Gegenprobe gegen den Stand von T4: 6 rot in `review_scripts_test`, davon 5 mit rc 0; 2 rot in `task_close_test`.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: tasks/README.md
