<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket reap-followups: Nachzügler aus reap-role — ein Test mehr, ein treuer Fake, AUTONOMOUS.md (R-0349) — Task-Ledger
Status: geplant · Branch: harness/reap-followups · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Spec: Roadmap R-0349 (Kurz-Ledger ohne Spec)
Heavy: none — vm.py mit test_vm.py (aufgezeichnete API), der Fake in vm_wrappers_test, ein Satz in AUTONOMOUS.md; keine echte VM, kein echtes destroy.
DoD je Task: CLAUDE.md (Tests grün, shellcheck/ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-14 von Worker A für den Chef (adminhelper-ac). Kevin hat die Zeile am 2026-10-13 angenommen.
Zeilenangaben origin/main@092c55d9; beim Bau an Symbolen orientieren.

Vorab geprüft:
- `verb_destroy` (vm.py) prüft `require_no_scenario(current)` (:1556) in der Bestätigungsschleife, vor der Schleife mit
  `purge_vm` (:1561). Die drei Tests zu `--no-scenario` (test_vm.py :2962–2990) nennen je eine VM.
  - Wandert die Prüfung in die purge-Schleife (Mutation), bleiben sie grün, obwohl bei zwei genannten VMs die erste
    schon zerstört wäre (Review reap-role).
- Der Fake in vm_wrappers_test (:65–73) lehnt mit `FAKE_ROLE_OF` einen Aufruf ab, wenn dessen `--role` nicht passt, auch
  wenn gar kein `--role` dabei ist. vm.py nimmt eine genannte VM ohne `--role` an.
- AUTONOMOUS.md :172–173: „`reap.sh` nennt die VMIDs aus der warm.env mit `--lane` der eigenen Lane, und `vm.py` lehnt
  eine VMID einer anderen Lane ab.“ Seit reap-role (#151) nennt reap.sh je Slot auch `--role` und `--no-scenario`,
  seit warm-slot-identity (#156) dazu `--expect-name`, wo warm.sh den Namen gemerkt hat (DEVELOPMENT.md :1850–1854 sagt
  das schon).

### T1 — Ein Test hält fest, dass --no-scenario den ganzen Aufruf vor der ersten Zerstörung ablehnt  [ ]
Komponente: scripts · Dateien: scripts/vm/tests/test_vm.py
Änderung:
- Neue Testfunktion am Dateiende:
  - `destroy 3000 3001 --no-scenario`;
  - 3000 frisch ohne `sc-` (über `purgeable(now=…)`), 3001 mit `sc-capstone` (Fixture);
  - erwartet: `vm.Usage` mit `3001 carries sc-capstone`, und `http.paths("DELETE") == []`.
- Code ändert sich nicht.
Rot vorher: Mit der Mutation „`require_no_scenario` in die purge-Schleife“ bleibt die Suite heute grün; mit dem neuen
Test wird sie rot (Probe im Wegwerf-Worktree).
Beweis: origin/main@092c55d9, test_vm.py :2962–2990 nennen je eine VM; vm.py :1556/:1561. Fund: Review reap-role
(Worker A), 2026-10-13.
Dedup-Key: ref:scripts:vm.py:no-scenario-followups
HEAD: 092c55d9
Semantik: vm.py `verb_destroy`, Kommentar: „Everything is checked BEFORE the first destruction“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T2 — Der Fake in vm_wrappers_test lehnt nur ab, was vm.py ablehnt  [ ]
Komponente: scripts · Dateien: scripts/tests/vm_wrappers_test.sh
Änderung:
- `FAKE_ROLE_OF` lehnt einen Aufruf nur ab, wenn er ein `--role` trägt und das nicht passt. Ohne `--role` nimmt der
  Fake die VM an, wie vm.py.
- Neuer Fall direkt gegen den Fake: `FAKE_ROLE_OF=3001=server`.
  - `destroy --lane main 3001` → Exit 0, `destroyed`;
  - `destroy --lane main --role desktop 3001` → Exit 2, `is not --role desktop`.
- Der bestehende reap.sh-Fall mit `FAKE_ROLE_OF` bleibt unverändert grün.
Rot vorher: Auf main endet `destroy --lane main 3001` am Fake mit Exit 2.
Beweis: origin/main@092c55d9, vm_wrappers_test :70 `[ "$role" != "${FAKE_ROLE_OF#*=}" ]` ohne Prüfung auf ein leeres
`role`. Fund: Review reap-role (Worker A), 2026-10-13.
Dedup-Key: ref:scripts:vm.py:no-scenario-followups
HEAD: 092c55d9
Semantik: vm.py `require_selected`: geprüft wird nur gegen die Selektoren, die der Aufruf trägt.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T3 — AUTONOMOUS.md nennt alle Filter, mit denen reap.sh einen Slot nennt  [ ]
Komponente: scripts · Dateien: AUTONOMOUS.md
Änderung:
- :172–173 wird: „`reap.sh` nennt die VMIDs aus der warm.env mit `--lane` der eigenen Lane, ihrer Rolle (`--role`),
  `--no-scenario` und, wo `warm.sh` ihn gemerkt hat, ihrem Namen (`--expect-name`), und `vm.py` lehnt eine VMID ab, die
  eine andere Lane oder Rolle, ein Szenario oder einen anderen Namen trägt.“
- Sonst ändert sich nichts.
Rot vorher: Auf main nennt die Stelle nur `--lane`.
Beweis: origin/main@092c55d9, AUTONOMOUS.md :172–173; reap.sh ruft `destroy --lane "$LANE" --role … --no-scenario …`
und, wo gemerkt, `--expect-name`.
Dedup-Key: ref:scripts:vm.py:no-scenario-followups
HEAD: 092c55d9
Semantik: DEVELOPMENT.md :1850–1854 (dieselbe Aussage, vollständig).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: AUTONOMOUS.md (die Stelle selbst; die Datei gibt es nur auf Deutsch)
