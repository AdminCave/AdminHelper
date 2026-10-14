<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Kleinpaket 4: Scissors im commit-msg-Hook, Kommentar-Grenzen und Ledger-Pfad im diff-scan — Task-Ledger
Status: erledigt · Branch: harness/kleinpaket-4 · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-14 (kleines Fund-Paket, Triage Kevin 2026-10-07; R-0213 Weg (a2), Restrisiko auf Kevins Wort 2026-10-14; N2 als Code-Fix; T3 mit task-close.sh; --editor; K1 und K2 eigene Zeilen; Review am Ende Opus; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0213, R-0216, R-0217 (Kurz-Ledger ohne Spec)
Heavy: none — nur Harness-Skripte unter scripts/dev, ihre hermetischen Tests und Doku; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-14 von Worker B im Auftrag der Aufsicht (adminhelper-ac). Kevin hat die drei Zeilen am 2026-10-07 als
Kleinpaket-4 angenommen, „nach dem Merge-Stapel“; der Stapel ist gemergt. Die private Roadmap ist in diesem Worktree
nicht lesbar, der Zeileninhalt kommt von der Aufsicht. Zeilenangaben origin/main@092c55d9, git 2.47.3. Alle Dateien
sind Harness-Pfade: Den PR merged Kevin oder die Aufsicht auf sein Wort. Alle drei Tasks fassen `review.sh` und
`review_scripts_test.sh` an und laufen nacheinander, ohne Lane. Token-Muster in Tests setzen sich wie bisher zur
Laufzeit zusammen (`review_scripts_test.sh:372-374`).

### T1 — commit-msg: an der Schnittlinie schneidet `sec --message` nur, wenn ein Editor die Nachricht schrieb, und nur den Diff darunter (R-0213)  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/commit-msg, scripts/dev/review.sh, scripts/tests/review_scripts_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @251bbcd7 2026-10-14T07:37:34+02:00
Review: Review am Ende (Kurz-Ledger, Opus): approve in Runde 2
Änderung:
- **Heute:** `review.sh:1042` (`/^# -+ >8 -+$/ { exit }`) beendet den Scan der Nachricht an jeder Zeile dieser Form, bei
  `-m` und `-F` ebenso wie im Editor, auch an einer kürzeren Linie wie `# --- >8 ---`. git schneidet dort aber nur mit
  `-v` oder mit Editor und `cleanup=scissors` (git-commit(1), `--cleanup`: „… is truncated, if the message is to be
  edited“). Sonst landet, was unter der Linie steht, im Commit.
- **`commit-msg`:** gibt `--editor` mit, wenn `GIT_EDITOR` nicht `:` ist. githooks(5): „All the git commit hooks are
  invoked with the environment variable GIT_EDITOR=: if the command will not bring up an editor to modify the commit
  message.“ Der Kommentar `:13-14` sagt, was gilt.
- **`review.sh sec --message <file> [--editor]`:**
  - Ohne `--editor` liest es die ganze Datei.
  - Mit `--editor` endet der Scan an der ersten Zeile `diff --git ` **unterhalb** der exakten Linie
    `# ------------------------ >8 ------------------------` (Stringvergleich, kein Regex). Das ist der Diff, den
    git mit `-v` dort einsetzt. Die Zeilen dazwischen und eine Linie ohne folgenden Diff werden gelesen.
  - `--editor` ohne `--message` ist Exit 2.
  - Usage `:13`, der Absatz `:70-75` und der Kommentar `:1036-1040` sagen es.
- **Tests (`review_scripts_test.sh`), nur ergänzt:**
  - Der Fall `:429-432` bekommt `--editor` und eine `diff --git`-Zeile in seine Eingabe; seine Erwartung (rc 0)
    bleibt. Eine Ankündigung braucht es nicht: diff-scan liest in `.sh` keine `ok`/`bad`-Zeile als Assertion.
  - Neue direkte Fälle:
    - ohne Flag: Linie plus Muster ergibt 4, ebenso die kurze Linie;
    - `--editor`: Linie, `diff --git`, Muster in einer entfernten Diff-Zeile ergibt 0;
    - `--editor`: Linie plus Muster ohne Diff ergibt 4;
    - `--editor` allein ergibt 2.
  - Am scharfen Hook (nach `:2154`):
    - `-m` mit getippter Linie und Muster wird verweigert, kein neuer Commit, nur die Zeile genannt;
    - dasselbe mit `-F` und mit `-m` bei gesetztem `GIT_EDITOR=<skript>` (git setzt dann trotzdem `:`);
    - `GIT_EDITOR=<skript>` mit `commit -v`, dessen gestagter Diff eine Zeile mit dem Muster entfernt, wird committet.
      Die Fixture-Datei mit dem Muster kommt vor dem Scharfschalten in den Fixture-Commit.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Hook-Absatz, `:853-855`)
