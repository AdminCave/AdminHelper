<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-server-7 — Task-Ledger
Status: aktiv · Branch: feature/klein-tests-server-7 · Review: am Ende
Spec: docs/features/klein-tests-server-7.md (Roadmap R-1307, R-1356, R-1357)
Heavy: none — nur Test-Fristen und ein Test-Filter
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1307, R-1356: Dashboard-Poll-Waits und der Übernahme-Wait warten bis 30 s  [x]
Komponente: server · Dateien: apps/server/tests/test_frps_supervisor.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @fec4de255 2026-11-12T10:23:30+01:00
Review: am Ende (Branch-Review)
Beweis: R-1307 klein-tests-server-4 2026-11-11 (Timeout 10 s, Ursache offen) · R-1356 Prüfer-Nit klein-tests-server-6 2026-11-12 · Dedup-Key: BUG:server:test_frps_supervisor.py:dashboard-poll-wait
Änderung: `wait_until` in `_with_dashboard` (Z. 1554, „the proxy lists“) und die Poll-Waits Z. 1602, 1643, 1829 bekommen `3 * WAIT`; `box.wait_state("running")` in Z. 1181 ebenso. Dauerlauf (50×) der betroffenen Tests im Commit-Body.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_supervisor.py -k dashboard
Doku: keine (Test-Fristen)

### T2 — R-1357: der Passwort-Test erkennt den Plugin-Check am Pfad, nicht am Port  [ ]
Komponente: server · Dateien: apps/server/tests/test_frps_supervisor.py
Beweis: CI run 43169329319 job 131018537950 (PR #481) 2026-11-12 · Dedup-Key: BUG:server:test_frps_supervisor.py:without_plugin_checks
Änderung: `_without_plugin_checks` (Z. 1620) filtert Zeilen der Form `… --output /dev/null http://127.0.0.1:<Port>/healthz` mit beliebigem Port; Kommentar nennt den Grund (`plugin_port` hebt den Port, wenn das Dashboard `policy_port` trägt). Neuer Test: ein Protokoll mit Plugin-Check auf `policy_port + 1` bleibt draußen, eine Dashboard-Zeile bleibt drin. Dauerlauf (50×) des Passwort-Tests im Commit-Body.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_supervisor.py -k "password_of_the_dashboard or plugin_checks"
Doku: keine (Test)
