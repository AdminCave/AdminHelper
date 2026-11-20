# Agent: gescheiterte Abfrage der fehlgeschlagenen Units melden — Task-Ledger
Status: erledigt · Branch: feature/kern-agent-14 · Review: am Ende
Spec: docs/features/kern-agent-14.md (Roadmap R-1644)
Heavy: linux-full — Änderung in apps/agent (Sammellauf)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1644: gescheitertes list-units --state=failed als error melden  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/services_linux.go, apps/agent/internal/monitor/services_linux_test.go, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-agent-14.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @462a974a2 2026-11-20T08:45:17+01:00
Review: am Ende (Branch-Review)
Änderung: Scheitert `list-units --state=failed` bei gelungenem `list-units --all`, setzt `collectServiceHealth` `health["error"]` mit `commandFailure`. `counts` und die Fakten bleiben. Ein Tabellentest (Exit, Timeout, Start) schlägt zuerst fehl. Die Doku-Sätze nennen die Abfrage mit.
Beweis: arch-monitoring-neu-p1 T8 2026-11-19 · apps/agent/internal/monitor/services_linux.go:49 · Dedup-Key: BUG:agent:services_linux.go:failed-units-error
Semantik: docs/admin/monitoring.html — „Kann der Agent die Dienste nicht abfragen (<code>systemctl list-units</code> scheitert), ist der Check <code>unknown</code> mit dem Grund statt <code>ok</code>.“
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestServiceHealth
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-agent-14.md

## Entscheidungen