Beweis:
- R-0213 (Review Kleinpaket-2 T3 r2, harness/kleinpaket-2@e1dba283).
- origin/main@092c55d9: Eine Nachricht `subject`, Leerzeile, die Schnittlinie, darunter ein Token-Muster, ergibt
  `review.sh sec --message <datei>` → rc 0. Dieselbe ohne Linie ergibt rc 4, ebenso rc 0 mit `# --- >8 ---`.
- `git commit -F <datei>` derselben Nachricht behält das Muster im Commit (`git log -1 --format=%B`).
- Ein Spion-Hook zeigte bei `commit -m`, `commit -F` und `merge --no-edit` jeweils `GIT_EDITOR=:`, bei `commit -v`,
  `-e -m`, `--cleanup=scissors` und `merge --edit` einen anderen Wert. Auch ein vom Aufrufer gesetztes
  `GIT_EDITOR=/bin/true` sieht der Hook bei `-m` und `-F` als `:`.
Orakel: mutation-sample — `--editor` im Hook nie gesetzt: der `commit -v`-Fall rot; der Schnitt wie heute an der
ersten Linie: die `-m`/`-F`-Fälle rot.
Dedup-Key: ref:scripts:hooks/commit-msg:scissors
HEAD: 092c55d9
Semantik: `scripts/dev/hooks/commit-msg:13-14`: „review.sh reads all of it but, with `commit -v`, the diff below the
scissors line.“ `review.sh:1038-1040`: „With commit -v git puts the diff below a scissors line, and that is no part of
the message. Comment lines are read: without an editor (-m, -F) git keeps them in the commit.“ `DEVELOPMENT.md:855`:
„bei `commit -v` zaehlt alles unter der Schnittlinie nicht.“ Alle drei meinen den Diff von `-v`; der Code schneidet
immer.

### T2 — diff-scan: Kommentar-Grenzen der hinzugefügten Assertions, dokumentiert und an `/*` geschnitten, und die Tab-Bindung der Filter unter Test (R-0216)  [x]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/tests/review_scripts_test.sh, tasks/README.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @13db4ce1 2026-10-14T06:21:50+02:00
Review: Review am Ende (Kurz-Ledger, Opus): approve in Runde 2
Änderung:
- **(N1)** `comment_at` (`review.sh:326-333`) nimmt ein ` #` bzw. ` //` auch in einem String als Kommentarbeginn. Eine
  Assertion dahinter auf derselben Zeile zählt nicht als hinzugefügt, die strengere Richtung. Ein Satz im Kommentar
  an `comment_at` und in Punkt 6 von `tasks/README.md` (`:174-175`) sagt das. Am Code ändert sich dafür nichts.
- **(N2)** Die gezählte Seite (`:377-379`) schneidet zusätzlich an `/*` am Zeilenanfang oder nach Leerraum. Ein
  `build(); /* expect(…) */` bringt dann keine Assertion mehr zurück, und „hinter Code“ in Punkt 6 stimmt wörtlich.
  `comment_at` selbst bleibt, wie es ist: Er entscheidet auch, ob ein Skip-Muster zählt, und dort wäre jeder weitere
  Kommentarbeginn die nachsichtigere Richtung.
- **(N3)** Ein Regressionsfall für die Tab-Bindung der Filter (`:797-799`, Präfixe `DECLARED\t`/`CHANGED\t` aus
  `:784/786`):
  - `CHANGED_test.py` und `DECLARED_test.py` im Wurzelverzeichnis der Fixture verlieren je eine Assertion;
  - mit und ohne `--task` ergibt das Exit 3, beide Dateien genannt.
- **Tests (`review_scripts_test.sh`), nur ergänzt:**
  - N2: eine angekündigte Änderung, deren einzige neue Assertion in `/* … */` hinter Code steht, ergibt Exit 3;
  - N1: eine neue Assertion hinter `" #"` in einem String zählt nicht, Exit 3, mit dem Satz aus der README als
    Testname;
  - N3 wie oben.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: tasks/README.md (Punkt 6 von `Assertion-Änderung:`)
Beweis:
- R-0216 (Review Kleinpaket-3 T4 Runde 2).
- origin/main@092c55d9, Fixture mit angekündigter Änderung:
  - `x = " #"; assert …` als neue Zeile ergibt Exit 3 „0 assertion(s) added in its new body, 1 removed“; mit `" -"`
    clean;
  - `build(); /* expect(out.at).toBe(2); */` ergibt clean (1 added), mit `/*` am Zeilenanfang Exit 3.
