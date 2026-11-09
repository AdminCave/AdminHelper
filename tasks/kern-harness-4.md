# Harness: eigene known_hosts-Datei für den Connect-Lauf — Task-Ledger
Status: bereit · Branch: feature/kern-harness-4 · Review: am Ende
Spec: docs/features/kern-harness-4.md (Roadmap R-1157)
Heavy: linux-full — Desktop-GUI-Journey (desktop_e2e_connect); vor dem Merge zusätzlich der Box-Lauf `iter.sh all --strict --step desktop_e2e_connect` (Bedingung der Roadmap-Zeile)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1157: Connect-Lauf mit eigener known_hosts-Datei  [x]
Komponente: scripts · Dateien: scripts/tests/desktop_e2e_connect.sh, scripts/tests/desktop_e2e_skip_test.sh, apps/desktop/e2e/test/specs/ssh-connect.live.js
Evidenz: run.sh[quick] scripts desktop-e2e: 7 passed, 0 failed, 11 skipped @8160e27a6 2026-11-09T20:19:42+01:00
Review: am Ende (Branch-Review)
Änderung: Ein `ssh`-Shim in `SHIM_DIR` ruft das vorher aufgelöste echte ssh mit `-o UserKnownHostsFile=$E2E_WORK/known_hosts` vor allen Argumenten; `forget_e2e_host_key` und sein Eintrag im EXIT-Trap entfallen, der Kommentar dazu und der im Spec beschreiben die Datei des Laufs. Beweis auf der Box: der Schritt `desktop_e2e_connect` grün, das known_hosts des Box-Nutzers trägt danach keinen Eintrag für `[127.0.0.1]:2222`.
Beweis: security-Review arch-ssh-terminal 2026-11-05 (Nit) · feature/arch-ssh-terminal@636e0e84 scripts/tests/desktop_e2e_connect.sh:72
Dedup-Key: ref:scripts:desktop_e2e_connect.sh:forget_e2e_host_key
HEAD: 81e2b2e46
Verify: bash scripts/dev/verify.sh scripts desktop-e2e --strict
Doku: keine (die Doku beschreibt den known_hosts-Umgang des Connect-Laufs nicht)

## Entscheidungen
