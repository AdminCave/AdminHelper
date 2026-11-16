<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-6 — Task-Ledger
Status: geplant · Branch: feature/klein-tests-desktop-6 · Review: am Ende
Spec: docs/features/klein-tests-desktop-6.md (Roadmap R-1493, R-1135)
Heavy: none — Live-Skript braucht Docker und Desktop-Box; Verhalten bleibt bis zum nächsten Heavy-Lauf nicht verifiziert
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1493: wait_log und Web-Prüfung fassen docker logs erst in eine Variable  [ ]
Komponente: scripts · Dateien: scripts/tests/desktop_e2e_connect.sh
Beweis: reviewer klein-tests-desktop-5 2026-11-14 · scripts/tests/desktop_e2e_connect.sh:40 · Dedup-Key: bug:tests:desktop_e2e_connect.sh:wait-log-sigpipe
Semantik: docs/developer/cicd.html — keine Stelle zum Verhalten dieses Skripts gefunden; Gegenprobe der SIGPIPE-Semantik im Commit-Body
Änderung: In `wait_log` (Z. 40) und der Web-Prüfung (Z. 222) `docker logs … 2>&1` in eine Variable lesen und mit `grep -qE … <<<"$log"` prüfen, wie `wait_rdp_log`. Kein pipefail-Abschalten. Live-Verhalten nicht verifiziert.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Testskript)

### T2 — R-1135: strictSelectors einschalten, mehrdeutige Selektoren eingrenzen  [?] (Box-Lauf mit Kevin abstimmen: GUI-Lauf auf der Desktop-Box, warm.env desktop)
Komponente: desktop-ui · Dateien: apps/desktop/e2e/wdio.conf.js, apps/desktop/e2e/test/specs/*.e2e.js
Beweis: kern-deps-3 T3 2026-11-05: wdio 10 wirft bei mehreren Treffern von `$`; Config setzt strictSelectors: false · Dedup-Key: ref:tests:desktop-e2e:strict-selectors
Änderung: `strictSelectors` auf true, Specs per GUI-Lauf einzeln eingrenzen. Konkrete Dateiliste erst nach dem ersten Lauf.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: keine (Testkonfiguration)
