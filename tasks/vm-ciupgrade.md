<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Klone ohne Paket-Upgrade beim ersten Boot — Task-Ledger
Status: aktiv · Branch: feature/vm-ciupgrade · Review: am Ende
Spec: Roadmap R-0416
Heavy: none — Test-Harness (`scripts/vm/vm.py`); belegt durch einen Multibox-Lauf nach dem Merge (R-0398 `--agents 1 --tunnel --enforce`)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-16: R-0416 jetzt fixen (Multibox scheitert auf main viermal reproduziert). Harness-PR, den Kevin merged.

### T1 — `create_vm`: Leases ohne `ciupgrade`, der Bake mit Upgrade und wartet auf cloud-init  [ ]
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/tests/test_vm.py, DEVELOPMENT.md
Änderung: Proxmox schreibt in die cloud-init-Daten jedes Klons `package_upgrade: true`, weil `ciupgrade` weder am Template noch am Klon gesetzt ist (PVE-Default 1). Beim ersten Boot läuft dann `apt-get dist-upgrade`; ein neueres openssh-server-Paket stoppt dabei `ssh.socket` für etwa 50 s, 40–55 s nachdem `vm.py wait` SSH schon gesehen hat, und der erste `rsync` in `multibox.sh` scheitert mit 255. Neu: `create_vm` (`vm.py:1018`, `config`-Dict `:1076`) setzt für Leases (`clone`) `"ciupgrade": 0`; der Bake (`verb_bake` `:1818`, Aufruf `:1852`) behält das Upgrade (Parameter, nur der Bake setzt 1), damit Templates aktuell gebacken werden, und wartet vor `_sync` (`:1877`) per ssh auf `cloud-init status --wait` (Exit 0 oder 2 gelten als fertig, 2 = „degraded“; 1 ist ein Fehler). Tests in `test_vm.py` neben dem Clone-Config-Test (`:851`): ein Lease setzt `ciupgrade` auf `"0"`; der Bake setzt `"1"` und ruft vor dem Sync das Warten auf cloud-init auf, Exit 2 gilt als fertig, Exit 1 bricht ab. `DEVELOPMENT.md:1088` (`wait`) und die Beschreibung von `clone`/`bake` nennen: Leases laufen mit dem Paketstand des Templates, der Bake bringt ihn auf den neuesten Stand.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (`vm.py`-Tabelle)
Beweis: main@48ec5718 · `bash scripts/tests/multibox.sh --agents 1` (Haupt-Checkout) viermal identisch rot: `== bring up the server stack ==` → `rsync: connection unexpectedly closed (0 bytes received so far) [sender]` / `vm.py: sync failed: rsync exited 255` / `FAIL server bring-up / token seed`; Diagnose auf einer frischen Server-Box: ssh 0,4 s nach `wait` offen, ab +40 s `Connection refused`, ab +93 s wieder offen; Journal `Preparing to unpack …openssh-server…13.20` → `Stopped ssh.service`/`Closed ssh.socket` → 51 s später `Listening on ssh.socket`; `cloudinit/dump type=user` des Klons endet mit `package_upgrade: true`; Gegenprobe mit `ciupgrade=0` im Config-PUT: kein apt-Lauf, ssh 200 s stabil, `multibox: 9 ok, 0 failed, 1 skipped`
Orakel: crash — der Szenario-Lauf bricht im ersten Sync ab
Dedup-Key: bug:scripts:multibox.sh:ssh-socket-flap
HEAD: 48ec5718
Semantik: DEVELOPMENT.md:1088 — „`wait <vm> [--timeout 900]` | Wartet auf Guest-Agent, IPv4 und ssh — alle drei an **einer** Frist. Druckt die Adresse.“ (nach `wait` soll die Box per ssh erreichbar sein)
