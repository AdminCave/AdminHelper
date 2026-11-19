# Agent Linux/FreeBSD: Ordner-Overrides nur in Testläufen — Task-Ledger
Status: aktiv · Branch: feature/kern-agent-13 · Review: am Ende
Spec: docs/features/kern-agent-13.md (Roadmap R-1655, R-1656)
Heavy: linux-full — Pfade des Agents auf Linux/FreeBSD (apps/agent)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Overrides auf allen Plattformen nur in Testläufen (R-1655, R-1656)  [ ]
Komponente: agent · Dateien: apps/agent/internal/config/paths.go, apps/agent/internal/config/paths_linux.go, apps/agent/internal/config/paths_freebsd.go, apps/agent/internal/config/paths_windows.go, apps/agent/internal/config/paths_override_test.go, apps/agent/internal/config/securedir_windows.go, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-agent-13.md
Änderung: `overridesAllowed` (Vorgabe `testing.Testing`) und `override()` ziehen nach `paths.go`; `FrpDir`, `MonitorDir` und `LogDir` aller drei Plattformen lesen die Variablen nur darüber. Ein plattformneutraler Test (neue Datei mit SPDX-Header) zeigt: abgeschaltet ändern gesetzte Variablen keinen Pfad, eingeschaltet gilt der Override. Der Kommentar an `EnsureDataDir` nennt den Ordner außerhalb der Wurzel als Testfall; der veraltete Doku-Satz zu `--purge` entfällt.
Beweis: security kern-windows-3 branch 2026-11-19 · feature/kern-windows-3@0f881e67d apps/agent/internal/config/paths_linux.go
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/config/...
Doku: docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-agent-13.md

## Entscheidungen
- Eine Task, `Review: am Ende`: Abschlussprüfung durch `reviewer` und `security`.
- Heavy linux-full nach `/feature-plan` §3 (`apps/agent`); der PR-Text sagt „Heavy: Sammellauf“.
