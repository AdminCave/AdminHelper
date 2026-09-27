<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Lane-Sidecar als Kopie (R-0094) — Task-Ledger
Status: geplant · Branch: harness/lane-sidecar-copy · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Spec: Roadmap R-0094
Heavy: none — nur das lokale Lane-Werkzeug und sein hermetischer Test; vm.py, bootstrap_linux.sh, Stack und Install-Pfad bleiben unverändert, die Box-Seite belegt der Test mit echtem rsync.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-09-27 von der Aufsicht (adminhelper-ac) auf Kevins Wort, zusammen mit fünf anderen Vorhaben.
Branch `harness/`, weil T1 `AUTONOMOUS.md` ändert (Harness-Pfad): Bau interaktiv, keine Lane
(`lane.sh new` legt fest `feature/<slug>` an).

### T1 — `lane.sh new` kopiert das frpc-Sidecar statt es zu verlinken  [ ]
Komponente: scripts · Dateien: scripts/dev/lane.sh, scripts/tests/lane_test.sh, AUTONOMOUS.md
Änderung: `lane_new` (lane.sh:211) kopiert die Einträge von `apps/desktop/src-tauri/binaries` mit `cp -p`
(dereferenzierend, Modus bleibt) in ein echtes Verzeichnis der Lane, statt `lane_link_dir` zu rufen; ein
fehlschlagendes `cp` warnt, bricht `new` aber nicht ab. Die Komponenten-Venvs bleiben Links
(`rsync-exclude.txt:14` hält `.venv` ohnehin von der Box). `done` bleibt unverändert: `git worktree remove`
(lane.sh:290) nimmt die gitignorte Kopie mit. Kommentare lane.sh:14, :104–112 und :208–210 nachziehen.
Test: lane_test.sh:198–199 („the frpc sidecar is linked") wird zu „reguläre, ausführbare Datei, `! -L`, `cmp`
gleich dem Sidecar des Haupt-Checkouts"; die Fixture (:66–71) bekommt `chmod +x`. Dazu der Symptom-Fall:
`rsync -a` der `binaries/` der Lane in ein Box-Verzeichnis, Haupt-Sidecar kurz beiseite, dann `[ -e box/frpc-… ]`.
Ohne Fix sind beide Prüfungen rot (symbolic link bzw. `test -e` falsch). :204–205 bleibt (done lässt das
Haupt-Sidecar stehen).
Beweis: origin/main@70e91718 · `lane_link_dir` aus lane.sh in ein Wegwerf-Verzeichnis, dann `rsync -az --exclude-from scripts/vm/rsync-exclude.txt --delete <lane>/ <box>/` und den Haupt-Pfad entfernen → `test -e rc=1`, `cp: not writing through dangling symlink`; die neue Assertion gegen ein echtes `lane.sh new` dreimal identisch rot: `FAIL sidecar: expected a regular file, got symbolic link -> …/binaries/frpc-x86_64-unknown-linux-gnu`
Semantik: AUTONOMOUS.md:129–131 — „frpc-Sidecar und Komponenten-Venvs mit dem CI-ruff als Links in den Haupt-Checkout, nur zum Lesen — die Links sperren nichts, installiert wird ins eigene Venv der Lane" (gemeint ist der lokale Gebrauch; für die Box sagt die Doku nichts, `DEVELOPMENT.md:1170` verspricht „Der Sync aus Worktrees ist validiert")
Dedup-Key: bug:scripts:lane.sh:sidecar-symlink
HEAD: 70e91718
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: AUTONOMOUS.md „Parallel-Betrieb" Z. 129–131 (Sidecar als Kopie; Grund: vm.py sync überträgt einen Link als Link)
