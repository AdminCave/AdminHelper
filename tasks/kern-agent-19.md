# kern-agent-19 — Task-Ledger
Status: geplant · Branch: feature/kern-agent-19 · Review: am Ende
Spec: docs/features/kern-agent-19.md (Roadmap R-1682)
Heavy: linux-full — apps/agent (Provisionierung); nur Ausgabe und Fehlerklassifikation, kein Cross-Host-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1682: provision meldet einen frpc, der nicht startet oder stoppt  [ ]
Komponente: agent · Dateien: apps/agent/internal/frpc/apply.go, apps/agent/internal/frpc/apply_test.go, apps/agent/internal/provision/provision.go, apps/agent/internal/provision/provision_test.go, changelog.d/kern-agent-19.md
Beweis: reviewer+security kern-agent-18 2026-11-21: warnOnServiceFailure macht errFrpcService zu nil (apps/agent/internal/frpc/apply.go:164), Apply liefert N (apply.go:137-140), provision.go:220 meldet "set up (N tunnels)" nach der Warnzeile
Dedup-Key: bug:agent:provision:frp-result-on-service-failure
Änderung: `warnOnServiceFailure` entfernt den Hash wie bisher und gibt dann `frpc.ErrServiceDeferred` (exportiert, umschließt die Ursache) statt `nil` zurück; `Apply` liefert dabei die Tunnelzahl mit. `provision` erkennt ihn per `errors.Is` und druckt eine Zeile "configured (N tunnels), but frpc did not start: …" bzw. "frpc could not be stopped: …", ohne abzubrechen; ein anderer Fehler bleibt fatal. Tests erst rot: Apply mit scheiterndem Start liefert N und ErrServiceDeferred, provision druckt bei ErrServiceDeferred keine Erfolgszeile (mit und ohne Paket) und endet mit "Provisioning abgeschlossen".
Verify: bash scripts/dev/verify.sh agent --strict
Doku: changelog.d/kern-agent-19.md
