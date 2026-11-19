<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ui-desktop-6 — Task-Ledger
Status: geplant · Branch: feature/klein-ui-desktop-6 · Review: am Ende
Spec: docs/features/klein-ui-desktop-6.md (Roadmap R-1592)
Heavy: none — nur Assets, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1592: App-Icons aus der AdminCave-Marke, Docs-Logo angleichen  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/icons, docs/assets/logo.svg, changelog.d/klein-ui-desktop-6.md
Beweis: Kevin 2026-11-18 (Nutzermeldung); Befund `icons/icon.png` = blaues „A“, `ui/public/logo.svg` = AdminCave-Marke (122ca2dc5)
Semantik: keine Stelle in docs/ — Kevin hat das Zeichen am Gate entschieden (AdminCave-Marke, 2026-11-19)
Änderung: `icons/source.svg` (Marke, Rundquadrat `#16181c`, Glyph `#ededee`, SPDX), daraus `tauri icon` für alle Größen; `docs/assets/logo.svg` auf die Marke. Gegenprobe: das erzeugte `icon.png` ist nicht mehr das alte (Pixelvergleich Mitte/Ecke) und 512×512 RGBA; `icon.ico` enthält 16–256.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: changelog.d/klein-ui-desktop-6.md; docs/assets/logo.svg (eine Datei für DE+EN)
