# klein-doku-11 — Task-Ledger
Status: geplant · Branch: feature/klein-doku-11 · Review: am Ende
Spec: docs/features/klein-doku-11.md (Roadmap R-1775)
Heavy: none — reine Doku
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — agent.html: FreeBSD-Platten-Zelle nennt nur die Typen von gopsutil (R-1775)  [ ]
Komponente: scripts · Dateien: docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/klein-doku-11.md
Änderung: DE "nimmt von gopsutil nur die Typen und die Rechnung" → "nimmt von gopsutil nur die Typen und rechnet nach gopsutils Formel"; EN entsprechend; die Klammer zu `disksFromFsstat` bleibt. Changelog-Fragment (umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/agent.html, docs/en/developer/agent.html
Task-Review: am Ende

## Entscheidungen
