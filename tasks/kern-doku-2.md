<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-doku-2 — Task-Ledger
Status: erledigt · Branch: feature/kern-doku-2 · Review: am Ende
Spec: docs/features/kern-doku-2.md (Roadmap R-0985)
Heavy: none — nur Doku, kein Stack-, Gateway-, PKI- oder Install-Pfad im Code
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — apt-Rezept: Prüfsatz für einen schon installierten Keyring (R-0985)  [x]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/kern-doku-2.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @8b05d04d 2026-10-30T16:53:23+01:00
Review: am Ende (Branch-Review)
Änderung: Hinter Schritt 1 des apt-Rezepts (`agent-deployment.html:75-90`, EN dito) ein Prüfsatz: die installierte
Datei trägt genau einen `pub`-Schlüssel mit `$FPR`, sonst Schritt 1 erneut. Probe mit Wegwerf-Schlüsseln (privat).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/kern-doku-2.md
Task-Review: am Ende

### T2 — Prüfsatz 1b setzt den Fingerprint selbst (R-0985, Abschlussprüfung)  [x]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @a9ca4e76 2026-10-30T17:00:58+01:00
Review: am Ende (Branch-Review)
Änderung: Schritt 1b setzt `FPR` selbst, damit er allein (ohne Schritt 1 in derselben Shell) prüft; Fund `wichtig` der Abschlussprüfung.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html
Task-Review: am Ende

## Entscheidungen
