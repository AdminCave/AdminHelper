<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: rebaseline mit unlesbaren Details — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-25 · Review: am Ende
Spec: docs/features/kern-monitoring-25.md (Roadmap R-1401)
Heavy: none — nur Monitoring-Dienst (interne Route und Modell), kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1401: rebaseline und Zustandsantwort vertragen unlesbare Details  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/app/models.py, apps/monitoring/tests/test_central_rebaseline.py
Änderung: rebaseline fängt `json.loads(state.details)` wie `check.config` ab (`JSONDecodeError`, `TypeError` → keine
Basislinie, gespeicherter Text bleibt); `MonitorState.to_dict` meldet unlesbare Details als `None`. Test zuerst rot:
Zustand mit Details `"{not json"` → 200, `state.details` in der Antwort `null`, gespeicherter Text unverändert.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_rebaseline.py
Doku: keine (gültige Zeilen verhalten sich unverändert, Spec Doku-Impact)

## Entscheidungen
