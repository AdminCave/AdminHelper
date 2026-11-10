# Eingebettetes RDP: eine Vorgabe für die eigene Größe — Task-Ledger
Status: geplant · Branch: feature/kern-rdp-11 · Review: am Ende
Spec: docs/features/kern-rdp-11.md (Roadmap R-1218)
Heavy: none — nur der Ersatzwert der Webview für eine fehlende eigene Größe; kein Stack-, Gateway-, PKI- oder Install-Pfad, die Desktop-Journeys prüfen keine Größe
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1218: eine Sitzung ohne gültige eigene Größe nimmt 1920x1080 wie der Einstellungsdialog  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/rdp/display.ts apps/desktop/ui/src/lib/rdp/display.test.ts docs/admin/index.html docs/en/admin/index.html changelog.d/kern-rdp-11.md
Änderung: `FIXED_DEFAULT` wird 1920x1080, der Doc-Kommentar von `parseSize` nennt es; `display.test.ts` erwartet 1920x1080 für null, „big“ und `fixedDisplay(undefined, …)` (erst rot). Admin-Doku DE+EN und Changelog-Fragment.
Beweis: R-1218 — `models/settings.ts:36` und `SettingsDialog.svelte:63` 1920x1080, `display.ts:18` 1280x720
Semantik: docs/admin/index.html „<em>Benutzerdefiniert</em> hält die Größe der Verbindung (sonst 1280&times;720)“ — beschreibt den Ersatz, Kevin 2026-11-10 entscheidet 1920x1080
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/rdp/display.test.ts
Doku: docs/admin/index.html docs/en/admin/index.html changelog.d/kern-rdp-11.md
