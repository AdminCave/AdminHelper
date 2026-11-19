# Windows-Einzeiler agent-install.ps1 — Task-Ledger
Status: aktiv · Branch: feature/ops-10 · Review: am Ende
Spec: docs/features/ops-10.md (Roadmap R-1578)
Heavy: windows — Installer-Pfad; Kevin 2026-11-19: der windows-latest-Job aus T2 zählt als scenario-Lauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1578: scripts/agent-install.ps1 mit Doku  [x]
Komponente: scripts · Dateien: scripts/agent-install.ps1, scripts/tests/agent_install_ps1_test.sh, scripts/tests/run.sh, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/ops-10.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d67da6b4c 2026-11-19T12:40:23+01:00
Review: am Ende (Branch-Review)
Änderung: Neues Skript (SPDX) nach Spec: Admin-Prüfung, Release per HTTPS, SHA256SUMS-Prüfung beider Dateien vor jeder Änderung, `service install` aus dem Temp-Verzeichnis, `provision --token-stdin` mit SecureString-Abfrage. Hermetischer Test (SPDX) prüft die Invarianten (kein `Invoke-Expression` geladener Inhalte, Token nie als Argument außer `-Token`, Hash-Prüfung vor `service install`, Override nur für Loopback), eingetragen in `run.sh`.
Verify: bash scripts/dev/verify.sh scripts --strict -- agent_install_ps1_test
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/ops-10.md

### T2 — R-1578: CI-Job agent-install.ps1 auf windows-latest  [x]
Komponente: server · Dateien: .github/workflows/ci.yml, apps/server/tests/test_ci_workflow.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @187e22ed6 2026-11-19T12:44:11+01:00
Review: am Ende (Branch-Review)
Änderung: Job baut `adminhelper-agent.exe`, holt das gepinnte `frpc.exe` (FRP_VERSION/FRP_SHA256_WINDOWS_AMD64), schreibt `SHA256SUMS`, serviert es über `127.0.0.1`, fährt das Skript (Install, Dienst läuft, zweiter Lauf = Update), dann mit verfälschter `SHA256SUMS` (Abbruch, nichts geändert) und `service uninstall --purge`. Strukturtest: Job existiert, überspringt sich nicht per Ereignis.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ci_workflow.py
Doku: keine (CI-Job; docs/developer/cicd.html nennt die Windows-Jobs nicht einzeln)
Abhängt von: T1


### T3 — R-1578: CI-Fälschung von SHA256SUMS unabhängig vom Trennzeichen  [x]
Komponente: server · Dateien: .github/workflows/ci.yml, apps/server/tests/test_ci_workflow.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @b326fb788 2026-11-19T12:49:28+01:00
Review: am Ende (Branch-Review)
Änderung: Lauf 44517506477: Git-Bash schreibt `SHA256SUMS` unter Windows als `<hash> *<name>`, der Regex der Fälschung erwartete zwei Leerzeichen und änderte nichts, das Skript nahm die echte Datei zu Recht an. Fälschung matcht `\s+\*?`, der Job bricht ab, wenn die gefälschte Datei der echten gleicht; der Strukturtest verlangt diese Gegenprobe.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ci_workflow.py
Doku: keine (CI-Job)
Abhängt von: T2

### T4 — R-1578: ohne -CaFp TOFU wie agent-install.sh, -Version nur SemVer  [ ]
Komponente: scripts · Dateien: scripts/agent-install.ps1, scripts/tests/agent_install_ps1_test.sh, changelog.d/ops-10.md, README.md
Änderung: Abschlussprüfung (reviewer + security, wichtig): ohne `-CaFp` gab das Skript weder `--ca-fp` noch `--insecure` mit, der Agent prüfte nur gegen die System-Roots, entgegen Warnung und Doku. Jetzt `--insecure` wie `agent-install.sh:396` und `agent-install-bsd.sh` (TOFU, Warnung bleibt); `-Version` muss SemVer sein, bevor es in den Download-Pfad geht. Nits: Changelog umlautfrei, README nennt den Windows-Einzeiler.
Verify: bash scripts/dev/verify.sh scripts --strict -- agent_install_ps1_test
Doku: README.md · changelog.d/ops-10.md (agent-deployment DE+EN beschreibt TOFU schon)

### T5 — R-1578: CI-Ablehnung am Grund prüfen, cicd-Doku nennt den Installer-Lauf  [ ]
Komponente: server · Dateien: .github/workflows/ci.yml, apps/server/tests/test_ci_workflow.py, docs/developer/cicd.html, docs/en/developer/cicd.html
Änderung: `Assert-Refused` verlangt einen Ausschnitt der erwarteten Meldung, so ist „tampered SHA256SUMS“ nicht mehr bei einem Download-Fehler grün (reviewer nit); `docs/developer/cicd.html` DE+EN nennt den End-to-End-Lauf von `agent-install.ps1` im Job `agent-windows` (reviewer wichtig).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ci_workflow.py
Doku: docs/developer/cicd.html · docs/en/developer/cicd.html
Abhängt von: T4

## Entscheidungen
- 2026-11-19 Kevin: Bootstrap nur HTTPS + SHA256SUMS (keine minisign-Prüfung unter Windows); der windows-latest-CI-Job zählt als scenario-Lauf für den Session-Merge.
- 2026-11-19 Plan: baut erst nach dem Merge von ci-15 (ci.yml); #560 (ci-14) ändert ci.yml nur in einem Kommentar, vor dem Merge origin/main hineinmergen.
- T4: ohne `-CaFp` TOFU (`--insecure`) statt Pflicht-`-CaFp` (security-Vorschlag): Gleichlauf mit `agent-install.sh`/`agent-install-bsd.sh` und dem geplanten Doku-Text; Pflicht wäre eine neue Verhaltensentscheidung.
