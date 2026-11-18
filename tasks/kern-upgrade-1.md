<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-upgrade-1 — upgrade_path nach update.sh: Einmal-Dienst db-init — Task-Ledger
Status: geplant · Branch: feature/kern-upgrade-1 · Review: am Ende
Spec: Roadmap R-1615
Heavy: linux-full — Fix des roten Sammellauf-Schritts upgrade_path; Beweis vor dem Merge per `run.sh all --strict --step` über diesen Branch
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Tasks

### T1 — R-1615: der erfolgreich beendete Einmal-Dienst db-init zählt als gesund  [ ]
Komponente: scripts · Dateien: scripts/tests/upgrade_path_test.sh
Beweis: Sammellauf 2026-11-18-0130, `retry-upgrade_path__last_release_-__HEAD_-1.log:52` „FAIL update.sh: after the
update — missing: none not running: db-init exited“; auf dem Basis-Commit ebenso (extern). v0.46.0 hatte kein
`db-init`, v0.47.0 (erstes Release als `PREV`) hat es. Dedup-Key: bug:scripts:upgrade_path_test.sh:db-init-oneshot
HEAD: cdebcf1b3
Semantik: docs/developer/cicd.html:152 „Danach läuft <code>scripts/update.sh --ref &lt;tag&gt;</code> real gegen ein
zweites Install-Verzeichnis (<code>UPDATE_SH_OK</code> …)“ — der aktualisierte Stack ist oben; ein Einmal-Dienst,
der mit 0 endet, gehört dazu.
Änderung: `ps --all` liest dazu den Exit-Code; `db-init` darf `exited` mit Code 0 sein, jeder andere Zustand oder
Code bleibt „not running“. Die Pflicht-Dienste bleiben wie sie sind.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Test; cicd.html beschreibt das Verhalten schon)
