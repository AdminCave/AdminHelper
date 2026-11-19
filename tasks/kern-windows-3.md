Status: bereit · Branch: feature/kern-windows-3 · Review: am Ende
Spec: docs/features/kern-windows-3.md (Roadmap R-1645)
Heavy: windows — Windows-Pfadcode, Beweis über die Windows-Jobs der PR-CI
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Overrides nur in Testläufen (R-1645)  [x]
Komponente: agent · Dateien: apps/agent/internal/config/paths_windows.go, apps/agent/internal/config/paths_windows_test.go, apps/agent/internal/service/service_windows.go, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/kern-windows-3.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @c18ca696d 2026-11-19T19:52:19+01:00
Review: am Ende (Branch-Review)
Änderung: `FrpDir`, `MonitorDir` und `LogDir` lesen `ADMINHELPER_*_DIR` nur, wenn die Paketvariable `overridesAllowed` (Vorgabe `testing.Testing`) wahr ist. Ein Windows-Test schaltet sie ab und zeigt, dass gesetzte Variablen die Pfade nicht mehr ändern. Der Hinweis in `service.Purge` entfällt, ebenso der Doku-Satz.
Beweis: security kern-windows-2 T1 2026-11-19 · feature/kern-windows-2@29d1b059d apps/agent/internal/config/paths_windows.go
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/config/... ./internal/service/...
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/kern-windows-3.md

## Entscheidungen
- Eine Task, `Review: am Ende`: Abschlussprüfung durch `reviewer` und `security` (SEC: security über den einzigen Task-Diff).
