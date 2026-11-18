# klein-ui-desktop-5 — Heartbeat-Einheit, Neu-gefunden zuerst — Task-Ledger
Status: geplant · Branch: feature/klein-ui-desktop-5 · Review: pro Task
Spec: docs/features/klein-ui-desktop-5.md (Roadmap R-1564, R-1542)
Heavy: none — reine Desktop-UI, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Desktop-UI: Heartbeat liest Sekunden aus beiden Meldungsformen  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/section/SecHeartbeat.svelte, apps/desktop/ui/src/components/monitoring/section/SecHeartbeat.test.ts
Beweis: Dedup-Key bug:desktop:SecHeartbeat.svelte:secondsOf · HEAD: 3aa2499f1 · neuer Test mit "Agent unreachable for 47 min (limit: 15 min)" ist rot (zeigt 47 s statt 47 min)
Änderung: R-1564. `secondsOf` erkennt "unreachable for N min" (N×60) und "last report Ns ago"; sonst null (—). Neue Testdatei zuerst rot (SPDX-Header), deckt min, s, und unbekannte Meldung ab.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/section/SecHeartbeat.test.ts
Doku: keine (Bugfix an einer Anzeige, kein dokumentiertes Verhalten betroffen)

### T2 — Desktop-UI: Karte "Neu gefunden" vor den Problem-Karten  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/MonServerDashboard.svelte, apps/desktop/ui/src/components/monitoring/MonServerDashboard.test.ts, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/klein-ui-desktop-5.md
Änderung: R-1542. Die Findings-Karte rendert vor `cards.problems`; der Kommentar "Concept §3.14" und der Test "puts problem cards first…" passen sich an (Reihenfolge Neu gefunden, Problem-Karten, Rest). Doku-Absatz zur Reihenfolge DE+EN, Changelog (Fixed für R-1564, Changed für R-1542).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/MonServerDashboard.test.ts
Doku: docs/admin/monitoring.html docs/en/admin/monitoring.html changelog.d/klein-ui-desktop-5.md
