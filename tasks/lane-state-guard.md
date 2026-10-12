<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket lane-state-guard: kein getrackter Zustand unter .vm, auch mit gesetzter Lane; warm und run nur auf Boxen der eigenen Lane (R-0329, R-0324) — Task-Ledger
Status: aktiv · Branch: harness/lane-state-guard · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-12 (kleines Fund-Paket, Triage und Reihenfolge Kevin 2026-10-12; Fragen: 1 ein Slot einer anderen Lane wird gemeldet, geleert und neu gewaermt; 2 run und sync pruefen die Lane, die Handwerkzeuge nicht; T1-T3 erst nach dem Merge von #133; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0329, R-0324 (Kurz-Ledger ohne Spec)
Heavy: none — lib.sh, vm.py, warm.sh, iter.sh, reap.sh und heavy.sh mit hermetischen Tests: pytest gegen die Fake-API von test_vm, Fake-vm.py in lib_vm_test, vm_wrappers_test und heavy_test, tmp-Repos. Kein echtes destroy, kein Stack-, Gateway-, PKI- oder Install-Pfad.
Hängt ab von: harness/lane-reap-guard (PR #133) — alle drei Tasks bauen auf dessen Sperre in lib.sh/vm.py und den
Fällen in lib_vm_test/test_vm auf. Erst nach dessen Merge bauen und origin/main vorher hineinmergen.
DoD je Task: CLAUDE.md (Tests grün, shellcheck/ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-12 von Worker A für die Aufsicht (adminhelper-ac). Kevin hat die Zeilen am 2026-10-12 angenommen.
Zeilenangaben nach harness/lane-reap-guard@1c8b6ade (heavy.sh und vm_wrappers_test nach origin/main@bf9d0a5c, dort
unverändert). Beim Bau an Symbolen orientieren.

Vorab geprüft:
- `vm.py` ist ein Harness- und Lab-Pfad. Für Plan und Bau gilt:
  - Proben und Tests laufen nur gegen Fakes und tmp-Repos.
  - Nie ein echtes `destroy`/`run`/`sync`, nie `settings.local.json` oder `pve.env` lesen.
  - Vor jedem Shell-Aufruf von reap/warm/iter: `unset "${!AH_PVE_@}"`, `AH_VM_PY` auf einen Rekorder setzen,
    `AH_PVE_URL` auf einen Platzhalter.
- reap.sh (:34), warm.sh (:28) und iter.sh (:39, nicht im Dry-Run) rufen `vm_lane` vor ihrem ersten `warm_get`,
  `warm_set` oder `warm_clear`. Eine Sperre in `vm_lane` deckt also alle drei.
  - Die Dry-Run-Ausgabe von iter.sh liest `desktop_ttl`, erreicht aber keine Box.
- Die run-Tests in test_vm (:1656ff.) zielen auf 3000, Lane `main`. Heute hängen sie, wie jeder Test, der `current_lane()`
  ohne `state_dir` ruft, an der `.vm/lane` des Checkouts, in dem sie laufen. Mit T2 muss ihre Lane fest stehen.

### T1 — Kein getrackter Zustand unter .vm, auch mit gesetzter Lane  [ ]
Komponente: scripts · Dateien: scripts/vm/lib.sh, scripts/vm/vm.py, scripts/tests/lib_vm_test.sh, scripts/vm/tests/test_vm.py, DEVELOPMENT.md
Änderung:
- Die Sperre aus lane-reap-guard (T5/T6) prüft heute nur, wenn die Lane nicht aus `--lane` oder `AH_LANE` kommt
  (lib.sh `vm_lane` :82, vm.py `current_lane` :570).
  - Neu gilt sie unabhängig von der Herkunft der Lane, sobald das State-Verzeichnis per realpath das eigene `.vm` des
    Checkouts ist.
  - Dann gilt wie bisher: Trackt der Checkout dort Pfade oder antwortet git nicht, folgt Exit 2, und die Meldung
    nennt keinen Wert.
- lib.sh: `vm_lane` ruft die Prüfung immer, nicht nur ohne `AH_LANE`. reap.sh, warm.sh und iter.sh rufen `vm_lane`
  schon vor dem ersten `warm_*`. Bei ihnen ändert sich nichts.
- vm.py: `current_lane` prüft unabhängig von `override` und `AH_LANE`. Dazu prüft `warm_vmids` (:1574), wenn es die
  warm.env des eigenen `.vm` liest, also beim Leak-Abgleich in `list`.
- Ein State-Verzeichnis, das nicht das eigene `.vm` ist, bleibt ungeprüft: `lane.sh done` (`AH_VM_STATE_DIR` der
  Lane und `--lane`) und die Tests.
- Tests, kein echtes destroy:
  - lib_vm_test: Ein Checkout trackt `.vm` als Symlink auf ein Verzeichnis mit warm.env. Mit `AH_LANE` gesetzt
    beziehungsweise `reap.sh --lane <l>` enden reap.sh, warm.sh und iter.sh mit Exit 2, ohne Aufruf an die
    Fake-vm.py, und die warm.env bleibt unverändert.
  - Der Fall „with AH_LANE the file is not read“ (:104) prüft danach Exit 2 statt `from-env`. Das ist eine
    Shell-Prüfung, für diff-scan keine Assertion.
  - test_vm: Getrackter Zustand mit `AH_LANE` oder `override` ergibt `Usage`. `warm_vmids` auf getracktem eigenem
    `.vm` ergibt `Usage`. Ein State-Verzeichnis außerhalb wird wie bisher gelesen.
Assertion-Änderung: scripts/vm/tests/test_vm.py::test_the_lane_is_not_read_from_tracked_state — mit gesetzter Lane (AH_LANE, override) wird getrackter Zustand jetzt ebenso abgelehnt; die beiden Zeilen, die dort die Lane lesen, werden zu Prüfungen auf Usage
Rot vorher: Auf harness/lane-reap-guard@1c8b6ade liest `vm_lane` mit `AH_LANE` gesetzt aus einem Checkout, der
`.vm` trackt, ohne Prüfung. Danach erreichen reap.sh, warm.sh und iter.sh die Fake-vm.py.
Beweis:
- harness/lane-reap-guard@1c8b6ade, lib.sh :82 `if [ -z "$lane" ]; then` umschließt die Prüfung.
- vm.py :574–577: `if not lane:` umschließt `require_untracked_state()`.
- `warm_vmids` (:1574) liest ungeprüft.
- Fund: Kontrolle lane-reap-guard T6, Worker A, 2026-10-12.
HEAD: 1c8b6ade
Semantik:
- AUTONOMOUS.md (Eigene Lane-Kennung je Worktree) „Lanes können sich nicht gegenseitig die Boxen abräumen“.
- DEVELOPMENT.md :1770–1774 (seit #133) „Die Lane kommt nur aus ungetracktem Zustand des eigenen Checkouts“. T1 dehnt
  das auf den Zustand selbst aus, auch mit gesetzter Lane.
- Unter docs/ gibt es keine Stelle zu lib.sh oder vm.py.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md, der Satz aus #133 (:1770–1774).
- Er sagt neu: Der Zustand im eigenen `.vm` wird nur ungetrackt gelesen, mit oder ohne `--lane`/`AH_LANE`.
- Ohne lesbares git braucht es ein `AH_VM_STATE_DIR`, das nicht das eigene `.vm` ist.
- Ein anderes Verzeichnis als das eigene `.vm` liest ohne diese Prüfung. Das ist die Wortwahl aus R-0329; „außerhalb
  des Checkouts“ war zu eng.

### T2 — warm und run nutzen nur Boxen der eigenen Lane (R-0324)  [ ]
Komponente: scripts · Dateien: scripts/vm/warm.sh, scripts/vm/vm.py, scripts/tests/vm_wrappers_test.sh, scripts/vm/tests/test_vm.py, DEVELOPMENT.md
Änderung:
- warm.sh `box_running` (:38–47) prüft nur `vmid` und `status` aus `vm.py list --json`.
  - Eine VMID, die inzwischen eine andere Lane trägt (`free_vmid` vergibt die kleinste freie wieder), gilt so als
    „reuse … box“.
  - Neu: Wiederverwendet wird nur, wenn die Zeile außerdem `lane == $LANE` trägt.
  - Sonst sagt warm.sh, dass der Slot eine Box einer anderen Lane nennt (VMID und deren Lane), und behandelt ihn wie
    eine verschwundene Box: Slot leeren, neu wärmen. So läuft heute schon der Weg für eine tote Box (:74, :99).
  - Seit T1 ist die warm.env die eigene. Das Leeren trifft also nur den eigenen Slot (Frage 1 am Gate).
- vm.py `run` (:1267) und `sync` (:1250) schreiben auf die Box: rsync `--delete` und Suiten.
  - Neu: Beide lehnen eine VM ab, deren `lane-`-Tag nicht `current_lane()` ist. Exit 2, geprüft am frischen Zustand
    wie `destroy`, vor `extend` und `sync`.
  - Für die Box einer anderen Lane von Hand gibt es `AH_LANE=<lane> vm.py run …`.
  - `ssh`, `pull`, `snap`/`rollback`/`delsnap` bleiben ohne Lane-Prüfung (Frage 2 am Gate).
- Tests:
  - vm_wrappers_test: `running_json` bekommt das Feld `lane`. Bestehende Reuse-Fälle laufen mit der eigenen Lane.
  - Neu: Ein Slot, den `list --json` mit einer anderen Lane meldet, wird nicht wiederverwendet. Die Fake sieht ein
    `clone`, die Meldung nennt VMID und Lane, kein Credential.
  - test_vm: `run` und `sync` auf eine VM einer anderen Lane ergeben `Usage` ohne ssh- oder rsync-Aufruf; auf eine
    der eigenen Lane laufen sie wie bisher.
  - Die bestehenden run-Tests bekommen ihre Lane fest (`AH_LANE` per monkeypatch im Fixture). Das ist Setup, keine
    Assertion-Änderung.
Rot vorher:
- origin/main@bf9d0a5c: warm.sh nutzt einen laufenden Slot einer anderen Lane wieder („reuse desktop box 3001“).
- vm.py `run 3001` läuft aus Lane `main` auf die Box der Lane `pilot`.
Beweis:
- origin/main@bf9d0a5c, warm.sh :38–47 vergleicht nur `vmid` und `status`.
- vm.py `Target` (:1180) und `verb_run`/`verb_sync` prüfen keine Lane.
- Fund: Review lane-reap-guard (Kandidat C), Worker A, 2026-10-12.
Dedup-Key: bug:scripts:warm.sh:box-running-lane
HEAD: bf9d0a5c
Semantik:
- AUTONOMOUS.md (Eigene Lane-Kennung je Worktree) „Lanes können sich nicht gegenseitig die Boxen abräumen“.
- `.claude/skills/vm/SKILL.md` :74–75 „Parallele Lanes teilen nichts“.
- Unter docs/ gibt es keine Stelle zu warm.sh oder `vm.py run`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku:
- DEVELOPMENT.md: In der vm.py-Tabelle, Zeilen `run` und `sync`, kommt ein Halbsatz dazu („nur auf VMs der eigenen
  Lane; eine andere mit `AH_LANE=<lane>`“).

### T3 — Nachträge aus lane-reap-guard: heavy.sh wiederholt keine Ablehnung, Fixtures ohne fremdes GIT_* (R-0329)  [ ]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, scripts/tests/lib_vm_test.sh
Änderung:
- heavy.sh `run_all` (:282–293) wiederholt jeden Fehler von `warm.sh desktop` einmal („the guest bootstrap is racy“)
  und meldet danach `infra`, „warm box could not be leased after a retry“.
  - Neu: Exit 2 von warm.sh ist eine Ablehnung, kein Wettlauf. Keine Wiederholung, eine eigene Meldung („warm.sh
    refused (exit 2), see warm.log“) und die letzte Zeile von warm.log.
  - Die Klasse bleibt `infra`/74: Der Lauf hat nichts verifiziert.
  - Ein heavy_test-Fall mit Fake-warm.sh, Exit 2: genau ein Aufruf, die eigene Meldung.
- lib_vm_test: Die Fixtures aus lane-reap-guard (`CO`, `CL`, `CU`, `CB`, ab :84) rufen `git init/add` unter
  geerbtem `GIT_DIR`/`GIT_WORK_TREE`/`GIT_INDEX_FILE`.
  - Neu: ein `unset` dieser drei vor dem Fixture-Block, wie `checkout_with_lane` in test_vm.
- Der dritte Punkt von R-0329, der Satz in DEVELOPMENT.md, geht in T1 auf, weil T1 denselben Satz neu schreibt.
Rot vorher: Auf origin/main@bf9d0a5c ruft heavy.sh bei Exit 2 von warm.sh warm.sh zweimal und meldet „after a retry“.
Beweis:
- origin/main@bf9d0a5c, heavy.sh :282–286 (`|| warm_rc=$?`, dann die Wiederholung bei jedem `warm_rc != 0`).
- Die Fixtures lib_vm_test :84–145 auf harness/lane-reap-guard@1c8b6ade.
- Fund: Kontrolle lane-reap-guard T6, Worker A, 2026-10-12 (Nits 2–4).
Dedup-Key: ref:scripts:lane-reap-guard:nits
HEAD: bf9d0a5c
Semantik:
- heavy.sh :275–277: Die Wiederholung gilt dem Wettlauf beim Bootstrap.
- CLAUDE.md §6 „SKIP ≠ grün“: Ein Lauf ohne Box bleibt unverifiziert. Eine Ablehnung ist kein Wettlauf.
- Unter docs/ gibt es keine Stelle zu heavy.sh.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
