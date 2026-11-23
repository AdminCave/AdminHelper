# klein-tests-agent-2 — Task-Ledger
Status: aktiv · Branch: feature/klein-tests-agent-2 · Review: am Ende
Spec: docs/features/klein-tests-agent-2.md (Roadmap R-1729)
Heavy: none — nur ein Unit-Test im Paket probe, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1729: der kurze HTTP-Test liest die Container-Ports nicht über den echten Docker  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_net_test.go
Änderung: `TestHTTPSensorTellsASilentServerOfPlainTextWithinAShortTimeout` stubbt `publishedPorts` (leere Liste) mit Cleanup, wie `app_web_test.go:216-218`.
Beweis: main@6895f8eaf, `go test -count=20 -run 'TestHTTPSensorTellsASilentServerOfPlainTextWithinAShortTimeout$' ./internal/probe/` in `apps/agent` mit 35 laufenden Containern: 19 von 20 rot („status error (timed out after 1s)“); Messung `dialThrough` 856 ms, `fetch` 1 ms.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: keine (nur ein Test)
