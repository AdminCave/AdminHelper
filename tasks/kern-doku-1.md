<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-doku-1 — Task-Ledger
Status: erledigt · Branch: feature/kern-doku-1 · Review: am Ende
Spec: docs/features/kern-doku-1.md (Roadmap R-0857)
Heavy: none — nur Doku, kein Stack-, Gateway-, PKI- oder Install-Pfad im Code
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — apt-Rezept installiert nur den gepinnten Signaturschlüssel (R-0857)  [x]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/kern-doku-1.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @25da9a42 2026-10-30T01:57:39+01:00
Review: am Ende (Branch-Review)
Änderung: Schritt 1 des apt-Rezepts (`agent-deployment.html:76-85`, EN dito) importiert die geladene Datei in ein `mktemp -d`-Verzeichnis, exportiert nur `$FPR`, prüft den Primär-Fingerprint des Exports und installiert nur ihn, wie `pinned_keyring` in `scripts/agent-install.sh:180-208`. Probe mit Wegwerf-Schlüsseln (privat).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/kern-doku-1.md
Task-Review: am Ende

## Entscheidungen
- 2026-10-30: Plan-Commit vor dem ersten Push neu geschrieben (Spec neutral, Hinweis security); Baum gleich dem alten Stand. Die Evidenz von T1 nennt den alten Commit 25da9a42, im Branch b8dda8fa.
