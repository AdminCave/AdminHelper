# Agent: Seam-Typ fuer die frpc-Dienstaktionen — Task-Ledger
Status: bereit · Branch: feature/kern-agent-25 · Review: am Ende
Spec: docs/features/kern-agent-25.md (Roadmap R-1756)
Heavy: linux-full — apps/agent; Verhalten unveraendert, Sammellauf genuegt
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- R-1756: nur `frpc` bekommt einen Seam-Typ; `probe`, `discovery`, `cmd` haben schon je eine Form (Spec, Nicht-Ziele).
- `t.Parallel` bleibt aus, solange die Naehte Paketvariablen sind (Spec); kein Auftrag fuer den vollen Umbau.

### T1 — frpc: Dienstaktionen als ein Typ serviceOps (R-1756)  [x]
Komponente: agent · Dateien: apps/agent/internal/frpc/sync.go, apps/agent/internal/frpc/admin.go, apps/agent/internal/frpc/sync_flow_test.go, apps/agent/internal/frpc/apply_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @d7ec7487b 2026-11-26T17:25:03+01:00
Review: am Ende (Branch-Review)
Änderung: Die sieben Variablen aus `sync.go:25` werden Felder von `serviceOps`, `var service = serviceOps{…}`; die
Aufrufer in `sync.go` und `admin.go` rufen `service.<aktion>`; die Tests sichern `service` als einen Wert.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/frpc/...
Doku: keine (internes Refactoring)
