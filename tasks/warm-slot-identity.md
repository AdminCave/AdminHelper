<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Warm-Slots: eine Box gilt nur als eigene, wenn Rolle, Szenario und Name stimmen — Task-Ledger
Status: bereit · Branch: harness/warm-slot-identity · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket, Triage Kevin 2026-10-13; Fragen 1-5 wie empfohlen: Altbestand einmal uebernehmen, alle drei Tasks, iter endet mit dem Exit von vm.py, kein eigenes --name, warm prueft ueber list und iter/reap lassen vm.py frisch pruefen; Review am Ende Opus; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0347 (Kurz-Ledger ohne Spec)
Heavy: none — vm.py mit test_vm.py (aufgezeichnete API), warm.sh, iter.sh und reap.sh mit dem Fake-vm.py der Script-Tests; keine echte VM, kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck/ruff sauber, Doku im selben Commit).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker B im Auftrag der Aufsicht (adminhelper-ac). Kevin hat die Zeile am 2026-10-13 als eigenes
Kurz-Ledger angenommen. Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht.
Zeilenangaben origin/main@c37d4198. `scripts/vm/*` und `.claude/` sind Harness-Pfade: Gebaut wird in einer Session
Kevins oder eines Workers, nicht im autonomen Loop; den PR merged Kevin oder die Aufsicht auf sein Wort.

**Befund.** Ein Warm-Slot in `.vm/warm.env` ist eine VMID (`desktop=<vmid>`, `server=<vmid>`; `lib.sh:97-114`).
- `warm.sh` nimmt ihn wieder, wenn `vm.py list` die VMID als `running` auf der eigenen Lane zeigt. So prüft es `box_lane`
  (`warm.sh:35-53`) in `warm_role` (`:72-84`) und `warm_server` (`:103-114`).
- Rolle, Szenario und Name prüft es nicht.
- `free_vmid` (`vm.py:627-638`) gibt eine freigewordene VMID dem nächsten Klon. Auf der VMID eines abgelaufenen Slots
  kann deshalb eine andere VM derselben Lane laufen, etwa der Server eines Multibox-Szenarios (`multibox.sh:60`, `:115`)
  oder die Warm-Box eines anderen Checkouts.
- `iter.sh` geht vor jedem Lauf durch `warm.sh` und fährt `vm.py run <vmid> --sync … --extend` auf dem Slot
  (`iter.sh:88-93`). `reap.sh` nennt den Slot an `vm.py destroy` (`reap.sh:58-61`).
- `vm.py list` liest Namen aus einem Cache, der bei einer wiederverwendeten VMID den Namen des Vorgängers zeigen kann. Die
  Tags sind dabei schon aktuell (`scripts/vm/tests/README.md:72-78`: „Namen lügen, Tags nicht“). Frisch ist nur
  `status/current` (`fresh_entry`, `vm.py:684-712`).
- `clone` druckt `VMID NAME` (`vm.py:983`), der Name ist `ah-<rolle>-<lane>-<pid16>` (`:961`). `clone_box` (`warm.sh:64`)
  behält davon nur die VMID.

Der Zuschnitt folgt daraus:
- T1 gibt `vm.py` eine Prüfung des Namens gegen den frischen Stand.
- T2 lässt `warm.sh` den Namen merken und einen Slot nur mit eigener Lane, seiner Rolle, ohne Szenario und mit diesem
  Namen nehmen (aus `list`).
- T3 lässt `iter.sh` und `reap.sh` den Namen an `vm.py` geben. Wo der Cache noch einen alten Namen zeigt, lehnt dann
  `vm.py` den Aufruf ab, statt auf die fremde Box zu schreiben oder sie zu zerstören.

### T1 — vm.py: `--expect-name` für run, sync und destroy, geprüft gegen `status/current` (R-0347)  [x]
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/tests/test_vm.py, .claude/skills/vm/SKILL.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @f6800f30 2026-10-13T13:45:13+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung:
- `run`, `sync` und `destroy` (Parser `vm.py:1941-1978`) nehmen ein optionales `--expect-name <name>`.
- Ist es gesetzt, gilt die VM nur, wenn `status/current` genau diesen Namen trägt.
  - Bei `run` und `sync` gehört die Prüfung in `require_own_lane` (`:1262-1269`). Die VMID kommt dort schon frisch, und sie
    läuft vor `--sync` und `--extend`.
  - Bei `destroy` gehört sie in die Prüfung je Ziel (`verb_destroy`, `:1531-1538`), neben die von Lane, Rolle und
    Szenario.
  - Meldung und Exit sind die einer abgelehnten Auswahl (`require_selected`). Die Meldung nennt die VMID, den erwarteten
    und den frischen Namen.
