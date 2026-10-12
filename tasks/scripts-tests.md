<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket scripts-tests: eingebaute Schreiber vor grep -q, lokale Klone, Ankündigung in einer Zeile (R-0286, R-0287, R-0297) — Task-Ledger
Status: aktiv · Branch: harness/scripts-tests · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-11 (kleines Fund-Paket aus R-0286, R-0287, R-0297, Triage Kevin 2026-10-11; Fragen: 1 Heavy linux-full statt none, 2 echo mitnehmen, 3 Variante (a) der Lint lehnt die Mehrzeilen-Form ab, 4 runner-setup.sh bleibt draussen; Bau erst nach dem Merge von #117; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0286, R-0287, R-0297 (Kurz-Ledger ohne Spec)
Heavy: linux-full — T1 ändert Zeilen in upgrade_path_test, integration_stack_test und backup_restore_test, die nur auf dem Stack laufen; `run.sh integration` auf einer Pool-VM belegt sie (Teststrategie der Aufsicht, 2026-10-11).
Hängt ab von: harness/flake-paket (#117) — sonst meldet der Wächter aus T1 die zehn Stellen in diagnostics_test.sh, die #117 umstellt; erst nach dem Merge bauen und origin/main vorher hineinmergen.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-11 von Worker A für die Aufsicht (adminhelper-ac). Kevin hat die drei Zeilen am 2026-10-11 in der
Triage als Harness-Paket angenommen. Zeilenangaben origin/main@8e31cf71; beim Bau an Symbolen orientieren.

Überschneidungen:
- #118 (feature/device-certificate-register) fügt in backup_restore_test.sh, integration_stack_test.sh und
  restore_guard_test.sh Zeilen ein, nicht an den Stellen aus T1. Die Zeilennummern verschieben sich, und der zweite
  PR mergt.
- #119 (harness/team-rules) ändert heavy_test.sh:512, T1 dort andere Zeilen.
- Der neue stack_pytest_test.sh aus #118 ist für den Wächter aus T1 sauber (geprüft).

Offene Fragen am Gate:
1. Heavy: none, obwohl T1 vier Zeilen in drei Tests ändert, die nur auf dem Stack laufen: upgrade_path_test (:218,
   :282), integration_stack_test (:174), backup_restore_test (:83).
   - Empfehlung: none. Es ist eine reine Formänderung, Here-String statt Pipe; Muster und Verknüpfung bleiben.
   - Statisch prüfen `bash -n`, shellcheck (deckt scripts/tests/*.sh ab) und der Wächter selbst.
   - integration_stack läuft nach dem Merge im CI auf main (Job integration-stack, nur außerhalb von PRs).
     upgrade_path und backup_restore laufen im nächsten Wochenlauf.
   - Im PR steht dafür „auf dem Stack nicht verifiziert“.
   - Alternative: `linux-full`, also `run.sh integration` auf einer Pool-VM.
2. `echo` gehört mit in den Umfang. Die Zeile R-0286 zählt 23 `printf`-Stellen. Der Wächter mit eingebauten
   Schreibern findet dazu 15 Zeilen mit `echo`-Pipes in sechs Dateien.
   - Empfehlung: mitnehmen. Es ist derselbe Mechanismus, und ein Wächter nur für `printf` ließe ihn offen.
3. R-0297 lässt zwei Wege offen: (a) der Lint lehnt die Mehrzeilen-Form ab; (b) `review.sh task_field` liest alle
   Zeilen.
   - Empfehlung: (a).
   - tasks/README.md (:94, :154) beschreibt die Ankündigung schon als eine Zeile mit `;`.
   - Der Lint läuft am Gate, der Fehler fällt also auf, bevor ein Bau ihn trifft.
   - Die Ausnahme-Prüfung im Diff-Scan bleibt so schmal, wie sie ist.
   - Trade-off: Bei vielen Ankündigungen wird die Zeile lang; team-rules T2 hatte vier Tests in einer Zeile.
   - (b) wäre bequemer, ändert aber den Gate-Code, README und review_scripts_test.
4. runner-setup.sh:304 klont ebenfalls mit `--no-hardlinks` aus dem Checkout. Es ist ein sudo-Skript des
   eingefrorenen Runners, und runner_setup_test hält den Befehl wörtlich fest.
   - Empfehlung: nicht in diesem Paket und keine eigene Zeile. Ein gescheiterter Klon dort ist sichtbar und
     wiederholbar.

### T1 — Der Wächter kennt eingebaute Schreiber; die Stellen lesen per Here-String (R-0286)  [x]
Komponente: scripts · Dateien: scripts/tests/pipe_guard_test.sh, scripts/tests/heavy_test.sh, scripts/tests/doc_smoke_test.sh, scripts/tests/upgrade_path_test.sh, scripts/tests/update_test.sh, scripts/tests/toolchain_lockstep_test.sh, scripts/tests/sync_check_test.sh, scripts/tests/openapi_breaking_test.sh, scripts/tests/desktop_e2e_skip_test.sh, scripts/tests/check_versions_test.sh, scripts/tests/agent_install_test.sh, scripts/tests/restore_guard_test.sh, scripts/tests/install_test.sh, scripts/tests/integration_stack_test.sh, scripts/tests/backup_restore_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ce19ccfb 2026-10-12T05:44:36+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `pipe_guard_test.sh` zählt `printf` und `echo` zu den Schreibern: `many()` (:56) und der Vorfilter (:114), der
  heute nur Zeilen mit `git` liest.
  - Ein eingebauter Schreiber vor einem früh endenden Leser ist ein Fund, gleich wie lang die Ausgabe ist. Früh
    endende Leser sind `grep -q/-m/-l`, `head` und `sed …q`.
  - Der Kopf der Datei (:11) nennt die Regel.
- Neue Fälle im Selbsttest:
  - `hit`: `printf '%s' "$x" | grep -q y`, `echo "$x" | grep -qi y` und `printf '%s\n' "$@" | head -1`;
  - `clean`: `grep -q y <<<"$x"`, `printf '%s' "$x" | grep -c y` und eine solche Pipe in Anführungszeichen.
- Die Stellen lesen per Here-String: `grep -q <muster> <<<"$x"` statt `printf '%s' "$x" | grep -q <muster>`.
  - Muster, Flags und Verknüpfung (`&&`, `||`, `!`, `if`/`elif`) bleiben.
  - `agent_install_test.sh:76` steht in einem Fake-Skript im Heredoc (bash). Die Stelle wird ebenso umgestellt,
    mit `\$`.
- Die Stellen auf origin/main@8e31cf71, gefunden mit einem Prototyp des erweiterten Scans:
  - `printf`, 23 Stellen:
    - heavy_test.sh: :225, :717, :724, :746, :754, :764, :772, :807, :1092, :1154;
    - doc_smoke_test.sh: :66, :102, :137, :139;
    - upgrade_path_test.sh: :218, :282;
    - je eine in toolchain_lockstep_test.sh:92, sync_check_test.sh:96, openapi_breaking_test.sh:76,
      desktop_e2e_skip_test.sh:64, check_versions_test.sh:68, update_test.sh:246 und agent_install_test.sh:76.
  - `echo`, 15 Zeilen mit 16 Pipes:
    - update_test.sh: :143, :149, :156, :182;
    - agent_install_test.sh: :142, :154, :170;
    - restore_guard_test.sh: :55 (zwei Pipes), :60, :64, :68;
    - install_test.sh: :114, :122;
    - integration_stack_test.sh:174 und backup_restore_test.sh:83.
  - Die zehn Stellen in diagnostics_test.sh stellt #117 um.
Rot vorher:
- Der erweiterte Wächter meldet auf main, mit #117, die 38 Zeilen oben.
- Die neuen `hit`-Fälle des Selbsttests fallen mit dem alten `many()`.
Beweis:
- origin/main@8e31cf71, Prototyp des erweiterten Scans über scripts/tests/*_test.sh: 48 Treffer in 16 Dateien, davon
  10 in diagnostics_test.sh.
- Auf harness/flake-paket@485599ff sind diagnostics_test.sh und ledger_loop_test.sh für den Prototyp sauber.
- Der Mechanismus ist deterministisch (Flake-Paket T2): `printf` von 300 kB in `grep -q` endet unter pipefail mit 141,
  als Here-String mit 0.
- heavy_test.sh:754 ist eine Negativprüfung. Endet der Schreiber mit 141, wertet `&&` den Treffer als „kein Treffer“,
  und der Fall wird grün, obwohl der Text da ist.
Metrik: erweiterter Scan von pipe_guard_test (POSIX awk): 38 → 0 Treffer (Zeilen).
Orakel: mutation-sample — Gegenprobe: eine Stelle zurück auf die Pipe-Form, der Wächter fällt.
Dedup-Key: ref:scripts:tests:printf-pipe-grep-pipefail
HEAD: 8e31cf71
Semantik: `docs/developer/cicd.html:99–101` „reruns bleibt bewusst 0: der Wochenlauf wiederholt einen roten Schritt
selbst und klassifiziert ihn, statt die Suiten heimlich retryen zu lassen“. Ein Test, der an seinem eigenen Schreiber
scheitert, ist ein Flake der Suite selbst.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; der Kopf von pipe_guard_test.sh nennt die Regel)

### T2 — Fixture-Klone und builder-home.sh setup klonen mit --no-local (R-0287)  [x]
Komponente: scripts · Dateien: scripts/tests/builder_home_test.sh, scripts/tests/review_scripts_test.sh, scripts/dev/builder-home.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @bb5df25a 2026-10-12T05:56:35+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `git clone --no-local` an vier Stellen:
  - builder_home_test.sh:48 (`--bare` aus `$MAIN`);
  - builder_home_test.sh:223 (aus `$ORIGIN`);
  - review_scripts_test.sh:2067 (aus `$PREMOTE`);
  - builder-home.sh:152 in `setup_clone`: heute `--no-hardlinks` aus dem Checkout, in dem `setup` läuft, im Betrieb
    Kevins Haupt-Checkout.
- Git holt die Objekte dann über den Transport, statt das Objektverzeichnis Datei für Datei zu kopieren oder zu
  verlinken. Eine Datei, die ein paralleler git-Prozess dort anlegt oder entfernt, trifft den Klon nicht mehr. Ein
  solcher Prozess ist eine andere Session oder ein `git maintenance --detach` nach einem Commit.
- Je eine Prüfung wie „repo wiring“ in ledger_loop_test (#117): Kein `git clone` steht ohne `--no-local`.
  - builder_home_test.sh prüft sich selbst und builder-home.sh.
  - review_scripts_test.sh prüft sich selbst.
- Nicht dabei ist runner-setup.sh:304 (offene Frage 4).
Rot vorher:
- Die neuen Prüfungen fallen auf main, denn dort stehen vier Klone ohne `--no-local`.
- Der Lauf selbst ist nicht deterministisch rot, wie bei R-0262.
Beweis:
- R-0262 (Flake-Paket T1): CI main 7600dc25, run 37976635971, `fatal: hardlink different from source at
  …/multi-pack-index.lock` beim lokalen Klon aus einem Fixture-Origin.
- Code: Die vier Stellen klonen aus einem lokalen Pfad ohne `--no-local`. builder-home.sh:152 klont aus dem Checkout,
  in dem zur selben Zeit andere Sessions git fahren.
- Das Repo hat 46 MB unter `.git`; der Klon über den Transport kostet Sekunden.
- Lokal nicht reproduziert, wie R-0262. `--no-local` nimmt das Wettrennen unabhängig von der Ursache weg.
Dedup-Key: ref:scripts:tests:local-clone-no-local
HEAD: 8e31cf71
Semantik: wie T1.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T3 — ledger.sh lint lehnt eine zweite Ankündigungszeile je Task ab (R-0297)  [ ]
Komponente: scripts · Dateien: scripts/dev/ledger.sh, scripts/tests/ledger_test.sh, tasks/README.md
Änderung:
- `ledger.sh lint` (Schleife über `Test-Löschung` und `Assertion-Änderung`, :312) meldet eine Task, die eine der
  beiden Zeilenarten zweimal trägt, als Fehler mit Exit 1. Die Meldung: „<id>: two <field>: lines — diff-scan reads
  only the first; join the entries with ; (tasks/README.md)“.
- tasks/README.md beschreibt die Form schon als eine Zeile mit `;` (:94, :154). Punkt 2 unter `Test-Löschung:` (:110)
  und unter `Assertion-Änderung:` (:163) bekommt den Halbsatz, dass `ledger.sh lint` eine zweite Zeile ablehnt.
- `review.sh task_field` (:225) bleibt, wie es ist (offene Frage 3).
- Fälle in ledger_test.sh, bei den Fällen der Ankündigungen (:291–322):
  - eine Task mit zwei `Assertion-Änderung:`-Zeilen ergibt Exit 1 mit der Meldung;
  - dieselben Einträge in einer Zeile mit `;` linten sauber;
  - dasselbe gilt für `Test-Löschung:`;
  - zwei Tasks mit je einer Zeile linten sauber.
- Kein Ledger auf origin/main@8e31cf71 trägt die Mehrzeilen-Form (geprüft), ledger_test bleibt also für die echten
  Ledger grün.
Rot vorher: Auf main lintet die Task mit zwei Zeilen sauber (Exit 0).
Beweis:
- Bau team-rules T2, harness/team-rules@38d1a72c: vier `Assertion-Änderung:`-Zeilen, `ledger.sh lint` sauber.
  `task-close.sh` endete mit Exit 3: diff-scan las nur die erste Zeile und meldete test_show_the_overview als entfernte
  Assertion.
- Die Korrektur 6a84ec9c fasste die Zeilen zu einer zusammen.
- Code: `task_field` (review.sh:225–231) endet nach der ersten passenden Zeile (`exit`). Der Lint (ledger.sh:312–320)
  liest jede Zeile einzeln und prüft nur ihre Form.
Dedup-Key: ref:scripts:review.sh:task_field-multiline
HEAD: 8e31cf71
Semantik: tasks/README.md:154 „Assertion-Änderung: <datei>::<test> — <Grund>[; <datei>::<test> — <Grund> …]“ und :94
für `Test-Löschung:`. Die Syntax der Ledger steht unter tasks/, nicht unter docs/.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: tasks/README.md (zwei Halbsätze)
