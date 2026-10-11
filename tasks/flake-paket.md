<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Flake-Paket: der Fixture-Klon in ledger_loop_test, die Pipes in diagnostics_test (R-0262, R-0264) — Task-Ledger
Status: aktiv · Branch: harness/flake-paket · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-11 (kleines Fund-Paket aus R-0262 und R-0264, Flake-Paket aus Kevins Triage 2026-10-10; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0262, R-0264 (Kurz-Ledger ohne Spec)
Heavy: none — zwei Shell-Tests unter scripts/tests; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-11 von Worker A für die Aufsicht (adminhelper-ac). Kevin hat beide Zeilen am 2026-10-10 in der Triage
als „Flake-Paket, zuerst“ angenommen. Zeilenangaben origin/main@8e31cf71; beim Bau an Symbolen orientieren.

### T1 — ledger_loop_test klont das Fixture über den Transport, nicht per Hardlink (R-0262)  [ ]
Komponente: scripts · Dateien: scripts/tests/ledger_loop_test.sh
Änderung:
- Die beiden Klone aus dem Fixture-Origin, `:197` (`$CLONE`) und `:645` (`$KEV`), laufen mit `git clone --no-local`.
  Git holt die Objekte dann über den Transport, statt das Objektverzeichnis Datei für Datei zu verlinken oder zu
  kopieren.
- Eine Datei, die ein paralleler git-Prozess in `objects/pack` des Origin anlegt oder entfernt (etwa
  `multi-pack-index.lock`), trifft den Klon damit nicht mehr.
- Im Abschnitt „repo wiring“ kommt eine Prüfung dazu: In `ledger_loop_test.sh` steht kein `git clone` ohne
  `--no-local`.
Rot vorher: Die neue Prüfung fällt auf main, denn dort stehen zwei Klone ohne `--no-local`. Der Lauf selbst ist nicht
deterministisch rot: Lokal ließ er sich in 150 Versuchen gegen eine laufend neu angelegte `multi-pack-index.lock`
nicht reproduzieren (git 2.47.3).
Beweis:
- CI main 7600dc25, run 37976635971, Job „Ops scripts“: `fatal: hardlink different from source at
  …/srv/repo/.git/objects/pack/multi-pack-index.lock`, danach 7 passed, 127 failed; im Rerun grün.
- Code: `:197` klont lokal aus `$ORIGIN`, in das `:136`/`:151` kurz zuvor rund 90 Branches gepusht haben.
- Git prüft beim lokalen Klon für jede verlinkte Datei, ob sie noch dieselbe ist wie beim Lesen des Verzeichnisses;
  eine Sperrdatei, die dazwischen neu entsteht, bricht den Klon ab.
- Welcher Prozess die Sperre schrieb, ist nicht verifiziert. `--no-local` nimmt das Wettrennen unabhängig davon weg.
Dedup-Key: bug:scripts:ledger_loop_test.sh:clone-hardlink-race
HEAD: 8e31cf71
Semantik: `docs/developer/cicd.html:99–101` „reruns bleibt bewusst 0: der Wochenlauf wiederholt einen roten Schritt
selbst und klassifiziert ihn, statt die Suiten heimlich retryen zu lassen“. Eine Suite ist deterministisch; ein
Fixture, das an fremder Wartung scheitert, ist ein Flake der Suite selbst.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T2 — diagnostics_test prüft ohne Pipe in grep -q (R-0264)  [ ]
Komponente: scripts · Dateien: scripts/tests/diagnostics_test.sh
Änderung:
- Eine Hilfe `has <muster> <text>` mit `grep -q -- "$1" <<<"$2"` ersetzt die zehn `printf '%s' "$x" | grep -q …`
  (`:37`, `:44`, `:47–50`, `:64`, `:66–68`). Ohne Pipe kann der Schreiber kein SIGPIPE bekommen, wenn grep nach dem
  ersten Treffer endet.
- Zwei der Stellen sind Leck-Prüfungen (`:37`, `:64`). Dort konnte unter `pipefail` sogar ein Treffer übersehen
  werden: Der Schreiber endet mit 141, und `if` wertet das als „kein Treffer“.
- Ein Selbsttest der Hilfe mit einer Eingabe über der Pipe-Größe (300 kB, Treffer in der ersten Zeile) muss grün sein.
  Mit der alten Pipe-Form endet derselbe Fall deterministisch mit 141.
Rot vorher: Der Selbsttest mit der Pipe-Form statt der Hilfe ergibt 141 (siehe Beweis).
Beweis:
- Bau loop-kleinpaket-1 T1, harness/loop-kleinpaket-1@91ca486a: Der erste Close war rot mit `diagnostics_test:
  FAILED` („SECRET_KEY not masked by sanitize_env“); allein lief der Test 3/3 grün.
- Der Mechanismus deterministisch: `bash -c 'set -o pipefail; big="$(printf "SECRET_KEY=<redacted>\n"; head -c 300000 /dev/zero | tr "\0" x)"; printf "%s" "$big" | grep -q "^SECRET_KEY=<redacted>"; echo $?'`
  ergibt `141`; dasselbe als `grep -q … <<<"$big"` ergibt `0`.
- Dass bashs `printf` auch eine kurze Ausgabe zeilenweise in die Pipe schreibt (die Ursache im kleinen Fall), ist nicht
  verifiziert, denn auf der Box gibt es kein strace.
Dedup-Key: bug:scripts:diagnostics_test.sh:pipefail-grep
HEAD: 8e31cf71
Semantik: `docs/developer/cicd.html:99–101` (wie T1). Dazu CLAUDE.md §6: „ein erst roter, dann grüner Test ist
`flaky`, nicht PASS“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
