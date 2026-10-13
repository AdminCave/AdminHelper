<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Multibox: das Urteil nennt das Go, mit dem die Server-Box das Agent-Paket gebaut hat — Task-Ledger
Status: bereit · Branch: harness/multibox-go-version · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket, Triage Kevin 2026-10-13; Fragen 1-4 wie empfohlen; Frage 5: Heavy none, die Box-Zeile verifiziert der naechste Multibox- bzw. Wochenlauf; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0359 (Kurz-Ledger ohne Spec)
Heavy: none — wie am Gate entschieden: Die Zeile von der Server-Box (`box_serverbox.sh`) zeigt erst der nächste echte Multibox- oder Wochenlauf; der Fake-vm.py des hermetischen Tests führt das Skript nicht aus.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker B im Auftrag der Aufsicht (adminhelper-ac). Kevin hat die Zeile am 2026-10-13 angenommen.
Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht. Zeilenangaben
origin/main@bef5d17e. `scripts/tests/multibox.sh` ist ein Harness-Pfad; den PR merged Kevin oder die Aufsicht auf sein
Wort. Adressen in Tests und Proben sind Platzhalter.

**Befund.**
- Die Server-Box baut das Agent-Binary einmal (`box_serverbox.sh:160` → `vm_build_agent_deb`, `scripts/vm/lib.sh:134-143`:
  `make build-linux`, dann `build-deb.sh`). `build-rpm.sh` packt dasselbe Binary (`:190`), und beide Pakete gehen ins
  signierte Repo.
- Welches Go das war, steht nirgends im Lauf:
  - `bootstrap_linux.sh:169` druckt nur den Pin (`Go ${GO_VERSION}`), am Anfang der Ausgabe.
  - `multibox.sh:168` zeigt von der Server-Box nur `tail -40`.
  - Die Summary (`:374`) nennt Zähler, Server und Agents.
- Marker liest `multibox.sh` mit `mb`/`vm_marker` (`:171-187`, `lib.sh:122`). Ein Wert endet am ersten Leerzeichen.

### T1 — Das Multibox-Urteil nennt die Go-Version des Agent-Binarys, das die Server-Box gebaut hat (R-0359)  [x]
Komponente: scripts · Dateien: scripts/tests/box_serverbox.sh, scripts/tests/multibox.sh, scripts/tests/multibox_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @1d869138 2026-10-13T21:02:18+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung:
- `box_serverbox.sh`: Im Zweig nach einem erfolgreichen `vm_build_agent_deb` (`:160-161`) druckt das Skript eine Zeile
  `MB_AGENT_GO=<version>`.
  - Die Version kommt aus dem gebauten Binary: `go version apps/agent/bin/adminhelper-agent`, das zweite Feld, etwa
    `go1.26.9`. Sie gilt damit auch, wenn ein anderes `go` im PATH gestanden hätte. Die Build-Info überlebt `-s -w`
    (lokal geprüft).
  - Ein Fehler von `go version` ergibt einen leeren Wert und lässt den Lauf nicht scheitern.
- `multibox.sh`: liest den Wert nach den übrigen Markern (`:187`) als `AGENT_GO="$(mb MB_AGENT_GO)"`.
  - Nach der Summary (`:374`) folgt eine Zeile `  go version (agent .deb, server box): <version>`, ohne Wert
    `unknown (no MB_AGENT_GO marker)`.
  - Zähler und Exit bleiben, wie sie sind.
  - Die Zeile enthält kein `multibox:`. Was `heavy.sh` als Summary liest, ändert sich also nicht.
- `multibox_test.sh`: Der Fake druckt im Zweig `*box_serverbox.sh*` (`:55-59`) zusätzlich
  `MB_AGENT_GO=${FAKE_AGENT_GO-go1.26.9}`, als neue Zeile. Neue Fälle am Dateiende:
  - `--agents 1` → rc 0, die Zeile `  go version (agent .deb, server box): go1.26.9`;
  - `FAKE_AGENT_GO=''` → rc 0, die Zeile mit `unknown`, kein Fall mehr rot.
- `DEVELOPMENT.md:1856-1859` (Punkt „Verteilt (Multi-Host)“): ein Satz, dass das Urteil die Go-Version des
  Agent-Binarys der Server-Box nennt.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Punkt „Verteilt (Multi-Host)“)
Beweis:
- R-0359: Der Lauf `multibox --agents 1` @531a19da (go-toolchain-126) hatte im Log keine Go-Version, sie musste aus dem
  Bootstrap-Pin abgeleitet werden.
- origin/main@bef5d17e: `git grep -n 'go version' -- scripts/tests/multibox.sh scripts/tests/box_serverbox.sh` → kein
  Treffer.
- Gegenprobe in einer Kopie: nur der Test geändert → `multibox_test` 20 passed, 2 failed; mit der Änderung → 22 passed.
Orakel: mutation-sample — die Zeile in `multibox.sh` entfernt: der Fall „Zeile mit go1.26.9“ rot.
Dedup-Key: ref:scripts:multibox.sh:box-go-version
HEAD: bef5d17e
Semantik: `.claude/skills/test/SKILL.md:270-271`: „report the `run.sh` / multibox summary line verbatim“. Dazu
`DEVELOPMENT.md:1887-1890`: Der Report ist „nie eine Bewertung, nur Fakten“. Womit das ausgelieferte Paket gebaut wurde,
ist eine solche Tatsache.
