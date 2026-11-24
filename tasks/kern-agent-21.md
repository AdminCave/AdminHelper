# kern-agent-21 — Task-Ledger
Status: geplant · Branch: feature/kern-agent-21 · Review: am Ende
Spec: docs/features/kern-agent-21.md (Roadmap R-0703)
Heavy: linux-full — apps/agent (Monitor-Collectoren); Windows-Dateien prüft der PR-Job agent-windows, FreeBSD nur quer gebaut
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Gilt für T1–T2: die Dateien unter `apps/agent/internal/monitor/testdata/report/` bleiben unverändert; jede Task baut
zusätzlich quer `GOOS=windows go vet ./...` und `GOOS=freebsd go vet ./...` in `apps/agent` und nennt das Ergebnis
im Commit-Body.

### T1 — R-0703: Seam-Typ `command`, Docker, Proxmox, ZFS und SMART  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/allowlist.go, apps/agent/internal/monitor/plugins.go, apps/agent/internal/monitor/smart.go, apps/agent/internal/monitor/plugins_test.go, apps/agent/internal/monitor/smart_test.go, apps/agent/internal/monitor/report_test.go, apps/agent/internal/monitor/report_golden_test.go
Änderung: Typ `command` (`lookPath`, `run func(ctx, timeout, env, name, args…)`, Standard `exec.LookPath` und `runTimedEnv`) in `allowlist.go`. `dockerCLI`, `zpoolCLI` und `smartctlCLI` werden `command`, `pveshCLI` bettet ihn ein; die Aufrufer geben Name und Timeout selbst an, `runDocker`, `runPvesh` und `runZpool` entfallen. Tests stubben die neue Form; keine Erwartung wird gelockert.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: keine (internes Refactoring)

### T2 — R-0703: System, Journal und FreeBSD-Pakete auf `command`  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/system_linux.go, apps/agent/internal/monitor/servicelogs_linux.go, apps/agent/internal/monitor/pkgaudit.go, apps/agent/internal/monitor/updates_linux.go, apps/agent/internal/monitor/system_linux_test.go, apps/agent/internal/monitor/servicelogs_linux_test.go, apps/agent/internal/monitor/pkgaudit_test.go, apps/agent/internal/monitor/system_freebsd_test.go
Änderung: `systemCLI` bettet `command` ein (dazu `now`), `journalCLI` und `freebsdCalls` werden `command`; die Aufrufer geben den Timeout (`pluginTimeout` bzw. den bisherigen) selbst an. Tests stubben die neue Form.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: keine (internes Refactoring)
Abhängt von: T1

## Entscheidungen
- 2026-11-24: Umfang Schritt 1 nur `monitor` (Kevin); Overrides, `slog.SetDefault`, `t.Parallel` und andere Pakete nicht (Spec, Nicht-Ziele).
