# Desktop-Dashboard: keine Nullen und kein Leerzustand bei Laden oder Fehler — Task-Ledger
Status: erledigt · Branch: feature/kern-dashboard-1 · Review: am Ende
Spec: Roadmap R-0781
Heavy: none — nur pages/Dashboard.svelte und seine vitest-Dateien; keine Desktop-E2E-Spec prüft Kacheln oder den Leerzustand (grep apps/desktop/e2e)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-0781: Zuletzt-Liste ohne Leerzustand unter dem Fehler, Kacheln Verbindungen und Server mit „-“  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/pages/Dashboard.svelte, apps/desktop/ui/src/pages/Dashboard.load.test.ts, apps/desktop/ui/src/pages/Dashboard.layout.test.ts, changelog.d/kern-dashboard-1.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @8c6ebb6c2 2026-11-20T13:48:23+01:00
Review: am Ende (Branch-Review)
Änderung: Die Liste „Zuletzt“ zeigt `dashboard.empty` nur, wenn die Verbindungen ohne Fehler geladen sind; nach einem Fehler ohne Einträge steht dort „-“ (der Banner darüber nennt den Fehler). Die Kachel Verbindungen zeigt „-“, solange keine Liste da ist und geladen wird oder der Abruf scheiterte; die Kachel Server zeigt „-“, bis das Monitoring ohne Fehler geladen ist (`monitoringKnown`, wie die Kachel Probleme seit R-0658). Tests erst rot.
Beweis: desktop-ui-fixes, Session fe 2026-10-22, Code-Lesung; heute apps/desktop/ui/src/pages/Dashboard.svelte:136-138 (`{:else}` → `dashboard.empty` auch bei `$connectionsStore.error`), :93 und :103 (Kacheln ohne Lade-/Fehlerzustand)
HEAD: 70b4f3719
Dedup-Key: bug:desktop-ui:Dashboard.svelte:empty-under-error
Semantik: keine Stelle in docs/ — gesucht in docs/developer/desktop.html (Dashboard „Übersicht/Status nach Login“) und docs/user; Vorbild im Code: Kachel Probleme zeigt „-“, „zero problems would read as a healthy monitoring“ (Dashboard.svelte:59)
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/pages/Dashboard
Doku: changelog.d/kern-dashboard-1.md (Doku-Seiten beschreiben die Kacheln nicht)

### T2 — R-0781: Kachel-Hinweise im selben Zustand, behaltene Liste zählt  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/pages/Dashboard.svelte, apps/desktop/ui/src/pages/Dashboard.load.test.ts, apps/desktop/ui/src/pages/Dashboard.layout.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @362382d46 2026-11-20T14:06:07+01:00
Review: am Ende (Branch-Review)
Änderung: Abschlussprüfung (request_changes, 2× wichtig): Die Hinweise „SSH · RDP · Web“ und „mit Agent“ entfallen, solange die Kachel „-“ zeigt; behält ein gescheiterter Abruf die Liste derselben Quelle (stores/connections.ts reloadForMode, keep), zählt die Kachel sie weiter, „-“ nur ohne Einträge. Tests erst rot.
Beweis: reviewer kern-dashboard-1 branch @0e5bf8f01, Dashboard.svelte:63, :98-103, :110
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/pages/Dashboard
Doku: keine (changelog.d/kern-dashboard-1.md aus T1 deckt es)
