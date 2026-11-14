<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-11 — Task-Ledger
Status: erledigt · Branch: feature/klein-nachlese-11 · Review: pro Task
Spec: docs/features/klein-nachlese-11.md (Roadmap R-1460, R-1461, R-1466, R-1467, R-1468, R-1478, R-1483)
Heavy: linux-full — apps/agent (die Änderung steckt in Windows-Dateien; auf Linux belegt der Cross-Build sie nur)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Agent Windows: Zertifikatsspeicher, VARIANT-Freigabe, eigener WUA-Slot, Namenstest  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/certstore_windows.go, apps/agent/internal/probe/winviews_windows.go, apps/agent/internal/probe/winviews_test.go, apps/agent/internal/probe/certstore_windows_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @6580d200c 2026-11-15T00:10:01+01:00
Review: approve (.ah-out/review/klein-nachlese-11/T1.verdict.json)
Beweis: R-1460, R-1461 (reviewer kern-monitoring-14 T2), R-1466, R-1467, R-1468 (T3), R-1483 (branch) 2026-11-14
Änderung: `machineCerts` liest `NotBefore`/`NotAfter` aus `ctx.CertInfo` (FILETIME) und lässt kein Zertifikat mehr aus; `runtime.KeepAlive(name)` nach `CertOpenStore`. In `wuaRead` gibt jedes VARIANT aus `oleutil.GetProperty` (`Count`, `MsrcSeverity`, `RebootRequired`, `LastSearchSuccessDate`) `Clear()` frei. `winUpdates` bekommt einen eigenen Slot `wuaSlot` statt `wmiSlot`. `TestTheHostSensorTakesTheWindowsViews` prüft die Namen über `hostViews`/`appViews`, ohne einen Lesezugriff.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/...
Doku: keine (Agent-Interna ohne dokumentiertes Verhalten)

### T2 — Katalog windows-dns: Port 53 gehört dem Modul  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/windows_dns.py, apps/monitoring/tests/test_catalog_windows_server.py, changelog.d/klein-nachlese-11.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @5cd3a4949 2026-11-15T00:12:11+01:00
Review: approve (.ah-out/review/klein-nachlese-11/T2.verdict.json)
Beweis: R-1478 (reviewer kern-monitoring-14 T7) 2026-11-14
Änderung: `detect.port_hints: [53]` in `windows-dns`; Test: ein Inventar mit `DNS`-Dienst und Socket auf 53 ohne Unit ergibt die Modul-Instanz und keinen Port-Fund `tcp-53`. Changelog-Fragment (German `### Fixed`).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_windows_server.py
Doku: changelog.d/klein-nachlese-11.md
