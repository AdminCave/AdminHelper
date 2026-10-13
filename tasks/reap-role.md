<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket reap-role: reap.sh nennt jeden Slot mit Rolle und ohne Szenario, list-Exit 74 im Test (R-0336) — Task-Ledger
Status: bereit · Branch: harness/reap-role · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket, Triage Kevin 2026-10-13; T1 bleibt drin; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0336 (Kurz-Ledger ohne Spec)
Heavy: none — vm.py mit test_vm.py (aufgezeichnete API, keine echte VM), reap.sh mit vm_wrappers_test (Fake-vm.py); kein Stack-, Gateway-, PKI- oder Install-Pfad, kein echtes destroy.
DoD je Task: CLAUDE.md (Tests grün, shellcheck/ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker A für den Chef (adminhelper-ac). Kevin hat die Zeile am 2026-10-13 angenommen.
Zeilenangaben origin/main@5b50dc86; beim Bau an Symbolen orientieren.

Vorab geprüft:
- reap.sh zerstört jeden Warm-Slot mit `vm_py destroy --lane "$LANE" "$v"` (:58), ohne Rolle. vm.py hält eine genannte
  VM gegen jeden mitgegebenen Selektor (`require_selected` :1484–1498), `--role` gibt es bei `destroy` schon (:1957).
- `free_vmid` (:627–638) vergibt die kleinste freie VMID im Klon-Band. Hat der Reaper einen Warm-Slot nach seiner ttl
  genommen, bekommt der nächste Klon dieselbe VMID.
- Die Zeile ließ offen, ob Szenario-VMs andere Rollen-Tags tragen. Geprüft: nein, nicht immer.
  - multibox.sh klont mit `--role "$role" --scenario "$SCENARIO"` (:115), die Rollen sind `server`, `agent`,
    `moncheck`, `rpm`, `tunnel`, `visitor` und `desktop` (`planned_roles` :84–92).
  - Der Server wird zuerst geleast (:135). Er bekommt also die freigewordene VMID eines Server-Slots und trägt
    `role-server`, `lane-main` und `sc-mb-<pid>`.
  - `--role` je Slot fängt damit eine andere Rolle (etwa einen Agenten auf der VMID des Desktop-Slots), aber nicht das
    Beispiel der Zeile.
- Ein Warm-Klon trägt nie einen Szenario-Tag: warm.sh klont ohne `--scenario` (:64), und vm.py setzt `sc-` nur aus
  `--scenario` (:929, :969).
- lane.sh `done` baut auf den Exit von reap.sh (:427–429). reap.sh gibt den Exit von `vm_py list` weiter (:74–78, unter
  `pipefail`). Der Fake in vm_wrappers_test beendet `list` immer mit 0 (:61–62), kein Fall hält den Exit fest.

### T1 — vm.py destroy --no-scenario: eine genannte VM mit Szenario-Tag wird abgelehnt  [x]
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/tests/test_vm.py, .claude/skills/vm/SKILL.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @6bca397d 2026-10-13T10:15:13+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `destroy` bekommt `--no-scenario` (Parser :1953–1957).
  - Mit genannten VMs: Trägt eine von ihnen einen `sc-`-Tag, lehnt `verb_destroy` den ganzen Aufruf ab, bevor es die
    erste zerstört, wie `require_selected` heute für Lane und Rolle. Geprüft am frischen Zustand.
  - Die Meldung nennt den Tag: `<vmid> carries sc-<name>, not a warm box — refusing`.
  - Ohne genannte VMs ist `--no-scenario` ein Usage-Fehler: allein würde es sonst jede VM ohne Szenario auswählen.
  - Zusammen mit `--scenario` ebenso ein Usage-Fehler.
- Fälle in test_vm.py, als neue Testfunktionen am Dateiende:
  - eine VM mit Szenario-Tag, sonst passend (Fixture 3001: `lane-pilot`, `role-server`, `sc-capstone`) mit
    `--lane pilot --role server --no-scenario` → Usage, die Meldung nennt `sc-capstone`, kein DELETE;
  - eine VM ohne `sc-` (Fixture 3000 über `purgeable(now=…)` ohne Szenario-Tag, wie :2155) mit
    `--lane main --role probe --no-scenario` → zerstört;
  - `--no-scenario` ohne VM und `--no-scenario --scenario x` → Usage.
- vm-Skill :38: `--no-scenario` in der Zeile der destroy-Optionen.
Rot vorher: Auf main nimmt `destroy --lane main --role server <vmid>` eine VM, die `sc-mb-1` trägt; `--no-scenario`
ist ein unbekanntes Argument (Exit 2).
Beweis: origin/main@5b50dc86, vm.py :1502–1537 `verb_destroy`, :1484 `require_selected` prüft nur die Selektoren
`--lane/--scenario/--role`.
Dedup-Key: ref:scripts:reap.sh:role-per-slot
HEAD: 5b50dc86
Semantik: DEVELOPMENT.md :1832–1834 „Steht neben ihr ein Filter, muss sie zu ihm passen: `reap.sh` nennt die
Warm-Slots mit `--lane` der eigenen Lane, und `vm.py` lehnt einen Slot ab, dessen VM eine andere Lane traegt.“
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: .claude/skills/vm/SKILL.md (Optionsliste)

### T2 — reap.sh nennt jeden Slot mit seiner Rolle und ohne Szenario  [x]
Komponente: scripts · Dateien: scripts/vm/reap.sh, scripts/tests/vm_wrappers_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @3bd8c975 2026-10-13T10:28:45+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- reap.sh merkt sich je Slot Rolle und VMID (:41–50) und ruft je Slot
  `vm_py destroy --lane "$LANE" --role "$role" --no-scenario "$v"` (:58).
  - Eine VM, die die VMID eines Slots inzwischen trägt, aber eine andere Rolle oder ein Szenario hat, kostet nur ihren
    eigenen Aufruf; der Rest des Sweeps läuft wie heute.
- vm_wrappers_test:
  - Die bestehenden Prüfungen der destroy-Zeilen (:206, :219, :229, :251) erwarten die neue Form, etwa
    `destroy --lane main --role desktop --no-scenario 3001`.
  - :229 prüfte, dass `--role` gar nicht im Log steht; es prüft jetzt, dass `--role=desktop` nicht darin steht. Das sind
    Shell-Prüfungen, für diff-scan keine Assertion.
  - Neu: Der Fake lehnt einen Aufruf mit `--role desktop` für eine als Server markierte VMID ab, wie vm.py; der
    Server-Slot geht trotzdem, Exit 0.
- DEVELOPMENT.md :1833: `reap.sh` nennt die Warm-Slots mit Lane, Rolle und `--no-scenario`.
Rot vorher: Auf main ruft reap.sh `destroy --lane main 3001`, ohne Rolle und ohne `--no-scenario`.
Beweis: origin/main@5b50dc86, reap.sh :58.
Dedup-Key: ref:scripts:reap.sh:role-per-slot
HEAD: 5b50dc86
Semantik: wie T1; reap.sh :17–20 „Only this lane's warm slots are destroyed outright“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md :1833
Abhängt von: T1

### T3 — Der Exit 74 von list wird der Exit von reap.sh, im Test festgehalten  [x]
Komponente: scripts · Dateien: scripts/tests/vm_wrappers_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @e22b1485 2026-10-13T10:41:49+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- Der Fake beendet `list` mit `FAKE_LIST_RC` (Default 0) (:61–62).
- Neuer Fall: `FAKE_LIST_RC=74` → reap.sh endet mit 74. Vorher liefen `destroy` je Slot, `reap` und das Leeren von
  warm.env wie gewohnt; `list` bleibt der letzte Aufruf.
- Der bestehende Fall mit Exit 0 (:203) bleibt.
Rot vorher: Auf main bleibt die Suite grün, wenn reap.sh :78 den Exit von `list` verschluckt (Mutation `|| true`).
Beweis: origin/main@5b50dc86, vm_wrappers_test :61–62 (`list` endet immer mit 0), lane.sh :427–429 (`done` hängt am
Exit von reap.sh).
Dedup-Key: ref:scripts:reap.sh:role-per-slot
HEAD: 5b50dc86
Semantik: reap.sh :74–76 „`list` exits 74 when it finds a VM of this lane that nothing claims any more, and that exit
code is this script's“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
