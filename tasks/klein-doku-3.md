<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-doku-3 — Task-Ledger
Status: geplant · Branch: feature/klein-doku-3 · Review: am Ende
Spec: docs/features/klein-doku-3.md (Roadmap R-0525)
Heavy: none — reine Doku, kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Admin-Uebersicht: EN an DE-Gliederung angleichen, PKI-Karte korrigieren (R-0525)  [ ]
Komponente: scripts · Dateien: docs/en/admin/index.html, docs/admin/index.html, changelog.d/klein-doku-3.md
Beweis: R-0525 EN :43 „10 y CA / 1 y client certs“ vs. apps/ca-issuer/app/pki.py:36-40 (Root 3650 d, Intermediate 1825 d, Leaf 90/365 d)
Dedup-Key: bug:docs:admin-index.html:de-en-structure-pki-claim
Semantik: docs/en/admin/operations.html:201 — „consists of a root (10 years) and the intermediates `tunnel`, `access` and `internal` (5 years)“
Änderung: EN erhaelt „Typical admin tasks“ (mit der Lesereihenfolge), „Architecture in a paragraph“ und „Versions“ in DE-Reihenfolge; die FRP-Karte nennt statt der Laufzeiten die PKI mit Verweis auf Operations. Der Versionsabschnitt nennt in DE und EN die aktuelle Serie.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/en/admin/index.html, docs/admin/index.html
Task-Review: am Ende
