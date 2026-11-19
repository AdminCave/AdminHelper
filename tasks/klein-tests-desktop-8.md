<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-8 — Task-Ledger
Status: bereit · Branch: feature/klein-tests-desktop-8 · Review: am Ende
Spec: docs/features/klein-tests-desktop-8.md (Roadmap R-1522)
Heavy: none — Live-Skripte brauchen Docker und Desktop-Box; Verhalten bleibt bis zum nächsten Heavy-Lauf nicht verifiziert
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1522: Log-Wartepunkte lesen docker logs erst in eine Variable  [x]
Komponente: scripts · Dateien: scripts/tests/desktop_e2e_connect_tunnel.sh, scripts/tests/desktop_e2e_workspaces.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @79bd39ed4 2026-11-19T17:06:38+01:00
Review: am Ende (Branch-Review)
Beweis: reviewer klein-tests-desktop-6 2026-11-16 · scripts/tests/desktop_e2e_connect_tunnel.sh:40 · Dedup-Key: bug:tests:desktop_e2e_connect_tunnel.sh:wait-log-sigpipe
Semantik: docs/developer/cicd.html — keine Stelle zum Verhalten dieser Skripte; Gegenprobe der SIGPIPE-Semantik im Commit-Body
Änderung: `wait_log` (beide Dateien), `wait_rdp_log`, die frps-Schleifen und die sshd-/nginx-Prüfung in connect_tunnel lesen die Log-Quelle in eine Variable und prüfen mit `grep … <<<"$log"`, wie in `desktop_e2e_connect.sh` (R-1493). Kein pipefail-Abschalten. Live-Verhalten nicht verifiziert.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Testskripte)
