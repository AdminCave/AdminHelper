<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-3 — Task-Ledger
Status: bereit · Branch: feature/klein-tests-desktop-3 · Review: am Ende
Spec: docs/features/klein-tests-desktop-3.md (Roadmap R-1197)
Heavy: none — Live-Skript braucht Docker und Desktop-Box; Verhalten bleibt bis zum nächsten Heavy-Lauf nicht verifiziert
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1197: RDP-Wächter fasst das xrdp-Log erst in eine Variable  [x]
Komponente: scripts · Dateien: scripts/tests/desktop_e2e_connect.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @3c38dac03 2026-11-11T06:18:03+01:00
Review: am Ende (Branch-Review)
Beweis: review kern-rdp-1 branch 2026-11-08 · Dedup-Key: bug:tests:desktop_e2e_connect.sh:session-watch · HEAD: feature/kern-rdp-1@8299f55ea
Änderung: Im Wächter (`AH_RDP_MARKS/session`) das Log mit `docker exec "$GFX_C" cat /var/log/xrdp.log 2>/dev/null` in eine Variable lesen und mit `grep -Eq … <<<"$log"` prüfen, wie bei `gfx_log`. Kein pipefail-Abschalten. Live-Verhalten nicht verifiziert (Docker, Desktop-Box).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Testskript)
