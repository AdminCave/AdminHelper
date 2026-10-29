<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ops-1 — Task-Ledger
Status: aktiv · Branch: feature/ops-1 · Review: am Ende
Spec: docs/features/ops-1.md (Roadmap R-0858, R-0864)
Heavy: none — beide Änderungen deckt der hermetische install_test.sh bzw. agent_install_test.sh ab; kein Install-Datenpfad, kein Paket, kein Stack ändert sich
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben `origin/main@5cd3f8f3`, vor dem Schreiben neu greppen. CHANGELOG umlautfrei in `changelog.d/ops-1.md`.
`security` zusätzlich bei T1. Einzelheiten der SEC-Zeile privat.

### T1 — install.sh: Admin-Passwort ohne Export-Attribut (R-0858)  [ ]
Komponente: scripts · Dateien: scripts/install.sh, scripts/tests/install_test.sh, changelog.d/ops-1.md
Änderung: Nach `ADMIN_PASSWORD=""` (`scripts/install.sh:53`) `export -n ADMIN_PASSWORD`. Test zuerst rot: der docker-Stub hält fest, ob er `ADMIN_PASSWORD` im Environment sieht; ein Lauf mit exportiertem `ADMIN_PASSWORD` und `--admin-password-file` → der Stub sieht es nicht.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: changelog.d/ops-1.md

### T2 — agent-install.sh -h druckt nur den Kopfkommentar (R-0864)  [ ]
Komponente: scripts · Dateien: scripts/agent-install.sh, scripts/tests/agent_install_test.sh, changelog.d/ops-1.md
Änderung: `-h|--help` (`scripts/agent-install.sh:124`) druckt bis zur ersten Leerzeile nach dem Kommentar statt `6,44p`. Test zuerst rot: `agent-install.sh -h` enthält `Options:`, aber kein `set -euo pipefail`.
Beweis: Code-Lesung origin/main@5cd3f8f3 scripts/agent-install.sh:44 (`set -euo pipefail`) liegt im Bereich `6,44p` von :124
Dedup-Key: bug:agent-install:help-prints-set-line
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: changelog.d/ops-1.md

## Entscheidungen