- `CHANGED_test.py` im Wurzelverzeichnis verliert seine Assertion: Exit 3. Mutant ohne `\t` im `grep -v` von `:799`:
  clean, beide Funde verschluckt.
Orakel: mutation-sample — die neue `/*`-Zeile entfernt: der N2-Fall rot; `\t` aus `:799` entfernt: der N3-Fall rot.
Dedup-Key: ref:scripts:review.sh:assertion-change-nits
HEAD: 092c55d9
Semantik: `tasks/README.md:174-175`: „Eine Assertion, die nur in einem Kommentar steht, am Zeilenanfang oder hinter
Code, zählt nicht.“ `review.sh:374-376`: „An added assertion, not one that only stands in a comment (at the start of
the line or behind code)“.

### T3 — diff-scan `--task` und task-close nehmen als Ledger nur, was als `tasks/*.md` geschrieben ist und dort liegt (R-0217)  [x]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/dev/task-close.sh, scripts/tests/review_scripts_test.sh, scripts/tests/task_close_test.sh, tasks/README.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @dbedc016 2026-10-14T07:51:15+02:00
Review: Review am Ende (Kurz-Ledger, Opus): approve in Runde 2
Änderung:
- **Heute:** `review.sh:295-299` und `task-close.sh:103-107` prüfen nur den aufgelösten Pfad (`realpath -m`). Ein
  Symlink `docs/l.md -> ../tasks/fix.md` besteht. Die Ankündigung liest diff-scan aber aus `HEAD:<geschriebener Pfad>`
  (`review.sh:308`). Die Commit-Prüfung von task-close (`:540`) schützt nur `tasks/*.md`.
- **Neu:** Beide prüfen zusätzlich den geschriebenen Pfad wie `review-run.sh:97-103`:
  - `realpath -m -s` relativ zu `ROOT`, so wie geschrieben, damit ein absoluter Pfad durch einen verlinkten Checkout
    nicht „draußen“ liegt;
  - beide Pfade durch dieselbe `case`-Liste;
  - `declared-only` (`review-probe.sh:201`) geht durch denselben Block.
- **Tests, nur ergänzt:**
  - `review_scripts_test.sh` neben der Schleife `:1824`:
    - `HEAD:docs/l.md` eine reguläre Datei mit Abschnitt T1 und `Test-Löschung:`, im Arbeitsbaum ein Symlink nach
      `../tasks/fix.md`: `diff-scan --task docs/l.md T1`, `declared-only` und `tasks/../docs/l.md` ergeben je Exit 2
      „not a ledger“;
    - `tasks/fix.md` relativ und absolut bleiben angenommen.
  - `task_close_test.sh` neben der Schleife `:160`: derselbe Symlink, dessen Ziel im Arbeitsbaum dieselben
    Ankündigungszeilen trägt wie `HEAD:docs/l.md`, ergibt Exit 2.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: tasks/README.md (`:204-207`, „geschrieben und liegend“)
Beweis:
- R-0217 (Frische Review-Runde Kleinpaket-3 T4).
- origin/main@092c55d9, Fixture wie oben, `test_gone` samt Assertion gelöscht:
  - `diff-scan --staged --task docs/l.md T1` ergibt clean „1 declared test deletion(s)“;
  - `--task tasks/fix.md T1` ergibt Exit 3.
- Über `task-close.sh docs/l.md T1` greift die Frühprüfung (`:138`, Exit 4) nur, solange sich die Ankündigungszeilen
  von `HEAD:docs/l.md` und dem Symlink-Ziel unterscheiden. Trägt das Ziel ungestagt dieselben Zeilen, bestehen
  Frühprüfung und diff-scan. Weiter als bis zur fehlenden Suite der Probe ist das nicht verifiziert; der neue Fall in
  `task_close_test.sh` zeigt es.
Orakel: mutation-sample — die Prüfung des geschriebenen Pfads entfernt: die Symlink-Fälle beider Tests rot.
Dedup-Key: ref:scripts:review.sh:ledger-symlink
HEAD: 092c55d9
Semantik: `tasks/README.md:204-207`: „Ein Ledger ist nur `tasks/*.md`, ohne `tasks/README.md` und
`tasks/templates/`: genau das, was die Commit-Prüfung von `task-close.sh` schützt. `diff-scan --task` und
`task-close.sh` lehnen alles andere ab (Exit 2), eine Ankündigung in der CHANGELOG oder einer Spec gewährt nichts.“
