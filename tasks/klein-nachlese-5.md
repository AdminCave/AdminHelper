<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-5 — Task-Ledger
Status: aktiv · Branch: feature/klein-nachlese-5 · Review: am Ende
Spec: docs/features/klein-nachlese-5.md (Roadmap R-1429)
Heavy: none — nur Agent-Unit-Tests und ein Docstring
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1429: LDAP-Fallname, openProcRoot direkt testen  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/app_ldap_test.go, apps/agent/internal/probe/app_wordpress_test.go
Beweis: reviewer arch-monitoring-app-collector T3/T4 2026-11-13 · Dedup-Key: REF:agent:app_ldap_test.go:nachlese-arch-monitoring-app-collector
Änderung: der Fall „a notice of disconnection“ (Zeile 540) heißt „a closed connection“; neuer Test ruft `openProcRoot(os.Getpid())` auf: unter Linux öffnet er, sonst `ErrUnsupported` (kein Skip).
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: keine (Tests)

### T2 — R-1429: Docstring-Zeile in sensors.py umbrechen  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py
Beweis: reviewer arch-monitoring-app-collector T5 2026-11-13
Änderung: die 169 Zeichen lange Zeile 13 im Modul-Docstring wird auf die Breite der übrigen umbrochen; Text unverändert.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog.py
Doku: keine (Docstring)
