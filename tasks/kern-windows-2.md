# Agent Windows: Datenpfade aus der Known-Folder-API — Task-Ledger
Status: bereit · Branch: feature/kern-windows-2 · Review: pro Task
Spec: docs/features/kern-windows-2.md (Roadmap R-1605)
Heavy: windows — Windows-Pfadcode, Beweis über die Windows-Jobs der PR-CI
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Vorgabe-Pfade aus KnownFolderPath (R-1605)  [x]
Komponente: agent · Dateien: apps/agent/internal/config/paths_windows.go, apps/agent/internal/config/paths_windows_test.go, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/kern-windows-2.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @37c3f819d 2026-11-19T17:06:05+01:00
Review: approve (.ah-out/review/kern-windows-2/T1.verdict.json)
Änderung: `programData()` bestimmt den Ordner einmal über `windows.KnownFolderPath(FOLDERID_ProgramData)`, bei einem Fehler über die feste Vorgabe `C:\ProgramData`. `MonitorDir`, `FrpDir` und `LogDir` bauen darauf auf. Ein Windows-Test setzt `ProgramData` auf ein TempDir und zeigt, dass die Pfade davon unberührt bleiben. Die neue Testdatei bekommt einen SPDX-Header.
Beweis: security kern-windows-1 T4 2026-11-18 · feature/kern-windows-1@16eccd1c1 apps/agent/internal/config/paths_windows.go
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/config/...
Doku: docs/admin/agent-deployment.html docs/en/admin/agent-deployment.html changelog.d/kern-windows-2.md

### T2 — Overrides ADMINHELPER_*_DIR unter Windows  [~] (verschoben in kern-windows-3 (R-1645): wartet auf Kevins Antwort)
Komponente: agent · Dateien: apps/agent/internal/config/paths_windows.go
Änderung: nach Kevins Antwort (Frage unter Entscheidungen).
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/config/...
Doku: docs/admin/agent-deployment.html docs/en/admin/agent-deployment.html

## Entscheidungen
