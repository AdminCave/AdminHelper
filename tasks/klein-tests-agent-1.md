<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-agent-1 — Task-Ledger
Status: bereit · Branch: feature/klein-tests-agent-1 · Review: pro Task
Spec: docs/features/klein-tests-agent-1.md (Roadmap R-0851, R-0883)
Heavy: none — Unit-Tests im Agent, kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — docs_cli_test: Aufrufe über Pfad und .exe lesen (R-0851)  [x]
Komponente: agent · Dateien: apps/agent/cmd/adminhelper-agent/docs_cli_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @9b78a99a 2026-10-29T21:54:10+01:00
Review: approve (.ah-out/review/klein-tests-agent-1/T1.verdict.json)
Änderung: `docCalls` führt vor dem Abgleich einen Aufruf über einen Pfad (`./`, `.\`, `/usr/bin/`) oder die Windows-Binary (`adminhelper-agent-windows-x86_64.exe`, `adminhelper-agent.exe`) auf den Namen `adminhelper-agent` zurück, wenn ein Unterbefehl oder ein Flag folgt; `parseCalls` und `checkCall` bleiben. `TestDocsCLICheckCanFail` bekommt Fälle für beide Formen (ein gültiger, ein ungültiger) und für Nicht-Aufrufe (`apt install ./adminhelper-agent_1_amd64.deb`); `docsCallFloor` steigt auf die neue Zahl abzüglich eins. Findet der Leser eine echte Abweichung in der Doku, wird sie korrigiert (DE+EN).
Beweis: R-0851 Code-Lesung docs_cli_test.go docCallRE; docs/admin/agent-deployment.html:138, docs/developer/cicd.html:508
Dedup-Key: ref:agent:docs_cli_test.go:path-exe-calls
Verify: bash scripts/dev/verify.sh agent --strict -- ./cmd/...
Doku: keine (Test; bei einem Fund die betroffene Seite DE+EN)

### T2 — monitor: ctx von smartctl-Scan und systemctl-Aufrufen testen (R-0883)  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/smart_test.go, apps/agent/internal/monitor/services_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @bdb7d3b3 2026-10-29T21:57:40+01:00
Review: approve (.ah-out/review/klein-tests-agent-1/T2.verdict.json)
Änderung: Je ein Test legt einen Marker in den `ctx` (`context.WithValue`) und prüft im Stub, dass der scan-Aufruf von `collectSmart` und die systemctl-Aufrufe aus `filterEnabledInactive` und `resolveAliases` (über `serviceHealth`) genau diesen `ctx` bekommen. Gegenprobe: `context.Background()` an der Stelle färbt den Test rot.
Beweis: R-0883 Code-Lesung smart.go:68, services_linux.go:56-57
Dedup-Key: ref:agent:smart.go:ctx-untested
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/...
Doku: keine (Test)

### T3 — Funde der Abschlussprüfung: Service-Test über den Kollektor, PowerShell-Aufruf lesen (R-0851, R-0883)  [x]
Komponente: agent · Dateien: apps/agent/cmd/adminhelper-agent/docs_cli_test.go, apps/agent/internal/monitor/services_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @b5235af2 2026-10-29T22:11:22+01:00
Review: approve (.ah-out/review/klein-tests-agent-1/T3.verdict.json)
Änderung: Der Service-Test stubbt list-units und list-unit-files so, dass `collectServiceHealth` selbst einen Kandidaten und einen Alias findet und beide show-Aufrufe mit dem Marker-`ctx` stellt (Gegenprobe `context.Background()` an `filterEnabledInactive`/`resolveAliases` färbt ihn rot). Der Doku-Leser liest den PowerShell-Aufruf `& 'C:\Program Files\…\adminhelper-agent.exe' provision` mit Backtick-Fortsetzung (agent-deployment.html:155 DE, :154 EN); Fixture-Fälle und `docsCallFloor` (28 echte Aufrufe) angepasst.
Beweis: Abschlussprüfung branch.verdict.json, zwei Funde „wichtig“
Dedup-Key: ref:agent:docs_cli_test.go:path-exe-calls
Verify: bash scripts/dev/verify.sh agent --strict -- ./cmd/... ./internal/monitor/...
Doku: keine (Test)

## Entscheidungen
