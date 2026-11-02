<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-3 — Task-Ledger
Status: aktiv · Branch: feature/kern-agent-3 · Review: am Ende
Spec: docs/features/kern-agent-3.md (Roadmap R-1007, R-1036)
Heavy: linux-full — `apps/agent` (Abhängigkeiten und Go-Version des Agent-Binaries)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben `origin/main@0294b3b1`.

### T1 — Terminal nach Ctrl-C in der verdeckten Eingabe zurücksetzen (R-1007)  [x]
Komponente: agent · Dateien: apps/agent/cmd/adminhelper-agent/main.go, apps/agent/cmd/adminhelper-agent/provision_cmd_test.go, changelog.d/kern-agent-3.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @f0a46b8a 2026-11-02T12:39:23+01:00
Review: am Ende (Branch-Review)
Beweis: reviewer kern-agent-2 T3 (Nit), 2026-10-30 · `main.go:106` `var readTerminal = term.ReadPassword`, kein Restore bei Signal · Dedup-Key: bug:agent:main.go:readStdinSecret-sigint
Änderung: Vor `readTerminal` den Zustand mit `term.GetState` sichern und `os.Interrupt` abfangen; im Signalfall `term.Restore`, Zeilenumbruch, Exit 130; nach dem Lesen `signal.Stop`. Signalkanal, Restore und Exit als austauschbare Variablen; der Test (erst rot) schickt ein Interrupt während eines blockierenden `readTerminal` und prüft Restore mit dem gesicherten Zustand und Exit 130, dazu dass ohne Signal kein Restore-Aufruf durch den Handler erfolgt.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: changelog.d/kern-agent-3.md

### T2 — go.mod auf Go 1.27, Abhängigkeiten aktuell (R-1036)  [ ]
Komponente: agent · Dateien: apps/agent/go.mod, apps/agent/go.sum, docs/developer/agent.html, docs/en/developer/agent.html, DEVELOPMENT.md, changelog.d/kern-agent-3.md
Änderung: `go 1.27.0` mit `toolchain go1.27.3` (`apps/agent/go.mod:3`), gopsutil v4.26.10, x/sys v0.49.0, x/term v0.47.0 (`go get`, `go mod tidy`); Doku-Baum `go.mod Go 1.27` DE+EN (`docs/developer/agent.html:55`, `docs/en/developer/agent.html:55`), `DEVELOPMENT.md:740` „go.mod verlangt 1.27“.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: docs/developer/agent.html, docs/en/developer/agent.html, DEVELOPMENT.md, changelog.d/kern-agent-3.md

## Entscheidungen
- 2026-11-02 Plan: Go 1.27.3 lädt die Dev-Box (1.26.9) per `GOTOOLCHAIN=auto` nach (`GOTOOLCHAIN=go1.27.3 go version` ok); R-0998 blockiert den Zug nicht.
