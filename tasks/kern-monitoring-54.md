# Compose-Kennung nur aus eindeutigen Teilen — Task-Ledger
Status: bereit · Branch: feature/kern-monitoring-54 · Review: am Ende
Spec: docs/features/kern-monitoring-54.md (Roadmap R-1663)
Heavy: none — reine Bewertungslogik des Monitoring-Dienstes, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1663: _compose_ident lehnt Teile mit Schrägstrich ab  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/plugins.py, apps/monitoring/tests/test_plugin_checkers.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @973493dcf 2026-11-20T10:03:05+01:00
Review: am Ende (Branch-Review)
Änderung: `_compose_ident` (plugins.py:539) gibt None zurück, wenn Projekt oder Dienst ein `/` enthält; der Parametrisierungs-Test `test_docker_without_the_whole_compose_identity_the_key_stays_the_name` (test_plugin_checkers.py:1099) bekommt diese Fälle, erst rot.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_plugin_checkers.py
Doku: keine (unzulässige Agent-Daten, kein dokumentiertes Verhalten)
