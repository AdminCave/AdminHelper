<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Capstone Visitor: frpc detached starten — Task-Ledger (Kurz)
Status: erledigt (1/1) · Branch: fix/visitor-frpc-detach · Commit-Granularität: pro Task · Review: am Ende (feature-review) · Modell: Fable (interaktiv, 2026-09-18)
Spec: scripts/tests/box_visitorbox.sh, scripts/vm/vm.py `run` (kein pty) — Kurz-Ledger, keine eigene Spec
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: der naechste `heavy.sh capstone` ist der Beweis (Visitor-Stufe endet in Sekunden statt am 3000-s-Timeout)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: R-0050 (BUG, Fund des ersten Capstones auf vm.py) · Hängt ab von: PR #22
Befund 2026-09-18 12:37–13:27: `vm.py run 3005 -- box_visitorbox.sh` haengt nach dem Skriptende; auf der Box laeuft nur noch `sudo sh -c '/usr/bin/frpc …' &` (Elternprozesse sudo/sh halten stdout/stderr der ssh-Sitzung), das Skript selbst ist beendet; frps sah die Visitor-Verbindung um 12:39:09. Unter crabbox endete dieselbe Stufe (mit pty). Der Tunnel-Agent hat dasselbe Problem nicht: sein frpc laeuft unter systemd.

### T1 — frpc-Visitor mit setsid starten und am Ende stoppen; Guard fuer alle Box-Skripte  [x] (box_visitorbox.sh; box_scripts_guard_test.sh in AH_SCRIPT_TESTS_DEFAULT; /vm-Skill-Regel; CHANGELOG)
Komponente: scripts · Dateien: scripts/tests/box_visitorbox.sh, scripts/tests/box_scripts_guard_test.sh (neu, SPDX), scripts/tests/run.sh, .claude/skills/vm/SKILL.md, CHANGELOG.md
Änderung: `sudo setsid /usr/bin/frpc … </dev/null >/tmp/frpc-vis.log 2>&1 &`, `pkill` vor `VIS_DONE`; hermetischer Guard: jede `… &`-Zeile in `box_*.sh` muss `setsid`/`nohup` mit `</dev/null` tragen (Nicht-Leer: Anzahl Box-Skripte).
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: .claude/skills/vm/SKILL.md · CHANGELOG
