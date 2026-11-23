# klein-tests-agent-2 — Task-Ledger
Status: erledigt · Branch: feature/klein-tests-agent-2 · Review: am Ende
Spec: docs/features/klein-tests-agent-2.md (Roadmap R-1729)
Heavy: none — nur ein Unit-Test im Paket probe, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1729: der kurze HTTP-Test liest die Container-Ports nicht über den echten Docker  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_net_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @a4519dcbe 2026-11-23T12:04:03+01:00
Review: am Ende (Branch-Review)
Änderung: `TestHTTPSensorTellsASilentServerOfPlainTextWithinAShortTimeout` stubbt `publishedPorts` (leere Liste) mit Cleanup, wie `app_web_test.go:216-218`, und startet mit `freshSnapshot(t)`: ohne ihn scheitert jeder weitere Lauf im selben Prozess (`-count>1`) am veralteten Listener-Snapshot („no process listens on port“).
Beweis: main@6895f8eaf, `go test -count=20 -run 'TestHTTPSensorTellsASilentServerOfPlainTextWithinAShortTimeout$' ./internal/probe/` in `apps/agent` mit 35 laufenden Containern: 19 von 20 rot (zwei Ursachen: im ersten Lauf „status error (timed out after 1s)“ durch Docker, in den weiteren der veraltete Listener-Snapshot); in getrennten Prozessen ohne Stub 4 von 33 rot mit „timed out after 1s“; Messung `dialThrough` 856 ms, `fetch` 1 ms.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: keine (nur ein Test)
