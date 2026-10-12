<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket harness-rest: Prompt nur an \n, Lane-Links in der Lane, pve.env gleich gelesen (R-0267, R-0252, R-0253) — Task-Ledger
Status: geplant · Branch: harness/harness-rest · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Spec: Roadmap R-0267, R-0252, R-0253 (Kurz-Ledger ohne Spec)
Heavy: none — review-run.sh, lane.sh, runner-env.sh und vm.py mit hermetischen Tests (Fake-CLI, Fixture-Repos, Platzhalter-pve.env); kein Stack-, Gateway-, PKI- oder Install-Pfad.
Hängt ab von: harness/lane-paket — T2 ändert lane.sh und lane_test.sh, die lane-paket auch ändert (dazu die Liste der
Plan-Slugs in lane_test); erst nach dessen Merge bauen und origin/main vorher hineinmergen. T1 und T3 hängen nicht daran.
DoD je Task: CLAUDE.md (Tests grün, shellcheck/ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-12 von Worker A für die Aufsicht (adminhelper-ac). Kevin hat die drei Zeilen am 2026-10-09 und
2026-10-10 angenommen. Zeilenangaben origin/main@c93b692e; beim Bau an Symbolen orientieren.

Vorab geprüft:
- `pve.env` trägt das Proxmox-Token. Für Plan und Bau gilt deshalb:
  - Die echte Datei (`~/.config/adminhelper/pve.env`) wird nie gelesen, gesourct oder ausgegeben.
  - Proben und Tests arbeiten nur mit Fixture-Dateien unter einem eigenen `HOME` und mit Platzhaltern, wie in
    hooks_test (`mk_home`) und test_vm (`placeholder-token`).
  - Keine Meldung nennt einen Wert aus der Datei.
- R-0251 (gemergt, PR #109) hat dieselbe Klasse wie R-0267 in ledger-loop.sh gelöst: `re.split(r"(?<=\n)", text)`,
  denn `splitlines()` trennt auch an `\x0b`, `\x0c`, `\x1c`–`\x1e`, `\x85` und U+2028/9.

### T1 — review-run.sh baut den Prompt nur an \n (R-0267)  [ ]
Komponente: scripts · Dateien: scripts/dev/review-run.sh, scripts/tests/review_run_test.sh
Änderung:
- Der Ledger-Text für den Prompt (:150) wird mit `split("\n")` statt `splitlines()` zerlegt.
  - Mit `splitlines()` beendet eine Zeile von T1, die ein U+2028 vor `### T9 — …` trägt, für den Reviewer den
    Abschnitt von T1 mitten in der Zeile, und der Rest von T1 fehlt im Prompt.
  - Umgekehrt beginnt dort ein falscher Abschnitt, der für eine Task `T9` als ihr Text gälte.
  - sed und awk von task-close und Loop lesen dasselbe Ledger nur an `\n`.
- Dasselbe gilt für `NEW_FILES` (:174). `GIT_DIFF` setzt `core.quotePath=false` (:139), also kommen Dateinamen roh.
  Ein Name mit U+2028 würde zu zwei „neuen Dateien“.
- Der Kopf von review-agent.md (:125) bleibt: Die Datei liegt unter den Harness-Pfaden, die Session ändert sie nicht.
- Fall in review_run_test:
  - Ein Ledger, dessen T1 eine Zeile mit U+2028 und `### T9 — fake` darin trägt und danach eine Zeile mit einer Marke.
  - Der Prompt für T1 enthält die Marke.
  - Ein neuer Dateiname mit U+2028 steht als eine Zeile unter „New files“.
Rot vorher: Auf main fehlt die Marke im Prompt für T1.
Beweis:
- origin/main@c93b692e, review-run.sh:150 `lines = open(ledger, encoding="utf-8").read().splitlines()` und :174
  `new_files.splitlines()`.
- Die Klasse ist an R-0251 belegt (harness/team-4b-loop-profile@591afaa0, Fall `nls` in ledger_loop_test :187/:822).
- Fund: Bau loop-kleinpaket-1, harness/loop-kleinpaket-1@91ca486a.
Dedup-Key: ref:scripts:review-run.sh:splitlines
HEAD: c93b692e
Semantik: `AUTONOMOUS.md` (Zwei Review-Ebenen) „ein frischer Sub-Agent …, der nur den Diff + die Task + feste
Kriterien sieht“. Die Task ist ihr ganzer Abschnitt im Ledger, wie ihn task-close liest.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T2 — lane.sh schreibt Links und Sidecar nur in die Lane (R-0252)  [ ]
Komponente: scripts · Dateien: scripts/dev/lane.sh, scripts/tests/lane_test.sh
Änderung:
- `lane_link_dir` (:122–130) macht `mkdir -p "$wt/$dir"` und `ln -sfn` hinein.
  - Trägt der Branch (`feature/<slug>`, ein Branch von irgendwem) einen getrackten Symlink an `apps/<c>/.venv` oder an
    `apps/<c>`, der aus der Lane herausführt, schreiben beide dorthin.
  - Dasselbe gilt für die Kopie des frpc-Sidecars in `lane_new` (:227–230, `mkdir -p` und `cp -RpL` nach
    `apps/desktop/src-tauri/binaries`).
- Neu: Eine kleine Hilfe prüft vor dem Schreiben, dass `realpath -m` des Ziels in der Lane liegt, so wie die Probe
  ihren Mutanten seit 4b schützt (review-probe.sh:165).
  - Liegt das Ziel außerhalb, schreibt `lane.sh` nichts dorthin. Es gibt ein WARN mit dem Pfad in der Lane, nicht mit
    dem Ziel.
  - Die Lane entsteht trotzdem, ohne diesen Link.
  - Ein Symlink, der innerhalb der Lane bleibt, ist erlaubt.
- Fall in lane_test:
  - Ein Plan-Branch mit getrackten Symlinks `apps/server/.venv` und `apps/desktop/src-tauri/binaries`, die auf
    Verzeichnisse außerhalb zeigen (unter `$WORK`).
  - Erwartet: `lane new` legt die Lane an. Die Ziele bleiben leer, je ein WARN erscheint.
  - Die Venvs der übrigen Komponenten sind verlinkt wie bisher.
Rot vorher: Auf main landen die Venv-Links und die Kopie des Sidecars im Ziel außerhalb der Lane.
Beweis:
- origin/main@c93b692e, lane.sh:125–128 (`mkdir -p "$wt/$dir"`, `ln -sfn "$entry" "$wt/$dir/${entry##*/}"`) und :229
  (`mkdir -p "$wt/$bin" && cp -RpL …`).
- Die Probe hat den Wächter: review-probe.sh:165–168.
- Fund: Bau 4b, harness/team-4b-loop-profile@591afaa0.
Dedup-Key: ref:scripts:lane.sh:link-through-tracked-venv
HEAD: c93b692e
Semantik: DEVELOPMENT.md „Eine Lane hat ihre eigene Test-DB“ und lane.sh :112–121 („link every entry of the main
checkout's <dir> into a REAL <dir> in the lane“). Die Links gehören in die Lane. Unter docs/ gibt es keine Stelle zu
`lane_link_dir`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T3 — runner-env.sh und vm.py lesen pve.env gleich, mit Paritätstest (R-0253)  [ ]
Komponente: scripts · Dateien: scripts/dev/runner-env.sh, scripts/vm/vm.py, scripts/tests/hooks_test.sh
Änderung:
- Heute lesen die beiden Leser an fünf Stellen verschieden:

  | Punkt | vm.py `read_pve_env` (:129–179) | runner-env.sh (:153–170) |
  |---|---|---|
  | Zeilen | `splitlines()`, auch an `\x0b`, `\x0c`, `\x85`, U+2028/9 | `read`, nur an `\n` |
  | Quotes | genau ein Paar | `sed` nimmt erst `"…"`, dann noch `'…'`, so wird aus `"'x'"` ein `x` |
  | Leerer Wert | gilt als nicht gesetzt | wird als `KEY=` exportiert |
  | NUL | bleibt im Wert | bash verwirft es stumm |
  | Leerraum | `str.strip()` (Unicode) | `[[:space:]]`, je nach Locale |

- Neu, gemeinsame Regeln:
  - Zeilen nur an `\n`; vm.py nimmt `split("\n")`.
  - Leerraum nur ASCII (Leerzeichen, Tab, CR, VT, FF). vm.py strippt genau diese Zeichen, runner-env.sh schreibt die
    Klasse aus, wie in bash-range-locale.
  - Genau ein Quote-Paar, gleich welcher Art.
  - Ein leerer Wert gilt als nicht gesetzt; runner-env.sh exportiert ihn nicht.
  - Eine Datei mit NUL-Byte lehnen beide ab (runner-env.sh `return 1`, vm.py `Usage`), ohne einen Wert zu nennen.
- Der Docstring von `read_pve_env` (:130) sagt dann richtig: Die `AH_PVE_*`-Zeilen liest vm.py wie runner-env.sh,
  `AH_VM_*` liest nur vm.py. runner-env.sh setzt `AH_VM_MAX` selbst.
- Paritätstest in hooks_test, bei `mk_home`/`runner_env` (:1258–1300):
  - Ein Fixture-pve.env mit Platzhaltern und den Fällen oben, ohne den NUL-Fall: verschachtelte Quotes, leerer Wert,
    CRLF, U+2028 und `\x85` in einem Wert, Tab am Ende, `export`.
  - Die `AH_PVE_*`-Werte, die runner-env.sh exportiert, sind genau die, die `vm.read_pve_env` derselben Datei
    liefert (vm.py importiert, `scripts/vm` auf dem Pfad).
  - Dazu: Eine Datei mit NUL lehnen beide ab, und keiner der Platzhalter steht in einer Meldung.
- test_vm `test_pve_env_is_read_as_runner_env_reads_it` bleibt grün. Die Fälle dort (Quotes, leer, `export`, letzte
  Zeile gewinnt) gelten unverändert.
Rot vorher: Der Paritätstest fällt auf main, mindestens an den verschachtelten Quotes, am leeren Wert und an U+2028.
Beweis:
- origin/main@c93b692e, vm.py:164 (`fh.read().splitlines()`), :169 (`line.strip()`), :175–176 (ein Quote-Paar), :177
  (leer zählt nicht).
- runner-env.sh:156 (`while IFS= read -r line`), :166 (`sed … s/^"\(.*\)"$/\1/; s/^'\''\(.*\)'\''$/\1/`), :167
  (`export "$key=$value"` auch bei leerem Wert).
- Fund: Bau 4b, harness/team-4b-loop-profile@591afaa0.
Dedup-Key: ref:scripts:runner-env.sh:pve-env-parity
HEAD: c93b692e
Semantik: vm.py:130 „The AH_PVE_*/AH_VM_* lines of pve.env, read as runner-env.sh reads them“ und runner-env.sh:60 „A
pve.env key as vm.py takes one (FILE_KEY)“. Beide behaupten Parität. Unter docs/ gibt es keine Stelle zu pve.env;
DEVELOPMENT.md nennt die Datei nur als Ablage des Tokens.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; die Kommentare und der Docstring sind die Regel)
