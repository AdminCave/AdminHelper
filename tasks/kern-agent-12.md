# Unix-Socket-Tests des Agents unter FreeBSD ohne Rennen — Task-Ledger
Status: geplant · Branch: feature/kern-agent-12 · Review: am Ende
Spec: docs/features/kern-agent-12.md (Roadmap R-1610)
Heavy: scenario --box opnsense — scripts/tests/opnsense_box.sh; der Test ist //go:build freebsd und läuft nur auf der Box (Box-User und root); dazu der Dauerlauf 50x auf der Box (Wackler-Regel)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Test-Server halten Unix-Verbindungen offen (R-1610)  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_local_freebsd_test.go
Änderung: Die drei Accept-Schleifen schließen eine angenommene Verbindung erst, wenn der Client sie schließt (io.Copy nach io.Discard), damit getpeername auf der Client-Seite den gebundenen Pfad liefert und nicht sun_noname.
Beweis: kern2 2026-11-18 ops-9 opnsense_box (feature/ops-9@e93012cf3, base-opnsense 20261112): sensor_local_freebsd_test.go:104
Dedup-Key: bug:agent:sensor_local_freebsd_test.go:peer-closed-race
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (nur Testcode)
