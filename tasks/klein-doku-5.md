<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-doku-5 — Task-Ledger
Status: geplant · Branch: feature/klein-doku-5 · Review: am Ende
Spec: docs/features/klein-doku-5.md (Roadmap R-1016, R-1018)
Heavy: none — Doku und ein Kommentar
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1016: Keyring-Prüfsätze verlangen fpr ausdrücklich  [ ]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html
Beweis: security-branch kern-doku-2 2026-10-30 · feature/kern-doku-2@1c9f682f docs/admin/agent-deployment.html:98 (nit)
Änderung: In Schritt 1 und 1b den awk-Satz auf `fpr` nach `pub` umstellen (wie `primary_fprs` in `scripts/agent-install.sh`), DE+EN gleich. Vorher mit Wegwerf-Schlüssel mit designiertem Widerrufer (eigenes gpg-Homedir) zeigen, dass der alte Satz abbricht und der neue `$FPR` liest; ohne Widerrufer bleibt es gleich.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html (die Änderung selbst)
Task-Review: am Ende

### T2 — R-1018: restored-Wächter nennt alle Abmeldefälle  [ ]
Komponente: web · Dateien: apps/web/src/lib/idle.ts, docs/developer/webui.html, docs/en/developer/webui.html
Beweis: reviewer branch kern-web-3 2026-10-30
Änderung: Docstring von `watchIdle` und den Satz zu `restored` in der webui-Doku DE+EN ergänzen: auch eine Zeit in der Zukunft oder keine Zahl meldet sofort ab; nur eine fehlende Zeit zählt als Bedienung. Nur Kommentar und Prosa, kein Code.
Verify: bash scripts/dev/verify.sh web --strict
Doku: docs/developer/webui.html, docs/en/developer/webui.html (die Änderung selbst)
