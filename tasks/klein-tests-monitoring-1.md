<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-monitoring-1 — Task-Ledger
Status: aktiv · Branch: feature/klein-tests-monitoring-1 · Review: am Ende
Spec: docs/features/klein-tests-monitoring-1.md (Roadmap R-0844)
Heavy: none — Unit-Test im Monitoring-Dienst, kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Monitoring: Vergleichstest der Proxy-Wahl gegen httpx (R-0844)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_ssrf_proxy_route.py
Änderung: Neue Testdatei mit dem Vergleichstest aus der Server-Suite: ein einfacher `httpx.Client` ist das Orakel, `pinned_client` muss dort zum Proxy gehen, wo httpx es tut, und sonst zur geprüften Adresse. Gegenprobe: `get_environment_proxies()` durch `{}` ersetzt färbt ihn rot.
Beweis: R-0844 Code-Lesung apps/monitoring/app/core/ssrf.py:29,295
Dedup-Key: ref:monitoring:ssrf.py:httpx-private-proxies
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_ssrf_proxy_route.py
Doku: keine (Test)

## Entscheidungen
