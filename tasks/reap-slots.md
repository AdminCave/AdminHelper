<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket reap-slots: reap.sh zerstört die Warm-Slots einzeln (R-0320, R-0323) — Task-Ledger
Status: erledigt · Branch: harness/reap-slots · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket aus R-0320, R-0323, Triage Kevin 2026-10-12; R-0320 jetzt mit Probe belegt; vm.py bleibt streng; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0320, R-0323 (Kurz-Ledger ohne Spec)
Heavy: none — reap.sh mit Fake-vm.py in vm_wrappers_test, vm.py destroy mit der Fake-API von test_vm; kein echtes destroy, kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck/ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker A für die Aufsicht (adminhelper-ac). Kevin hat die Zeilen am 2026-10-12 angenommen.
Zeilenangaben origin/main@710b68a2; beim Bau an Symbolen orientieren.

Vorab geprüft:
- `vm.py` ist ein Harness- und Lab-Pfad: nur Fakes, nie ein echtes `destroy`.
- R-0320 trug „Beweis fehlt“. Der Beweis ist nachgereicht: eine Probe gegen die Fake-API von test_vm auf
  origin/main@710b68a2, als Datei, die nicht committet wurde.
  - `verb("destroy", cfg, api, "3001", "3005")`, wobei 3005 nicht in `/cluster/resources` steht, endet mit
    `Usage: no VM '3005' in pool adminhelper-ci`.
  - `http.paths("DELETE") == []`: 3001 wird nicht zerstört.
- `vm.py destroy` bleibt bei einer VMID, die nicht im Pool steht, mit Absicht streng. Es kann eine verschwundene VM
  nicht von einer VM eines anderen Pools unterscheiden, und eine solche darf es nie anfassen (`require_ours`, `find_vm`
  „resolved inside our pool — and nowhere else“). Der Fix gehört deshalb in reap.sh.

### T1 — reap.sh zerstört die Warm-Slots einzeln (R-0320, R-0323)  [x]
Komponente: scripts · Dateien: scripts/vm/reap.sh, scripts/tests/vm_wrappers_test.sh, scripts/vm/tests/test_vm.py
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @5a4e4d0b 2026-10-13T02:29:31+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- reap.sh (:40–49) übergibt alle Warm-Slots in einem `vm_py destroy --lane "$LANE" <ids…>`.
  - vm.py prüft vor der ersten Zerstörung alles und bricht den ganzen Aufruf ab, wenn ein Slot nicht durchgeht. Das
    passiert in zwei Fällen:
    - Die VM des Slots steht nicht mehr in der Liste (R-0320, etwa nach abgelaufener ttl).
    - Die VMID gehört inzwischen einer anderen Lane (R-0323, `free_vmid` vergibt die kleinste freie wieder).
  - Dann bleibt auch der eigene, lebende Slot stehen, die warm.env ist danach leer, und `list` meldet einen Leak
    (74).
- Neu: reap.sh ruft `destroy --lane "$LANE" <id>` je Slot.
  - Ein Slot, den vm.py ablehnt, kostet nur sich selbst. Die Meldung von vm.py erscheint eingerückt wie bisher.
  - Der Kommentar (:45–46, „vm.py says so and moves on“) wird richtig: Er sagt, dass ein verschwundener oder fremder
    Slot nur seinen eigenen Aufruf scheitern lässt.
- Tests:
  - vm_wrappers_test:
    - Der Fall `reap.sh` erwartet zwei Aufrufe (`destroy --lane main 3001` und `destroy --lane main 3002`) statt
      eines (:201–202). Das ist eine Shell-Prüfung, für diff-scan keine Assertion.
    - Neu: Die Fake-vm.py lehnt 3001 mit Exit 2 ab (`FAKE_DESTROY_FAIL=3001`). 3002 wird trotzdem zerstört, und die
      warm.env ist danach leer wie bisher.
  - test_vm: `destroy` mit einer VMID, die nicht im Pool steht, neben einer, die dort steht, ergibt `Usage` mit der
    VMID und zerstört nichts. Der Test hält den Vertrag fest, auf dem reap.sh jetzt aufbaut.
Rot vorher: Auf main ruft reap.sh `destroy --lane main 3001 3002` in einem Aufruf. Lehnt vm.py 3001 ab, wird 3002 nicht
zerstört.
Beweis:
- origin/main@710b68a2, reap.sh :48 `vm_py destroy --lane "$LANE" "${IDS[@]}"`.
- Die Probe oben.
- Funde: Planung und Review lane-reap-guard, Worker A, 2026-10-12.
Dedup-Key: bug:scripts:reap.sh:slot-by-slot
HEAD: 710b68a2
Semantik: reap.sh :45–46 („A slot whose VM is already gone is the normal case after a ttl expired … the sweep must not
stop at it“). Unter docs/ gibt es keine Stelle zu reap.sh.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; DEVELOPMENT.md und AUTONOMOUS.md sagen nur, dass reap.sh die Slots mit `--lane` nennt, das bleibt)

### T2 — Nachbesserung aus dem Review am Ende: nur Slots aus Ziffern, der Exit-Code des Ablehnungsfalls  [x]
Komponente: scripts · Dateien: scripts/vm/reap.sh, scripts/tests/vm_wrappers_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @8760914f 2026-10-13T03:13:35+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Angelegt 2026-10-13 aus dem Review am Ende (Opus, `approve`, zwei nits).
- reap.sh gibt jeden Slot-Wert als Argument an `vm.py destroy`. Ein Wert, der mit `-` beginnt, würde argparse als
  Option lesen. `desktop=--role=desktop` hieße dann `destroy --lane main --role=desktop` und träfe per Filter jede
  Desktop-VM der Lane.
  - Neu: reap.sh nimmt nur Slot-Werte aus Ziffern. Einen anderen meldet es mit der Rolle, ohne den Wert, und
    überspringt ihn.
  - Der Vorschlag `destroy -- <id>` aus dem Review geht nicht: `vm.main` schneidet `--` vor argparse ab, und ein Verb
    ohne Kommando endet dann mit Exit 2 (test_vm `test_a_verb_without_a_command_refuses_one`).
- vm_wrappers_test:
  - Der Ablehnungsfall aus T1 prüft auch, dass reap.sh mit 0 endet; über rot oder grün entscheidet das abschließende
    `list`.
  - Ein Fall `desktop=--role=desktop`: kein `destroy` mit diesem Wert, die Meldung nennt die Rolle, Exit 0.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
Abhängt von: T1
