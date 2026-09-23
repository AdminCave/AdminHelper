<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Lane-Isolation: eigene Test-DB, Lauf-Sperre, vollständige Lane, sicheres Aufräumen — Task-Ledger
Status: geplant · Branch: harness/lane-isolation · Commit-Granularität: pro Task · Review: pro Task (Sonnet, 10 min) · Modell: Opus
Spec: dieses Ledger (Harness-Vorhaben; AUTONOMOUS.md „Parallel-Betrieb", scripts/dev/lane.sh)
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: nein — der Diff berührt `scripts/dev/lane.sh`, `scripts/tests/run.sh`, ein neues Testskript und die Doku. Abschluss-Beweis ist ein echter Lane-Durchlauf (unten), keine VM-Suite.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: Als Nächstes Nr. 2 (Voraussetzung für zwei parallele Python-Bauten) · Hängt ab von: —

## Warum — fünf Belege, alle aus echten Läufen

1. **2026-09-18, geteilte Test-DB:** `lane.sh new` verlinkt `.devenv.sh` in die Lane, beide Checkouts zeigen auf dieselbe `AH_TEST_DB`. Die `pg_engine`-Fixture des Stufe-4-Laufs räumte per `drop_all` ab, im parallelen 8b-Lauf hieß es dann „Relation users existiert nicht“, und zwei Läufe waren entwertet.
2. **2026-09-21, OOM:** Zwei Schemathesis-Läufe gleichzeitig, einer in der Lane und einer im Haupt-Checkout. Die Dev-Box (32 GB) hat den OOM-Killer ausgelöst.
3. **2026-09-22, parallele pytest-Sitzungen** auf derselben DB, wieder ein entwerteter Lauf.
4. **2026-09-22, Session im gelöschten Verzeichnis:** `lane.sh done` hat die 8b-Lane entfernt, während eine Worker-Session mit Arbeitsverzeichnis darin noch lief. Die Session hing danach in einem gelöschten cwd und war nicht mehr arbeitsfähig.
5. **2026-09-23, Verifikation im Worktree:** Für die PR-Prüfung von #38 musste ich eine eigene Test-DB, ein eigenes Venv und das CI-`ruff` von Hand in einen Worktree legen. Ohne `.devenv.sh` findet `run.sh` kein `ruff`, und der Lauf endet `strict-failed`. Die lokalen Cache-Venvs haben außerdem ein neueres `ruff` (0.16.8) als CI (0.15.20). Die Komponenten-Venvs des Haupt-Checkouts tragen das CI-`ruff` (R-0074).

## Ablauf der Plan-Dateien (Kevins Entscheidung vom 2026-09-22, Roadmap R-0065)

Spec und Ledger sind der **erste Commit des Feature-Branches**, gesetzt am Gate. Eine Lane checkt diesen Branch aus und sieht den Plan damit von selbst. Das Kopieren nicht eingecheckter Plan-Dateien, wie es die alte Fassung von T2 vorsah, entfällt deshalb. Die Anpassung von `feature-plan/SKILL.md` und `AUTONOMOUS.md` an R-0065 bleibt ein eigenes Vorhaben. Hier wird nur `lane.sh` passend gemacht.

### T1 — Test-DB und Python-Venv je Lane  [ ]
Komponente: scripts · Dateien: scripts/dev/lane.sh, scripts/tests/lane_test.sh (neu, SPDX), scripts/tests/run.sh (nur `AH_SCRIPT_TESTS_DEFAULT`)
Änderung: `lane.sh new <slug>` legt statt des Symlinks eine eigene `.devenv.sh` in die Lane. Sie sourct Kevins Datei und überschreibt danach zwei Werte: `AH_TEST_DB` auf die Datenbank `adminhelper_test_<slug>` (Bindestriche werden zu `_`) und `AH_VENV` auf `~/.cache/ah-venv-<slug>`, nie `/tmp`. `new` legt die DB mit der bestehenden Rolle an (`createdb`, die Rolle hat `CREATEDB`, geprüft am 2026-09-23). `lane.sh done` löscht die DB (`dropdb --if-exists`) und das Lane-Venv. Test: Er läuft hermetisch mit Fake-`createdb`/`dropdb` im PATH, die ihre Aufrufe protokollieren, und einem Wegwerf-Git-Repo als Haupt-Checkout. Geprüft wird: Die Lane-`.devenv.sh` ergibt eine andere `AH_TEST_DB` als der Haupt-Checkout, `done` löscht genau diese DB, und ein Slug mit Sonderzeichen erreicht nie `createdb`. Gegenprobe: Mit dem alten Symlink wird der Test rot.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: DEVELOPMENT.md „Python-Tests lokal“ (eine DB je Lane) · AUTONOMOUS.md „Parallel-Betrieb“ (Schritt 2)

### T2 — Host-weite Lauf-Sperre für die schweren Python-Schritte  [ ]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/lane_test.sh
Änderung: `run_py_step` ist die einzige Stelle, durch die jeder Python-Schritt läuft. Dort holen die schweren Schritte (`server-pytest`, `schemathesis`) vorher ein `flock` auf eine host-weite Sperrdatei unter `${XDG_RUNTIME_DIR:-$HOME/.cache}`. Ist die Sperre belegt, **wartet** der Schritt und meldet einmal sichtbar, dass und worauf er wartet; er schlägt nicht fehl. Nach `AH_PY_LOCK_WAIT` Sekunden (Default 3600) gibt er auf. Das Aufgeben ist ein Selbst-Skip mit Grund (Exit 75, der Weg, den `run_py_step` schon kennt), kein FAIL. Unter `--strict` wird der Lauf damit rot, bleibt aber als „nicht gelaufen“ erkennbar, nicht als Befund über den Code. Die übrigen Schritte bleiben parallel. `AH_PY_LOCK=0` schaltet die Sperre ab, gedacht für VMs, auf denen nur ein Lauf existiert. Test: Zwei gleichzeitige Aufrufe mit einem Stub-Schritt laufen nacheinander statt überlappend (Zeitstempel-Protokoll). Eine belegte Sperre mit kurzer Wartezeit endet als SKIP mit Grund, unter `--strict` als `strict-failed`.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: DEVELOPMENT.md „Python-Tests lokal“ (Sperre, Wartezeit, Abschalter) · AUTONOMOUS.md „Parallel-Betrieb“ (ersetzt „nur ein server-Lauf zur Zeit“ als Absprache)
Abhängt von: T1 (gemeinsames Testskript)

### T3 — Die Lane hat, was sie zum Bauen braucht  [ ]
Komponente: scripts · Dateien: scripts/dev/lane.sh, scripts/tests/lane_test.sh
Änderung: `lane.sh new` prüft den Plan dort, wo er nach R-0065 liegt. Existiert `feature/<slug>`, muss `tasks/<slug>.md` **auf diesem Branch** stehen, sonst auf `main`. Fehlt er an beiden Stellen, bricht `new` mit einer klaren Meldung ab, statt wie heute nur zu warnen. Dazu legt `new` zwei Symlinks in die Lane. Das frpc-Sidecar `apps/desktop/src-tauri/binaries/frpc-*` ist gitignored, `cargo test` braucht es aber. Die Komponenten-Venvs `apps/{server,monitoring,ca-issuer}/.venv` des Haupt-Checkouts werden nur gelesen, damit `run.sh` das CI-gepinnte `ruff` findet statt keins. Test: Ein Plan nur auf dem Branch wird gefunden. Ein fehlender Plan bricht `new` ab, bevor ein Worktree entsteht. Die Symlinks zeigen in den Haupt-Checkout.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: AUTONOMOUS.md „Parallel-Betrieb“ (Schritt 1 und 2: der Plan liegt auf dem Branch, `lane.sh new` reicht)
Abhängt von: T1

### T4 — `lane.sh done` räumt keine Lane ab, in der noch etwas läuft  [ ]
Komponente: scripts · Dateien: scripts/dev/lane.sh, scripts/tests/lane_test.sh
Änderung: Bevor `done` VMs oder Worktree anfasst, sucht es Prozesse, deren Arbeitsverzeichnis im Worktree der Lane liegt (`/proc/<pid>/cwd`, eigene Prozesse des Nutzers). Findet es welche, bricht es ab, nennt PID und Kommando und sagt, was zu tun ist: die Session in der Lane beenden und dann `done` erneut aufrufen. Einen Force-Schalter gibt es nicht; das wäre genau der Handgriff, der am 2026-09-22 die Session zerstört hat. Test: Ein Hintergrundprozess mit cwd in einer Fake-Lane lässt `done` mit Exit ≠ 0 abbrechen, VMs und Worktree bleiben unangetastet (Fake-`vm.py`/`reap.sh` protokollieren nichts). Ohne diesen Prozess läuft `done` durch.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: AUTONOMOUS.md „Parallel-Betrieb“ (Schritt 4)
Abhängt von: T1

## Abschluss-Beweis (nach T4, vor dem PR)

Ein echter Lane-Durchlauf auf der Dev-Box:
1. `lane.sh new probe-lane` mit einem Plan nur auf `feature/probe-lane`.
2. In der Lane und im Haupt-Checkout gleichzeitig `verify.sh server --strict`. Beide müssen grün sein, auf zwei verschiedenen DBs, und die Sperre muss die beiden Server-Läufe sichtbar nacheinander fahren.
3. `lane.sh done probe-lane`, einmal mit laufender Shell in der Lane (muss abbrechen) und einmal ohne (muss abräumen, einschließlich DB und Venv).

Ergebnis und Laufzeiten gehören in dieses Ledger.
