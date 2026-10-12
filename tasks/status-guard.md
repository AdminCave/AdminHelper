<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket status-guard: AH-STATUS zeigt nur Rollen und VM-IDs, Nachträge aus lane-state-guard (R-0331) — Task-Ledger
Status: bereit · Branch: harness/status-guard · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket, Triage und Reihenfolge Kevin 2026-10-12: sofort; lane.sh lane_vm_untracked ohne eigenen Fall wie empfohlen; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0331 (Kurz-Ledger ohne Spec)
Heavy: none — session-status.sh, heavy.sh, lib.sh, vm.py und lane.sh mit hermetischen Tests: session_status_test mit Fixture-Repo, heavy_test mit Shims, lib_vm_test und test_vm mit tmp-Repos und Fake-API; nur Platzhalter, keine VM, kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck/ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker A für die Aufsicht (adminhelper-ac). Kevin hat die Zeilen am 2026-10-12 angenommen.
Zeilenangaben origin/main@b127f4de (lane-state-guard ist mit #136 gemergt); beim Bau an Symbolen orientieren.

Vorab geprüft:
- Tests nur mit Platzhaltern. Keine echte `.vm/warm.env` lesen oder ausgeben, kein `env` ausgeben (die Session-Umgebung
  trägt `AH_PVE_*`).
- Vor jedem Shell-Aufruf von reap/warm/iter: `unset "${!AH_PVE_@}"`, `AH_VM_PY` auf einen Rekorder setzen,
  `AH_PVE_URL` auf einen Platzhalter.
- Die getrackte Sperre steht an drei Stellen, alle mit `git … ls-files -- .vm`:
  - lib.sh `vm_lane` (:84);
  - vm.py `require_untracked_state` (:564);
  - lane.sh `lane_vm_untracked` (:144).

### T1 — AH-STATUS zeigt aus der warm.env nur Rollen und VM-IDs  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/session-status.sh, scripts/tests/session_status_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @8aaae593 2026-10-13T01:03:39+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- session-status.sh, Zeile 5 des Blocks (:238–241), druckt heute jede Zeile der warm.env, die wie `KEY=` beginnt.
  - Neu: Nur die Rollen-Slots kommen in den Block, Schlüssel ohne `_` mit einer VM-ID aus Ziffern, wie `warm_vmids`
    in vm.py sie liest (`LC_ALL=C grep -E '^[a-z]+=[0-9]+$'`). Jede andere Zeile bleibt draußen.
  - Trackt der Checkout Pfade unter `.vm`, liest der Hook die warm.env gar nicht. Ein git, das nicht antwortet, zählt
    wie ein Treffer. Die Zeile sagt dann „warm.env nicht gelesen (Zustand unter .vm ist getrackt)“, wie die Sperre
    aus lane-state-guard.
  - git läuft dabei ohne geerbtes `GIT_DIR`/`GIT_WORK_TREE`/`GIT_INDEX_FILE` (wie T3).
- Fälle in session_status_test, nur Platzhalter:
  - Die Fixture-warm.env bekommt `desktop=3001`, `server=3002`, `server_ip=…` und drei weitere `server_*`-Schlüssel
    mit dem Platzhalter `plchold`.
  - Erwartet wird `VMs: warm.env desktop=3001 server=3002`; `plchold` steht nirgends im Block.
  - Der bestehende Fall `desktop=warmbox-7` (:135, :180) wird dafür zu einer VM-ID aus Ziffern. Das ist eine
    Shell-Prüfung, für diff-scan keine Assertion.
  - Ein Fixture, das `.vm/warm.env` trackt: Die Zeile sagt „nicht gelesen“, kein Slot und kein Platzhalter erscheint.
Rot vorher: Auf main steht jeder `server_*`-Wert der Fixture im Block.
Beweis:
- origin/main@b127f4de, session-status.sh :239 `grep -E '^[A-Za-z0-9_-]+=' .vm/warm.env | paste -sd' ' -`.
- Fund: Review lane-state-guard, Worker A, 2026-10-12.
HEAD: b127f4de
Semantik:
- CLAUDE.md §3: Der Block `AH-STATUS` zeigt Checkout, Roadmap, Ledger, PRs, VMs.
- vm.py `warm_vmids`: „Only the bare role slots hold a VMID“.
- Unter docs/ gibt es keine Stelle zu session-status.sh.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T2 — heavy.sh bucht eine Ablehnung von iter.sh als infra, die Tests hängen nicht an AH_LANE (R-0331)  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, scripts/tests/iter_flags_test.sh, scripts/vm/tests/test_vm.py
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b95e18df 2026-10-13T01:17:20+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- heavy.sh `run_all` (:421–425): Endet `iter.sh all` mit einem Exit ≠ 0 ohne roten Schritt, wird das FAIL („wrapper
  exit $rc without a red step“).
  - Exit 2 ist eine Ablehnung, kein Testergebnis: `vm.py run` lehnt seit lane-state-guard die Box einer anderen Lane
    ab, oder es ist ein Usage-Fehler.
  - Neu: Exit 2 ohne roten Schritt wird infra (UNVERIFIED) mit eigener Meldung („iter.sh all refused (exit 2)“).
  - Ein roter Schritt bleibt FAIL, wie bisher.
  - Ein Exit 2 der Remote-Suite lässt sich davon nicht unterscheiden. Auch er ist kein Testergebnis.
  - Ein heavy_test-Fall mit Shim: `SHIM_ITER_RC=2` und grüne Schritte ergeben infra/74 und die Meldung. Mit einem
    roten Schritt bleibt es FAIL.
- iter_flags_test: `AH_LANE` kommt in die `unset`-Zeile (:18), wie in vm_wrappers_test. Mit einem exportierten
  `AH_LANE=pilot` war der Test seit lane-state-guard 21/8.
- test_vm `test_a_vm_that_is_not_ours_keeps_its_lease` (:1810): Die Lane wird fest gesetzt (`monkeypatch.setenv`),
  denn `run` prüft vor `extend` die Lane. Das ist Setup, keine Assertion-Änderung.
Rot vorher:
- Auf main bucht heavy.sh `SHIM_ITER_RC=2` mit grünen Schritten als FAIL.
- `AH_LANE=pilot bash scripts/tests/iter_flags_test.sh` ist rot.
Beweis:
- origin/main@b127f4de, heavy.sh :424 `set_fail; FINDINGS+=(… "wrapper exit $rc without a red step")`.
- iter_flags_test :18 ohne `AH_LANE`.
- Fund: Review lane-state-guard (Kandidat A, Nit 1).
Dedup-Key: ref:scripts:lane-state-guard:followups
HEAD: b127f4de
Semantik:
- heavy.sh :334–336: Was nichts über den Code sagt, ist infra, nie eine Regression.
- CLAUDE.md §6 „SKIP ≠ grün“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T3 — Die Sperre fragt git ohne geerbtes GIT_DIR (R-0331)  [x]
Komponente: scripts · Dateien: scripts/vm/lib.sh, scripts/vm/vm.py, scripts/dev/lane.sh, scripts/tests/lib_vm_test.sh, scripts/vm/tests/test_vm.py
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ea8e8ac6 2026-10-13T01:30:14+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- Die drei Stellen der Sperre (lib.sh :84, vm.py :564, lane.sh :144) fragen `git ls-files -- .vm` unter der geerbten
  Umgebung.
  - Ein exportiertes `GIT_DIR`, `GIT_WORK_TREE` oder `GIT_INDEX_FILE` ließe git einen anderen Index lesen, und
    getrackte Pfade gingen als ungetrackt durch.
  - Ein Aufrufer in Produktion, der das exportiert, ist nicht bekannt. Das ist eine Härtung.
- Neu: lib.sh und lane.sh rufen `env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE git …`. vm.py gibt `subprocess.run`
  eine Umgebung ohne diese drei mit.
- Tests:
  - lib_vm_test: ein Checkout, der `.vm/lane` trackt, mit exportiertem fremdem `GIT_DIR` und `GIT_INDEX_FILE` (ein
    leerer tmp-Index). `vm_lane` lehnt trotzdem ab.
  - test_vm: dasselbe für `current_lane` per `monkeypatch.setenv`.
  - lane.sh deckt der Code-Pfad aus lane-reap-guard T2 ab. Ein lane_test-Fall ist nicht vorgesehen: Die Stelle läuft
    in einer Lane, die `lane.sh` selbst angelegt hat (Frage am Gate).
Rot vorher: Auf main nimmt `vm_lane` mit einem leeren fremden Index einen getrackten Checkout als ungetrackt.
Beweis:
- origin/main@b127f4de, lib.sh :84, vm.py :564, lane.sh :144.
- Fund: Review lane-state-guard (Kandidat C).
Dedup-Key: ref:scripts:lane-state-guard:followups
HEAD: b127f4de
Semantik: DEVELOPMENT.md, Lane-Absatz (seit #136): „Den Zustand im eigenen `.vm` … lesen `vm.py` und `lib.sh` … nur
ungetrackt“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
