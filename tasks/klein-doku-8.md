<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-doku-8 — Task-Ledger
Status: aktiv · Branch: feature/klein-doku-8 · Review: am Ende
Spec: docs/features/klein-doku-8.md (Roadmap R-1282)
Heavy: none — reine Doku
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1282: monitoring.html nennt den 422 bei wiederholtem Skalar-Query-Parameter  [ ]
Komponente: scripts · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html
Task-Review: am Ende
Beweis: review kern-server-8 2026-11-10 · apps/monitoring/app/core/query_params.py (R-1131) · Semantik: docs/en/developer/api-reference.html: "A query parameter the schema declares as a single value, given more than once (?offset=1&offset=2), is a 422 with loc [\"query\", <name>]"
Änderung: Nach dem Modulbaum ein Absatz DE+EN: ein Skalar-Query-Parameter, mehrfach angegeben, ergibt 422 (`loc ["query", <name>]`, Werte als Liste in `input`); App-weite Abhängigkeit `reject_repeated_scalar_query` in `core/query_params.py`; unbekannte Parameter werden ignoriert.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Änderung selbst
