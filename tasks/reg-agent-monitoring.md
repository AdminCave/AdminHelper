# reg-agent-monitoring — Task-Ledger
Status: geplant · Branch: feature/reg-agent-monitoring · Review: am Ende
Spec: Roadmap R-1779
Heavy: linux-full — der Schritt agent_monitoring ist im Sammellauf rot; der Fix beweist sich vor dem Merge mit `bash scripts/tests/run.sh all --strict --step agent_monitoring` auf einer Box
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1779: agent_monitoring sucht den englischen Enrollment-Text  [ ]
Komponente: scripts · Dateien: scripts/tests/agent_monitoring_test.sh
Änderung: Die Prüfung in `agent_monitoring_test.sh:53` sucht `mTLS client certificate enrolled` statt des alten deutschen Texts, den der Agent seit c5968063b (#658) nicht mehr druckt (`apps/agent/internal/provision/provision.go:160`).
Beweis: Sammellauf 2026-11-25-0130 (unbestaetigt) · Einzelschritt main@564be0395 auf Box 3000: `run.sh all --strict --step agent_monitoring` → 0 passed, 1 failed, Marker `agent 1 did not enroll + push`, Log mit Enrollment und `Report gesendet`
Dedup-Key: reg:scripts:agent_monitoring_test.sh:enroll-string · HEAD: 564be0395
Semantik: keine Stelle in docs/ — gesucht nach „enrolled and pinned“ und „enrollt und gepinnt“; der Test prüft die Ausgabe von `agent provision` (provision.go:160)
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (nur Test)
