# TOFU-Warnung in agent-install.sh — Task-Ledger
Status: bereit · Branch: feature/ops-11 · Review: am Ende
Spec: docs/features/ops-11.md (Roadmap R-1634)
Heavy: none — nur der Text einer Warnung, der Stub-Test in scripts deckt den Zweig
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — TOFU-Warnung zeigt aufs Server-Zertifikat (R-1634)  [x]
Komponente: scripts · Dateien: scripts/agent-install.sh, scripts/tests/agent_install_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d3513b74a 2026-11-19T17:16:57+01:00
Review: am Ende (Branch-Review)
Änderung: Der Fallback-Zweig für Agents ohne --ca-fp warnt nicht mehr, den Fingerprint mit dem Provisionierungs-Tab zu vergleichen, sondern mit dem Server-Zertifikat (wie der Hinweis des Agents) und nennt das Agent-Update als Weg zur verifizierten Erstverbindung. Der Test des Fallbacks prüft erst rot, dass keine Warnung auf den Tab verweist.
Beweis: security ops-10 Runde 2, 2026-11-19 (scripts/agent-install.sh:391)
Dedup-Key: bug:scripts:agent-install.sh:tofu-warning
Verify: bash scripts/dev/verify.sh scripts --strict -- agent_install_test
Doku: keine (agent-deployment.html beschreibt den Vergleich mit dem Server-Zertifikat schon)
