<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ui-web-1 — Task-Ledger
Status: bereit · Branch: feature/klein-ui-web-1 · Review: am Ende
Spec: docs/features/klein-ui-web-1.md (Roadmap R-1658)
Heavy: none — nur Asset und Unit-Test, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1658: Web-Favicon-SVG wohlgeformt machen  [x]
Komponente: web · Dateien: apps/web/public/logo.svg, apps/web/src/logo.test.ts (neu, SPDX-Header), changelog.d/klein-ui-web-1.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @4953fffa8 2026-11-20T11:39:40+01:00
Review: am Ende (Branch-Review)
Beweis: klein-ui-desktop-6 Abschlussprüfung 2026-11-19: `xmllint --noout apps/web/public/logo.svg` meldet `AttValue: " or ' expected` (Kommentar mit `<link rel=icon>` im `<style>`). Dedup-Key: BUG:web:public/logo.svg:xml
Semantik: keine Stelle in docs/ — ein Favicon, das der Browser nicht lädt, ist kein gewolltes Verhalten
Änderung: Kommentar ohne `<` formulieren (Wortlaut wie Desktop-UI); neuer Test `src/logo.test.ts` parst `public/logo.svg` als XML (erst rot gegen den heutigen Stand sehen).
Verify: bash scripts/dev/verify.sh web --strict -- src/logo.test.ts
Doku: changelog.d/klein-ui-web-1.md
