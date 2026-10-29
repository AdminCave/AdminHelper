<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-agent-1 — Task-Ledger
Status: aktiv · Branch: feature/klein-tests-agent-1 · Review: pro Task
Spec: docs/features/klein-tests-agent-1.md (Roadmap R-0851, R-0883)
Heavy: none — Unit-Tests im Agent, kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — docs_cli_test: Aufrufe über Pfad und .exe lesen (R-0851)  [ ]
Komponente: agent · Dateien: apps/agent/cmd/adminhelper-agent/docs_cli_test.go
Änderung: `docCalls` führt vor dem Abgleich einen Aufruf über einen Pfad (`./`, `.\`, `/usr/bin/`) oder die Windows-Binary (`adminhelper-agent-windows-x86_64.exe`, `adminhelper-agent.exe`) auf den Namen `adminhelper-agent` zurück, wenn ein Unterbefehl oder ein Flag folgt; `parseCalls` und `checkCall` bleiben. `TestDocsCLICheckCanFail` bekommt Fälle für beide Formen (ein gültiger, ein ungültiger) und für Nicht-Aufrufe (`apt install ./adminhelper-agent_1_amd64.deb`); `docsCallFloor` steigt auf die neue Zahl abzüglich eins. Findet der Leser eine echte Abweichung in der Doku, wird sie korrigiert (DE+EN).
Beweis: R-0851 Code-Lesung docs_cli_test.go docCallRE; docs/admin/agent-deployment.html:138, docs/developer/cicd.html:508
Dedup-Key: ref:agent:docs_cli_test.go:path-exe-calls
Verify: bash scripts/dev/verify.sh agent --strict -- ./cmd/...
Doku: keine (Test; bei einem Fund die betroffene Seite DE+EN)

### T2 — monitor: ctx von smartctl-Scan und systemctl-Aufrufen testen (R-0883)  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/smart_test.go, apps/agent/internal/monitor/services_linux_test.go
Änderung: Je ein Test legt einen Marker in den `ctx` (`context.WithValue`) und prüft im Stub, dass der scan-Aufruf von `collectSmart` und die systemctl-Aufrufe aus `filterEnabledInactive` und `resolveAliases` (über `serviceHealth`) genau diesen `ctx` bekommen. Gegenprobe: `context.Background()` an der Stelle färbt den Test rot.
Beweis: R-0883 Code-Lesung smart.go:68, services_linux.go:56-57
Dedup-Key: ref:agent:smart.go:ctx-untested
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/...
Doku: keine (Test)

## Entscheidungen
