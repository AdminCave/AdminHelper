<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-server-4 — Task-Ledger
Status: bereit · Branch: feature/klein-tests-server-4 · Review: am Ende
Spec: docs/features/klein-tests-server-4.md (Roadmap R-1293)
Heavy: none — nur pytest
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1293: Fehlermeldung von _with_dashboard nennt Requests und Listen  [x]
Komponente: server · Dateien: apps/server/tests/test_frps_supervisor.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @e97a297d5 2026-11-11T08:21:46+01:00
Review: am Ende (Branch-Review)
Beweis: reviewer ci-8 branch 2026-11-10 · PR #453 Lauf 42859714863 (a2fa262), Datei vom Branch nicht berührt · Dedup-Key: bug:server:test_frps_supervisor:dashboard-poll-timeout
Änderung: `_with_dashboard` fängt das Timeout des Wartens auf die vier Listen und wirft es mit den Requests, die das Dashboard sah (`dashboard.requests`, `dashboard.clients`), und den vorhandenen Listen (`_proxy_files`) neu. Gegenprobe: ein Dashboard, das nie antwortet (hang), liefert die Diagnose in der Meldung; grüner Pfad unverändert.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_supervisor.py
Doku: keine (Tests)

## Entscheidungen
- Ursache von R-1293 lokal nicht reproduzierbar (2026-11-11): ungestoert erste Listen nach 1,7 s (Budget 10 s), Test 4,2 s; 8 Laeufe unter 24 Rechenschleifen gruen (4,2-6,1 s), ganze Datei zweimal gruen unter Last mit --cov (161 passed). Dashboard._scan() 25 ms bei 400 Prozessen. Statt Timeout-Anhebung: Diagnose in der Fehlermeldung; Gegenprobe (Mutant ohne Requests in der Meldung) faellt rot. R-1293 bleibt als offene Ursache bestehen (neue Zeile nach dem Merge).
