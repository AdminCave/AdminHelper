<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ui-desktop-6 — Task-Ledger
Status: bereit · Branch: feature/klein-ui-desktop-6 · Review: am Ende
Spec: docs/features/klein-ui-desktop-6.md (Roadmap R-1592)
Heavy: none — nur Assets, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1592: App-Icons aus der AdminCave-Marke, Docs-Logo angleichen  [x]
Komponente: desktop-rs · Dateien: docs/features/klein-ui-desktop-6.md, docs/assets/logo.svg, changelog.d/klein-ui-desktop-6.md, apps/desktop/src-tauri/icons/128x128.png, apps/desktop/src-tauri/icons/128x128@2x.png, apps/desktop/src-tauri/icons/32x32.png, apps/desktop/src-tauri/icons/64x64.png, apps/desktop/src-tauri/icons/Square107x107Logo.png, apps/desktop/src-tauri/icons/Square142x142Logo.png, apps/desktop/src-tauri/icons/Square150x150Logo.png, apps/desktop/src-tauri/icons/Square284x284Logo.png, apps/desktop/src-tauri/icons/Square30x30Logo.png, apps/desktop/src-tauri/icons/Square310x310Logo.png, apps/desktop/src-tauri/icons/Square44x44Logo.png, apps/desktop/src-tauri/icons/Square71x71Logo.png, apps/desktop/src-tauri/icons/Square89x89Logo.png, apps/desktop/src-tauri/icons/StoreLogo.png, apps/desktop/src-tauri/icons/icon.icns, apps/desktop/src-tauri/icons/icon.ico, apps/desktop/src-tauri/icons/icon.png, apps/desktop/src-tauri/icons/source.svg, apps/desktop/src-tauri/icons/source.svg.license
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @dce511613 2026-11-19T20:41:53+01:00
Review: am Ende (Branch-Review)
Beweis: Kevin 2026-11-18 (Nutzermeldung); Befund `icons/icon.png` = blaues „A“, `ui/public/logo.svg` = AdminCave-Marke (122ca2dc5)
Semantik: keine Stelle in docs/ — Kevin hat das Zeichen am Gate entschieden (AdminCave-Marke, 2026-11-19)
Änderung: `icons/source.svg` (Marke, Rundquadrat `#16181c`, Glyph `#ededee`, SPDX), daraus ImageMagick für alle Größen (echtes icns, ico 16–256); `docs/assets/logo.svg` auf die Marke. Gegenprobe: das erzeugte `icon.png` ist nicht mehr das alte (Pixelvergleich Mitte/Ecke) und 512×512 RGBA; `icon.ico` enthält 16–256.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: changelog.d/klein-ui-desktop-6.md; docs/assets/logo.svg (eine Datei für DE+EN)

### T2 — R-1592: das Favicon-SVG ist kein wohlgeformtes XML  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/public/logo.svg, docs/assets/logo.svg, apps/desktop/ui/src/logo.test.ts, changelog.d/klein-ui-desktop-6.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @840d1f18d 2026-11-19T20:49:17+01:00
Review: am Ende (Branch-Review)
Beweis: Abschlussprüfung 2026-11-19: `xmllint --noout` meldet `AttValue: " or ' expected` (Kommentar mit `<link rel=icon>` im `<style>`); ein Browser verwirft das SVG-Favicon dann ganz. Dedup-Key: BUG:desktop-ui:public/logo.svg:xml
Semantik: keine Stelle in docs/ — ein Favicon, das der Browser nicht lädt, ist kein gewolltes Verhalten
Änderung: Kommentar ohne `<` formulieren (Desktop-UI und Docs-Logo); neuer Test `src/logo.test.ts` parst `public/logo.svg` als XML (erst rot gesehen). `apps/web/public/logo.svg` hat denselben Fehler und wird eine eigene Roadmap-Zeile (andere Komponente).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/logo.test.ts
Doku: changelog.d/klein-ui-desktop-6.md (Eintrag erweitert)
