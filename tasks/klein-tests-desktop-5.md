<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-5 — Task-Ledger
Status: aktiv · Branch: feature/klein-tests-desktop-5 · Review: am Ende
Spec: docs/features/klein-tests-desktop-5.md (Roadmap R-1298)
Heavy: none — Live-Skript braucht Docker und Desktop-Box; Verhalten bleibt bis zum nächsten Heavy-Lauf nicht verifiziert
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1298: wait_rdp_log fasst die Logs erst in eine Variable  [ ]
Komponente: scripts · Dateien: scripts/tests/desktop_e2e_connect.sh
Beweis: klein-Session 2026-11-11 beim Planen von klein-tests-desktop-3 · scripts/tests/desktop_e2e_connect.sh:49 · Dedup-Key: bug:tests:desktop_e2e_connect.sh:wait-rdp-log-sigpipe
Semantik: docs/developer/cicd.html — keine Stelle zum Verhalten dieses Skripts gefunden; Gegenprobe der SIGPIPE-Semantik im Commit-Body
Änderung: In `wait_rdp_log` die Ausgabe von `docker exec … cat …` und `docker logs` je in eine Variable lesen und mit `grep -qiE … <<<"$log"` prüfen, wie der Marken-Wächter im selben Skript. Kein pipefail-Abschalten. Live-Verhalten nicht verifiziert (Docker, Desktop-Box).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Testskript)
