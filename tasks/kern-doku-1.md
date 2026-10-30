<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-doku-1 — Task-Ledger
Status: geplant · Branch: feature/kern-doku-1 · Review: am Ende
Spec: docs/features/kern-doku-1.md (Roadmap R-0857)
Heavy: none — nur Doku, kein Stack-, Gateway-, PKI- oder Install-Pfad im Code
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — apt-Rezept installiert nur den gepinnten Signaturschlüssel (R-0857)  [ ]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/kern-doku-1.md
Änderung: Schritt 1 des apt-Rezepts (`agent-deployment.html:76-85`, EN dito) importiert die geladene Datei in ein `mktemp -d`-Verzeichnis, exportiert nur `$FPR`, prüft den Primär-Fingerprint des Exports und installiert nur ihn, wie `pinned_keyring` in `scripts/agent-install.sh:180-208`. Probe mit Wegwerf-Schlüsseln (privat).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/kern-doku-1.md
Task-Review: am Ende
