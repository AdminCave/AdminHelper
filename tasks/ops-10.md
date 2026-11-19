# Windows-Einzeiler agent-install.ps1 — Task-Ledger
Status: aktiv · Branch: feature/ops-10 · Review: am Ende
Spec: docs/features/ops-10.md (Roadmap R-1578)
Heavy: windows — Installer-Pfad; Kevin 2026-11-19: der windows-latest-Job aus T2 zählt als scenario-Lauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1578: scripts/agent-install.ps1 mit Doku  [ ]
Komponente: scripts · Dateien: scripts/agent-install.ps1, scripts/tests/agent_install_ps1_test.sh, scripts/tests/run.sh, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/ops-10.md
Änderung: Neues Skript (SPDX) nach Spec: Admin-Prüfung, Release per HTTPS, SHA256SUMS-Prüfung beider Dateien vor jeder Änderung, `service install` aus dem Temp-Verzeichnis, `provision --token-stdin` mit SecureString-Abfrage. Hermetischer Test (SPDX) prüft die Invarianten (kein `Invoke-Expression` geladener Inhalte, Token nie als Argument außer `-Token`, Hash-Prüfung vor `service install`, Override nur für Loopback), eingetragen in `run.sh`.
Verify: bash scripts/dev/verify.sh scripts --strict -- agent_install_ps1_test
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/ops-10.md

### T2 — R-1578: CI-Job agent-install.ps1 auf windows-latest  [ ]
Komponente: server · Dateien: .github/workflows/ci.yml, apps/server/tests/test_ci_workflow.py
Änderung: Job baut `adminhelper-agent.exe`, holt das gepinnte `frpc.exe` (FRP_VERSION/FRP_SHA256_WINDOWS_AMD64), schreibt `SHA256SUMS`, serviert es über `127.0.0.1`, fährt das Skript (Install, Dienst läuft, zweiter Lauf = Update), dann mit verfälschter `SHA256SUMS` (Abbruch, nichts geändert) und `service uninstall --purge`. Strukturtest: Job existiert, überspringt sich nicht per Ereignis.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ci_workflow.py
Doku: keine (CI-Job; docs/developer/cicd.html nennt die Windows-Jobs nicht einzeln)
Abhängt von: T1

## Entscheidungen
- 2026-11-19 Kevin: Bootstrap nur HTTPS + SHA256SUMS (keine minisign-Prüfung unter Windows); der windows-latest-CI-Job zählt als scenario-Lauf für den Session-Merge.
- 2026-11-19 Plan: baut erst nach dem Merge von ci-15 (ci.yml); #560 (ci-14) ändert ci.yml nur in einem Kommentar, vor dem Merge origin/main hineinmergen.
