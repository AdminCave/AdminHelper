<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-doku-4 — Task-Ledger
Status: bereit · Branch: feature/klein-doku-4 · Review: am Ende
Spec: docs/features/klein-doku-4.md (Roadmap R-0946)
Heavy: none — reine Doku, kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — DEVELOPMENT.md: lokaler Monitoring-Start mit DATA_DIR (R-0946)  [x]
Komponente: scripts · Dateien: DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @f45d0a00 2026-10-30T14:00:25+01:00
Review: am Ende (Branch-Review)
Beweis: R-0946 apps/monitoring/app/core/config.py:12-13 (`DATA_DIR` default `/app/data`, mkdir beim Import); `env -u DATA_DIR python3 -c "import app.core.config"` als Nicht-Root → PermissionError '/app'
Dedup-Key: bug:dev:monitoring-local-data-dir
Semantik: docs/developer/monitoring.html:200 — „in `$DATA_DIR/.api_key` persistiert“
Änderung: Das Startbeispiel im Abschnitt „Monitoring (lokal ohne Docker)“ setzt `DATA_DIR` auf ein beschreibbares Verzeichnis; ein Satz nennt, dass dort die automatisch erzeugte `.api_key` liegt.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: DEVELOPMENT.md
Task-Review: am Ende