- Ohne `--expect-name` bleibt alles, wie es ist.
- `test_vm.py`, mit den aufgezeichneten Antworten (`status_current_running.json` trägt `name`):
  - Ein passender Name lässt `run`, `sync` und `destroy` durch.
  - Ein anderer frischer Name lehnt sie ab, ohne rsync, ohne Kommando, ohne `extend` und ohne purge.
  - Ein Cache mit dem erwarteten Namen und `status/current` mit einem anderen wird abgelehnt.
- `.claude/skills/vm/SKILL.md`: eine Zeile zu `--expect-name` neben den Verben.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: .claude/skills/vm/SKILL.md (Verben)
Beweis: origin/main@c37d4198: `git grep -n expect-name -- scripts/vm` → kein Treffer. `require_own_lane` prüft frisch nur
die Lane (`:1262-1269`), `verb_destroy` Lane, Rolle und Szenario (`:1531-1538`), keiner den Namen.
Orakel: mutation-sample — die Namensprüfung in `require_own_lane` entfernt: der Fall „anderer frischer Name bei run“ rot.
Dedup-Key: bug:scripts:warm.sh:warm-slot-identity
HEAD: c37d4198
Semantik: `scripts/vm/tests/README.md:77-78`: „Frischen Zustand einer einzelnen VM liefert `status/current`
(`status_current_*.json`), nicht die Ressourcenliste.“ Dazu `vm.py:689`: „Deciding to destroy something from a
cache is how the wrong VM dies“.

### T2 — warm.sh: der Slot merkt den Namen und gilt nur mit eigener Lane, Rolle, ohne Szenario und mit diesem Namen (R-0347)  [x]
Komponente: scripts · Dateien: scripts/vm/warm.sh, scripts/tests/vm_wrappers_test.sh, scripts/tests/iter_flags_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @15e7ddf5 2026-10-13T14:00:11+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Abhängt von: T1
Änderung:
- `clone_box` (`warm.sh:62-70`) gibt den Namen aus `clone` mit weiter, ohne den Exit von `clone` zu verlieren.
- `warm_role` und `warm_server` schreiben ihn als `<rolle>_name` (`desktop_name`, `server_name`) neben die VMID (`:96`,
  `:127-128`). Der Schlüssel trägt einen Unterstrich. So überspringen ihn alle, die nur VMIDs lesen: `vm.py warm_vmids`
  (`:1627-1631`), `session-status.sh:270`, `lane.sh:497`. `warm_clear` eines Slots leert auch `<rolle>_name`.
- `box_lane` wird zu einer Prüfung des Slots. Wiederverwendet wird nur, wenn `list --json` die VMID zeigt mit:
  - `running`;
  - der eigenen Lane;
  - der Rolle des Slots;
  - leerem `scenario`;
  - dem gemerkten Namen.
  Sonst wird wie heute neu gewärmt, mit einer Meldung, die den Grund nennt (Rolle, Szenario, Name), und Exit 0.
- Ein Slot ohne `<rolle>_name` (Altbestand) wird einmal übernommen, wenn Lane, Rolle und „kein Szenario“ stimmen. Den
  Namen schreibt `warm.sh` dann aus `list` fest, mit eigener Meldung.
- `vm_wrappers_test.sh`: Der Fake druckt bei `clone` einen Namen nach Wahl (heute fest, `:55`).
  - Neue Fälle, je mit einem Slot `desktop=3001` und `desktop_name=…`:
    - auf 3001 läuft ein Server mit Szenario → neu gewärmt, kein `run 3001`;
    - auf 3001 läuft eine Desktop-Box mit anderem Namen → neu gewärmt;
    - auf 3001 läuft die eigene Box → Reuse ohne `clone`;
    - der Server-Slot mit einem Szenario-Server → kein „reuse server box“;
    - Altbestand ohne Namen → übernommen, Name festgeschrieben.
  - Die bestehenden Vorgaben (`running_json` `:88`, `RUNNING` `:297`) bekommen Rolle und Namen. Die `--extend`-Fälle
    (`:296-314`) prüfen dann wirklich Reuse.
- `iter_flags_test.sh`: Die `warm.env`- und `list`-Vorgaben (`:163-177`, `:208`) bekommen Rolle und Namen. Die erwarteten
  Aufrufe bleiben.
- `DEVELOPMENT.md:1815-1816`: Der Satz zu `warm.sh` nennt, dass der Slot auch den Namen merkt und nur mit eigener Lane,
  Rolle, ohne Szenario und mit diesem Namen wieder gilt.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Absatz zu warm.sh)
Beweis: origin/main@c37d4198, hermetisch mit Fake-vm.py (nicht committet; `AH_VM_PY` auf die Attrappe, keine VM):
- Slot `desktop=3001`, `list` zeigt auf 3001 `role server`, `scenario mb-4242`, Lane `main`: `iter.sh lint` → „reuse
  desktop box 3001 (already warm)“ und `run 3001 --sync … --extend 8h`, rc 0.
