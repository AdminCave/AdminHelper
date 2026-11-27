# klein-ui-desktop-7 — Task-Ledger
Status: geplant · Branch: feature/klein-ui-desktop-7 · Review: pro Task
Spec: docs/features/klein-ui-desktop-7.md (Roadmap R-0439, R-0783)
Heavy: none — reine Desktop-UI, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — MonCheckLine: Enter löst Aktionen nur einmal aus (R-0439)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/section/MonCheckLine.svelte, apps/desktop/ui/src/components/monitoring/section/MonCheckLine.test.ts
Änderung: Die `onkeydown`-Handler der Aktions-Buttons entfallen (der native Klick genügt); der Zeilen-Handler reagiert auf Enter nur, wenn `e.target === e.currentTarget`. Neuer Komponententest (SPDX-Header): Enter auf Bearbeiten/Jetzt prüfen/Aktivieren ruft den Handler genau einmal und expandiert nicht, Enter auf der Zeile expandiert. Rot zuerst.
Beweis: Roadmap R-0439 (Bauer monitoring-templates T9, 2026-10-16), Dedup-Key: BUG:desktop-ui:MonCheckLine.svelte:enter_double_fire
Semantik: keine Stelle in docs/ — Tastaturbedienung der Prüfzeilen ist nicht dokumentiert; Absicht: eine Aktion je Tastendruck.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/section/MonCheckLine.test.ts
Doku: keine (kein dokumentiertes Verhalten)

### T2 — connections: Fehler-Banner bleibt während des Abrufs stehen (R-0783)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/connections.ts, apps/desktop/ui/src/lib/stores/connections.reload.test.ts
Änderung: `reloadForMode` setzt zu Beginn nur `loading: true` und löscht `error` erst im Erfolgsfall (dort schon `error: null`). Test: nach einem Fehlschlag bleibt `error` während des laufenden zweiten Abrufs gesetzt und verschwindet erst bei Erfolg. Rot zuerst.
Beweis: Roadmap R-0783 (connections.ts, Code-Lesung), Dedup-Key: idee:desktop-ui:connections.ts:error-flicker
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/connections.reload.test.ts
Doku: → T3

### T3 — Changelog  [ ]
Komponente: desktop-ui · Dateien: changelog.d/klein-ui-desktop-7.md
Änderung: Fragment (umlautfrei) zu beiden Korrekturen.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/connections.reload.test.ts
Doku: changelog.d/klein-ui-desktop-7.md
Task-Review: am Ende
Abhängt von: T1, T2

## Entscheidungen
