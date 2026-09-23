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

### T2 — Das Feld ist dokumentiert und wird gelintet  [ ]
Komponente: scripts · Dateien: scripts/dev/ledger.sh, scripts/tests/ledger_test.sh, tasks/README.md, AUTONOMOUS.md
Änderung: `tasks/README.md` beschreibt `Test-Löschung:`. Dazu gehört, wann das Feld passt: toter Code samt Test, oder ein Test, der durch einen genaueren ersetzt wird. Und wann es nicht passt: ein roter Test, der „weg soll“. `ledger.sh lint` prüft die Form (`<pfad>::<name> — <Grund>`, der Grund ist Pflicht). Ein fehlender Grund ist ein Fehler, denn eine Löschung ohne Begründung ist genau das, was das Gate verhindern soll. `AUTONOMOUS.md` nennt den Weg dort, wo `diff-scan` beschrieben ist. Tests: gültige Zeile ⇒ lint ok; ohne Grund ⇒ Fehler; ohne `::` ⇒ Fehler.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: tasks/README.md · AUTONOMOUS.md
Abhängt von: T1

## Danach, als eigenes Kurz-Ledger (nicht in diesem Branch)

`SafeText` löschen, eine Task auf `fix/safetext-delete`. Sie wendet den gesicherten Patch an und trägt
`Test-Löschung: apps/server/tests/test_text_bounds.py::test_safetext_passes_everything_but_nul — der
Typ hat seit R-0067 keinen Nutzer mehr`. Das ist zugleich der erste echte Lauf der neuen Regel durch
`task-close.sh`. Harness und Produktcode bleiben dabei in getrennten Branches.