- Slot `desktop=3001`, auf 3001 eine Desktop-Box mit anderem Namen: `iter.sh --cmd` → „reuse desktop box 3001“,
  `run 3001 --sync …`.
- Slot `server=3002` mit `server_ip`, auf 3002 ein Szenario-Server: `warm.sh server` → „reuse server box 3002“.
Orakel: mutation-sample — die Rollen- und Szenario-Prüfung entfernt: der Fall „Server mit Szenario auf dem Desktop-Slot“
rot. Der Namensvergleich entfernt: der Fall „anderer Name“ rot.
Dedup-Key: bug:scripts:warm.sh:warm-slot-identity
HEAD: c37d4198
Semantik: `warm.sh:36-38`: „A slot is reused only on this lane: the pool hands a freed VMID out again, and a slot whose
box expired may name the box another lane is working on by now.“ Dasselbe gilt in der eigenen Lane für eine Box, die ein
anderes Szenario oder ein anderer Checkout auf die VMID gelegt hat. `.claude/skills/test/SKILL.md:141`: „Warm once
(idempotent — reuses `.vm/warm.env` if the VM is still running)“ meint die eigene VM.

### T3 — iter.sh und reap.sh geben den gemerkten Namen an vm.py (R-0347)  [x]
Komponente: scripts · Dateien: scripts/vm/iter.sh, scripts/vm/reap.sh, scripts/tests/vm_wrappers_test.sh, scripts/tests/iter_flags_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @584aa7f4 2026-10-13T15:04:50+02:00
Review: Review am Ende (Kurz-Ledger, Opus): approve, Nits miterledigt
Abhängt von: T1, T2
Änderung:
- `iter.sh` `box_run` (`:88-93`): Trägt der Slot `desktop_name`, ruft es `vm.py run <vmid> --expect-name <name> …`.
  Lehnt `vm.py` ab, etwa weil der Cache bei `warm.sh` noch den alten Namen zeigte, endet `iter.sh` mit dessen Exit und
  einer Zeile, die `warm.sh` als nächsten Schritt nennt. Es synct nicht.
- `reap.sh` (`:43-61`): Trägt der Slot `<rolle>_name`, kommt `--expect-name <name>` zum `destroy` des Slots.
  - Ein Name, der mit `-` beginnt oder andere Zeichen als `[a-z0-9-]` trägt, gilt als kein Name: Der Slot wird
    übersprungen, wie heute ein Slot ohne VMID (`:48-50`).
  - Ohne Namen bleibt es beim heutigen Aufruf.
- `vm_wrappers_test.sh`:
  - reap mit `desktop_name` → `destroy --lane main --role desktop --no-scenario --expect-name <name> 3001`;
  - reap mit einem Namen, der mit `-` beginnt → übersprungen;
  - iter mit `desktop_name` → `run 3001 --expect-name <name> --sync …`;
  - ein Fake-`run`, der mit Exit 2 ablehnt → iter endet mit 2, ohne weitere Läufe.
- `iter_flags_test.sh`: Die erwarteten `run`-Aufrufe bekommen `--expect-name`, wo die Vorgabe einen Namen trägt.
- `DEVELOPMENT.md:1832-1836`: Der Satz zu `reap.sh` nennt `--expect-name`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Absatz zu reap.sh)
Beweis: origin/main@c37d4198, dieselbe Probe: Slot `desktop=3001`, auf 3001 eine Desktop-Box mit anderem Namen derselben
Lane ohne Szenario: `reap.sh` ruft `destroy --lane main --role desktop --no-scenario 3001`. Diesen Aufruf nähme
`vm.py` heute an, denn seine Prüfung kennt nur Lane, Rolle und Szenario (`:1531-1538`; gelesen, nicht gegen eine VM
gelaufen).
Orakel: mutation-sample — `--expect-name` aus dem `destroy` von `reap.sh` entfernt: der Fall „reap mit desktop_name“ rot;
aus `box_run` entfernt: der Fall „iter mit desktop_name“ rot.
Dedup-Key: bug:scripts:warm.sh:warm-slot-identity
HEAD: c37d4198
Semantik: `DEVELOPMENT.md:1833-1836`: „`reap.sh` nennt die Warm-Slots mit `--lane` der eigenen Lane, ihrer Rolle
(`--role`) und `--no-scenario`, und `vm.py` lehnt einen Slot ab, dessen VM eine andere Lane oder Rolle oder ein Szenario
traegt: `free_vmid` gibt eine freigewordene VMID dem naechsten Klon“. Die Box eines anderen Checkouts derselben Lane und
Rolle gehört ebenso wenig zum Slot.
