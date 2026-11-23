<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-19 — Task-Ledger
Status: aktiv · Branch: feature/klein-nachlese-19 · Review: am Ende
Spec: docs/features/klein-nachlese-19.md (Roadmap R-1726)
Heavy: none — eine Doku-Zeile im README, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1726: README nennt ./repo beim Deinstallieren  [ ]
Komponente: scripts · Dateien: README.md
Beweis: reviewer ops-15 T5 2026-11-23, README.md:196 zählt ./data/./certs auf, ./repo fehlt (uninstall.sh:116/159 löscht es). Dedup-Key: REF:nachlese:ops-15
Änderung: In der Aufzählung vor `./scripts/uninstall.sh` `./repo` (das Agent-Paket-Repo) ergänzen.
Task-Review: am Ende
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: README.md
