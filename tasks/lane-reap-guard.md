<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket lane-reap-guard: reap nur in der eigenen Lane, kein getrackter Zustand unter .vm (R-0317, R-0318) — Task-Ledger
Status: aktiv · Branch: harness/lane-reap-guard · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-12 (kleines Fund-Paket, Triage und Reihenfolge Kevin 2026-10-12; Fragen 1-3 wie empfohlen: die Regel gilt fuer alle drei Filter, eine unpassende VMID lehnt den ganzen Aufruf ab, kein mkdir fuer .claude; T2/T3 erst nach dem Merge von harness-rest; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0317, R-0318 (Kurz-Ledger ohne Spec)
Heavy: none — vm.py (destroy), reap.sh und lane.sh mit hermetischen Tests: pytest gegen die Fake-API von test_vm, Fake-vm.py in vm_wrappers_test und lane_test, Fixture-Repos. Kein echtes destroy, kein Stack-, Gateway-, PKI- oder Install-Pfad.
Hängt ab von: harness/harness-rest — T2 und T3 ändern lane.sh und lane_test.sh, die harness-rest (T5–T7: Prüfschleife in
lane_new, Zustandsprüfung in lane_done) auch ändert. Erst nach dessen Merge bauen und origin/main vorher hineinmergen.
T1 hängt nicht daran.
DoD je Task: CLAUDE.md (Tests grün, shellcheck/ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-12 von Worker A für die Aufsicht (adminhelper-ac). Kevin hat die Zeilen am 2026-10-12 angenommen.
Zeilenangaben: vm.py, reap.sh und die Doku nach origin/main@2ebdef55, lane.sh und lane_test.sh nach
harness/harness-rest@aea75df3. Beim Bau an Symbolen orientieren.

Vorab geprüft:
- `vm.py` ist ein Harness- und Lab-Pfad. Für Plan und Bau gilt deshalb:
  - Proben und Tests laufen nur gegen Fakes: die aufgezeichnete Fake-API von test_vm (`purgeable`, `current_of`,
    Fixture `cluster_resources`) und die Fake-vm.py-Rekorder in vm_wrappers_test und lane_test.
  - Nie ein echtes `destroy`, nie `settings.local.json` oder `pve.env` lesen.
- Heute ruft niemand `destroy` mit VMIDs und einem Filter zugleich auf (`git grep` über scripts/, .claude/ und die
  Doku, origin/main@2ebdef55). Die neue Bedeutung dieser Kombination bricht also keinen Aufrufer.
- Die Tests der Shell-Seite (`ok`/`bad`) sind für `diff-scan` keine Assertions. Die geänderte Erwartung in
  vm_wrappers_test (T1) braucht deshalb keine `Assertion-Änderung:`. Der Review sieht sie im Diff.

### T1 — reap zerstört nur Boxen der eigenen Lane: destroy mit VMIDs und Filter verlangt, dass beide passen  [x]
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/reap.sh, scripts/vm/tests/test_vm.py, scripts/tests/vm_wrappers_test.sh, DEVELOPMENT.md, AUTONOMOUS.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @1db98a16 2026-10-12T17:42:10+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `vm.py destroy`: Werden VMs genannt und zugleich `--lane`, `--scenario` oder `--role` gegeben, muss jede genannte VM
  zu jedem gegebenen Filter passen.
  - Die Filter fügen dann keine VMs mehr hinzu. Heute vereinigt `select_vms` (:1385–1418) beides.
  - Passt eine genannte VM nicht, endet `destroy` mit Exit 2 (`Usage`), bevor irgendetwas zerstört ist. Die Meldung
    nennt die VMID, den Filter und den Wert der VM, etwa `3000 is on lane main, not pilot — refusing`.
  - Geprüft wird am frischen Zustand (die Tags aus `status/current`), an derselben Stelle wie `require_ours` in
    `verb_destroy` (:1421–1438), nicht am Cache der Auswahl.
  - Ohne Filter bleibt `destroy <vmid>` wie es ist: der Weg von Hand, den reap.sh :15 für eine Box einer anderen
    Lane nennt. Filter allein bleiben ebenfalls, wie sie sind.
- `reap.sh` (:40–48) nennt die Warm-Slots mit der eigenen Lane: `vm_py destroy --lane "$LANE" "${IDS[@]}"`. Der Kopf
  (:17–19) sagt, dass vm.py einen Slot einer anderen Lane ablehnt.
- Tests in test_vm.py (Fixture: 3000 auf Lane `main`, 3001 auf Lane `pilot`):
  - `destroy 3000 --lane pilot` wird abgelehnt, ohne DELETE.
  - `destroy 3000 3001 --lane pilot` wird ganz abgelehnt, auch 3001 steht noch.
  - `destroy 3001 --lane pilot` zerstört 3001 und nichts sonst, auch wenn eine weitere VM die Lane `pilot` trägt.
  - Der Cache nennt Lane `pilot`, `status/current` aber Lane `main`: abgelehnt.
  - Dasselbe für `--role` oder `--scenario` in einem Fall.
- Tests in vm_wrappers_test: Der Fall `reap.sh` erwartet `destroy --lane main 3001 3002` statt `destroy 3001 3002`.
  Der Fall `reap.sh --lane pilot-two` mit zwei Slots erwartet `destroy --lane pilot-two …`.
Rot vorher: Auf main zerstört `destroy 3000 --lane pilot` die VM 3000 der Lane `main`, und reap.sh ruft `destroy` ohne
`--lane`.
Beweis:
- origin/main@2ebdef55, vm.py `select_vms` :1388–1390 nimmt jede genannte VM, :1408–1417 fügt die Treffer der Filter
  hinzu.
- `verb_destroy` :1431–1436 prüft die genannten VMs nur mit `require_ours` (Tag `ah`, kein Template).
- reap.sh :47 `vm_py destroy "${IDS[@]}" …`, ohne `--lane`.
HEAD: 2ebdef55
Semantik: AUTONOMOUS.md :165–169 („Jede VM trägt den Tag `lane-<slug>`, und `reap` … arbeiten auf der eigenen Lane
— Lanes können sich nicht gegenseitig die Boxen abräumen“) und `.claude/skills/vm/SKILL.md` :74–75 („`reap` und
`destroy` arbeiten auf der eigenen Lane“).
- Der Nachsatz AUTONOMOUS.md :171–172 bzw. DEVELOPMENT.md :1814–1815 („eine ausdrücklich genannte VMID wird zerstört —
  darauf beruht `reap.sh`“) beschreibt den Weg von Hand. Für ihn bleibt er wahr.
- Unter docs/ gibt es keine Stelle zu `destroy` oder `reap.sh`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku:
- DEVELOPMENT.md: Zeile `destroy` der vm.py-Tabelle (:1714) und der Lane-Absatz (:1814–1815).
- AUTONOMOUS.md: Klammersatz :171–172. reap.sh nennt die VMIDs aus der warm.env mit `--lane` der eigenen Lane, und
  vm.py lehnt eine VMID ab, die nicht dazu passt.
- Beide Dateien gibt es nur auf Deutsch. CHANGELOG nicht (intern).

### T2 — lane.sh new lehnt getrackten Zustand unter .vm ab; der Kopierschritt nennt den Rückweg (R-0317)  [x]
Komponente: scripts · Dateien: scripts/dev/lane.sh, scripts/tests/lane_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @74303daf 2026-10-12T17:58:36+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `lane_new`: Direkt nach `git worktree add` und vor der Prüfschleife (:250) prüft `new`, ob der Branch Pfade unter
  `.vm` trackt (`git -C "$wt" ls-files -- .vm`).
  - `.vm` ist der Zustand der Lane, gitignored, und gehört nicht in einen Branch.
  - Trägt der Branch dort etwas, endet `new` mit Exit 1 und schreibt nichts nach `.vm`. Die Meldung nennt den Pfad in
    der Lane und `run: bash scripts/dev/lane.sh done <slug>`, wie die Schritte von harness-rest T5–T7.
  - Scheitert `ls-files` selbst, gilt das als Ablehnung (fail closed).
- `lane_done`: Die Zustandsprüfung (:350) nimmt dazu: Trackt der Branch der Lane Pfade unter `.vm`, liest `done`
  keinen Zustand aus ihr.
  - Es folgt ein WARN wie beim Symlink (:353), dann der Weg ohne Worktree (`destroy --lane <slug>`, :360–361).
  - Das deckt auch einen Branch, der `.vm`-Pfade erst nach `new` committet hat.
- R-0317, der Kopierschritt (:272–273): `[ -f … ] && cp …` endet bei einem Fehler über `set -e` ohne Hinweis.
  - Neu: `[ ! -f .claude/settings.local.json ] || cp --remove-destination … || { echo "  lane.sh: could not copy
    .claude/settings.local.json"; echo "  run: bash scripts/dev/lane.sh done $slug"; exit 1; }`.
  - Das ist dieselbe Form wie bei `.devenv.sh` (:274–275). Kein `mkdir -p`: das echte Repo trackt `.claude/`.
- Fälle in lane_test:
  - Ein Plan-Branch trackt `.vm/warm.env` als Datei mit Platzhalter-VMIDs. `new` endet mit Exit 1, nennt `.vm` und
    `run: … done <slug>`. In der Lane steht kein `.vm/lane`, der Haupt-Checkout bleibt unverändert (cmp-Marke).
  - Danach `done` für diesen Branch: Exit 0, ein WARN. Im VM-Log steht `destroy --lane <slug>` und keine der
    Platzhalter-VMIDs. Die Lane ist weg.
  - Ein Plan-Branch ohne `.claude/`, im Haupt-Checkout liegt `settings.local.json` (Platzhalter). `new` endet mit
    Exit 1, nennt `.claude/settings.local.json` und `run: … done <slug>`. `done` räumt die Lane ab.
Rot vorher:
- Auf harness/harness-rest@aea75df3 legt `new` die Lane für einen Branch mit getracktem `.vm/warm.env` an und schreibt
  `.vm/lane` daneben. `done` liest danach den Zustand aus diesem `.vm`.
- Der Kopierschritt endet ohne `run: … done`.
Beweis:
- harness/harness-rest@aea75df3: lane.sh :250–263 prüft nur die drei Pfade, die `new` schreibt, :350 nur Symlink und
  `lane_inside` von `.vm`.
- :272–273 `[ -f .claude/settings.local.json ] && cp --remove-destination …` ohne `||`.
- Fund: Kontrolle harness-rest T7, Worker A, 2026-10-12.
Dedup-Key: ref:scripts:lane.sh:claude-copy-hint
HEAD: aea75df3
Semantik:
- DEVELOPMENT.md :1808–1811 und lane.sh :241–244: `.vm/lane` und `settings.local.json` entstehen in der Lane durch
  `new`. Der Zustand unter `.vm` ist der der Lane, nicht der eines Branches.
- lane.sh :264–267 und :275: Ein Schreibschritt, der scheitert, nennt den Rückweg `done`.
- Unter docs/ gibt es keine Stelle zu `lane.sh`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T3 — lane_test: der Normalfall mit getracktem .claude/ (R-0318)  [x]
Komponente: scripts · Dateien: scripts/tests/lane_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @7b5d8fcb 2026-10-12T18:17:22+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- Das Fixture trackt heute kein `.claude/`. Der Normalfall des echten Repos ist nicht getestet: `.claude/` getrackt,
  `settings.local.json` im Haupt-Checkout, die Lane kopiert sie.
- Neuer Fall mit eigenem Plan-Branch, der `.claude/settings.json` (Platzhalter) trackt. Im Haupt-Checkout liegt
  `.claude/settings.local.json` mit Platzhalter-Inhalt. Erwartet nach `new`:
  - Exit 0.
  - `.claude/settings.local.json` in der Lane ist eine Datei, kein Symlink, und inhaltsgleich (cmp).
  - Die Datei im Haupt-Checkout ist unverändert (cmp-Marke).
  - `.claude/settings.json` des Branches ist unverändert.
  - `git -C <lane> status --porcelain` ist leer: Die Kopie ist ignoriert, nicht untrackt.
- Danach `done`: Exit 0, die Lane ist weg, die Datei im Haupt-Checkout steht unverändert.
- Nur Platzhalter. Nichts liest die echte `settings.local.json`.
Rot vorher: keiner, der Fall deckt bestehendes Verhalten ab. Gegenprobe: ohne den Kopierschritt in lane.sh ist der Fall
rot, mit `ln -s` statt `cp` ebenso.
Beweis: harness/harness-rest@aea75df3, lane_test.sh :63 legt `$MAIN/.claude` an, trackt aber nichts darin. :347 („no
.claude/, and a copy into nothing would end new“) zeigt, dass die Fälle den Kopierschritt umgehen.
Dedup-Key: ref:scripts:lane_test.sh:claude-happy-path
HEAD: aea75df3
Semantik: DEVELOPMENT.md :1808–1810 („`.claude/settings.local.json` als **Kopie** — Claude Code schreibt die Datei bei
Permission-Grants, ein Symlink waere ein geteiltes Write-Target aller Lanes“).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T4 — Nachbesserung aus dem Review am Ende: nichts zerstört auch hinter einer passenden VM, eindeutige Tags, Marke in par-vm-tracked  [x]
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/tests/test_vm.py, scripts/tests/lane_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @36f6093b 2026-10-12T19:00:54+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Angelegt 2026-10-12 aus dem Review am Ende (Opus, `request_changes`: ein belegter Fund, zwei nits).
- T1, Test: `test_destroy_refuses_a_named_vm_of_another_lane_and_destroys_nothing` lehnt eine VM ab, die vor der
  passenden sortiert.
  - Eine Prüfung, die erst beim Zerstören liefe, bliebe damit grün. Der Reviewer hat das als Mutante geprobt.
  - Neu: ein Fall, in dem die abgelehnte VM nach der passenden kommt (`destroy 3000 3001 --lane main`). Abgelehnt
    wird 3001, und `DELETE` gibt es keins.
- nit, T1, `require_selected`: Trägt eine VM zwei Tags eines Präfixes (`lane-main` und `lane-pilot`), liest
  `tag_value` den ersten aus einem Set, und welcher das ist, hängt von `PYTHONHASHSEED` ab.
  - Neu: Die Prüfung vergleicht alle Werte des Präfixes. Sie passt nur, wenn genau der verlangte dasteht, bei der Lane
    ohne Tag weiter `main`.
  - Die Meldung nennt alle Werte. Dazu ein Fall in test_vm.
  - Die Auswahl über Filter allein bleibt, wie sie ist.
- nit, T2, lane_test `par-vm-tracked`: Die cmp-Marke im Haupt-Checkout, die das Ledger nennt, kommt dazu
  (`$MAIN/.vm/warm.env` und die Marke, wie in `par-vm-main`).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
Abhängt von: T1, T2

### T5 — lib.sh und vm.py lesen die Lane nicht aus getracktem Zustand  [ ]
Komponente: scripts · Dateien: scripts/vm/lib.sh, scripts/vm/reap.sh, scripts/vm/warm.sh, scripts/vm/vm.py, scripts/tests/lib_vm_test.sh, scripts/vm/tests/test_vm.py, DEVELOPMENT.md
Review: Nachbesserung, Opus-Review über T4 und T5 folgt
Änderung: Angelegt 2026-10-12 auf Entscheidung der Aufsicht (adminhelper-ac), aus dem Review am Ende.
- `vm_lane` (lib.sh) und `current_lane` (vm.py) nehmen die Lane aus `--lane`, sonst aus `AH_LANE`, sonst aus
  `.vm/lane`.
  - Kommt sie aus der Datei, und trackt der Checkout, zu dem das Werkzeug gehört, Pfade unter `.vm`, lehnen beide ab:
    Exit 2, die Meldung nennt keinen Wert.
  - Geprüft wird mit `git ls-files -- .vm`. Ein Fehler von git zählt als Treffer.
  - Mit `--lane` oder `AH_LANE` wird die Datei nicht gelesen und git nicht gefragt.
- `reap.sh` und `warm.sh` enden dann mit Exit 2, bevor sie vm.py aufrufen oder die warm.env ändern.
- Tests, kein echtes destroy:
  - lib_vm_test mit einem tmp-Repo als Checkout, das `.vm/lane` trackt: `vm_lane` Exit 2, `reap.sh` Exit 2 ohne einen
    Aufruf an die Fake-vm.py, die warm.env unverändert.
  - Ungetrackt bleibt es wie bisher.
  - test_vm mit tmp-Repo: `current_lane` wirft `Usage`. Mit `AH_LANE` oder `--lane` ist kein git nötig.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md, Lane-Absatz („Sie kommt aus `--lane`, sonst aus `AH_LANE`, sonst aus `.vm/lane`“).
Abhängt von: T1
