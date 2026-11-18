<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-windows-1 — Windows-Agent: frpc-Tunnel, Installation als Update, Dienst-Monitoring — Task-Ledger
Status: aktiv · Branch: feature/kern-windows-1 · Review: pro Task
Spec: docs/features/kern-windows-1.md (Roadmap R-1576, R-0577, R-1545, R-0708, R-1577, R-1583)
Heavy: windows — Windows-Code des Agent (Dienst-Install, frpc-Kindprozess, Registry, w32tm) läuft nur im CI-Job agent-windows (go test auf windows-latest); lokal nur GOOS=windows Build/Vet; release.yml-Anteil im Tag-Lauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1576: Programmordner beim Dienst-Install mit festen Rechten  [?] (Programmordner %ProgramFiles%\AdminHelper ist auch der MSI-Ordner der Desktop-App (productName adminhelper); geschützte DACL sperrte sie für Nicht-Admins. Empfehlung: Agent in eigenen Ordner %ProgramFiles%\AdminHelper Agent, T4 zieht alte Installationen um)
Komponente: agent · Dateien: apps/agent/internal/service/service_windows.go, apps/agent/internal/service/service_windows_test.go, tasks/kern-windows-1.md
Änderung: `Install()` legt `%ProgramFiles%\AdminHelper` mit `config.EnsureSecureDir` an (wie der Datenordner) statt
`MkdirAll` und kopiert das Binary erst danach; ein vorhandener Ordner wird ebenso eingerichtet. Test auf Windows:
DACL geschützt, nur SYSTEM und Administratoren.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T7

### T2 — R-0577: Sync richtet das Datenverzeichnis vor dem Lesen ein  [x]
Komponente: agent · Dateien: apps/agent/internal/frpc/sync.go, apps/agent/internal/frpc/sync_flow_test.go, tasks/kern-windows-1.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @5ba5c5225 2026-11-18T14:42:57+01:00
Review: approve (.ah-out/review/kern-windows-1/T2.verdict.json)
Änderung: `Sync` ruft `secureFrpDir` vor `config.LoadFrpcConfig` und vor jedem weiteren Lesen aus dem FRP- bzw.
Datenverzeichnis; die späteren Aufrufe entfallen, wo sie doppelt wären. Test: Reihenfolge über die Hook-Variablen
(Sichern vor dem ersten Lesen), plattformneutral.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (keine dokumentierte Wirkung)

### T3 — R-1545, R-0708: frpc als Kindprozess des Agent-Dienstes  [ ]
Komponente: agent · Dateien: apps/agent/internal/frpc/platform_windows.go, apps/agent/internal/frpc/supervisor_windows.go, apps/agent/internal/frpc/supervisor_windows_test.go, apps/agent/internal/frpc/frpcpin.go, apps/agent/cmd/adminhelper-agent/run_windows.go, tasks/kern-windows-1.md
Änderung: Supervisor im Dienstprozess: startet `frpc.exe -c <frpc.toml>` aus dem Programmordner nach Prüfung des
gepinnten SHA-256 (`frpcpin.go`, SPDX), in einem Job-Objekt mit KILL_ON_JOB_CLOSE; Neustart mit Backoff, wenn frpc
endet; Reload über die Admin-API wie Linux. Die Hooks (`enableFrpcService`, `restartFrpc`, `disableFrpc`,
`reloadFrpc`, `frpcActive`, `frpcDown`, `frpcOwnsAdminPort`) gehen an den Supervisor; außerhalb des Dienstprozesses
melden sie einen Fehler statt Erfolg (R-0708). Neue Dateien mit SPDX-Header. Tests auf Windows mit einem Fake-frpc
(Test-Binary): Start, Hash falsch → Fehler, Prozessende → Neustart, Stopp, Kind stirbt mit dem Job.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T7
Abhängt von: T1, T2

### T4 — R-1577: service install als Update, uninstall --purge, frpc.exe ablegen  [ ]
Komponente: agent · Dateien: apps/agent/internal/service/service_windows.go, apps/agent/internal/service/service_windows_test.go, apps/agent/cmd/adminhelper-agent/main.go, apps/agent/cmd/adminhelper-agent/main_test.go, tasks/kern-windows-1.md
Änderung: `Install()` erkennt einen vorhandenen Dienst (SCM über `golang.org/x/sys/windows/svc/mgr`), stoppt ihn,
tauscht Agent und `frpc.exe` (aus dem Ordner des laufenden Binarys, Hash wie T3 geprüft; fehlt sie: Warnung, Agent
ohne Tunnel), zieht Konfiguration und Wiederanlauf nach und startet; sonst Neuanlage wie heute. `service uninstall
--purge` entfernt zusätzlich Programm- und Datenordner. Tests: Befehlsfolge über Hooks plattformneutral, auf Windows
Install zweimal hintereinander.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T7
Abhängt von: T1, T3

### T5 — R-1545: frpc.exe als Release-Asset, Pin-Gleichstand in CI  [ ]
Komponente: scripts · Dateien: .github/workflows/release.yml, .github/workflows/ci.yml, tasks/kern-windows-1.md
Änderung: release.yml lädt das gepinnte frpc-Windows-ZIP (`FRP_SHA256_WINDOWS_AMD64`), entpackt `frpc.exe`, prüft den
SHA-256 gegen die Go-Konstante aus `frpcpin.go` und legt sie als `frpc-windows-x86_64.exe` in `dist/` (damit in
`SHA256SUMS` mit minisign); ci.yml prüft den Gleichstand der Konstante mit den Workflow-Pins. Der PR ändert Workflows:
Kevin merged.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: → T7
Abhängt von: T3

### T6 — R-1583: Starttyp der Windows-Dienste und Zeitsynchronisation  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/scquery.go, apps/agent/internal/monitor/scquery_test.go, apps/agent/internal/monitor/services_windows.go, apps/agent/internal/monitor/services_windows_test.go, apps/agent/internal/monitor/system_other.go, apps/agent/internal/monitor/system_windows.go, apps/agent/internal/monitor/system_windows_test.go, tasks/kern-windows-1.md, apps/agent/internal/monitor/w32tm.go, apps/agent/internal/monitor/w32tm_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @c56bedb19 2026-11-18T14:52:49+01:00
Review: approve (.ah-out/review/kern-windows-1/T6.verdict.json)
Änderung: Starttyp je Dienst in einem Durchlauf aus der Registry (`Start`, `DelayedAutostart`, `TriggerInfo`):
Auto ohne Trigger → `enabled`, Demand → `manual`, Disabled → `disabled`; gestoppte `enabled`-Dienste in
`enabled_inactive`. Neu `system_windows.go` (SPDX): `system_state.time_synchronized` aus `w32tm /query /status`
(Leap-Indikator 3 oder lokale Uhr als Quelle = nicht synchron; unlesbar → Feld fehlt mit Warnung);
`system_other.go` ohne Windows. Parser plattformneutral getestet, Registry-Lesen auf Windows.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T7

### T7 — Doku: Windows-Abschnitt der Agent-Verteilung, Changelog  [ ]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/kern-windows-1.md, tasks/kern-windows-1.md
Änderung: Windows-Abschnitt DE+EN: `frpc-windows-x86_64.exe` neben den Agent legen, Install = Update, `uninstall
--purge`, Tunnel laufen jetzt auf Windows, Defender-Hinweis; Changelog-Fragment.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/kern-windows-1.md
Task-Review: am Ende

### T8 — R-1583: Dienstnamen auf Windows ohne Groß-/Kleinschreibung  [?] (Agent-Namen klein schreiben ändert Inventar und Regeln; Empfehlung: Agent unverändert, Monitoring vergleicht case-insensitiv, R-0436 neu aufnehmen)
Komponente: agent · Dateien: apps/agent/internal/monitor/scquery.go, tasks/kern-windows-1.md
Änderung: nach Kevins Antwort.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (nach Antwort)

## Entscheidungen
- T2: Sync sichert das FRP-Verzeichnis beim ersten Lauf je Prozess vor jedem Lesen (atomic.Bool `frpDirSecured`); spätere Läufe ohne Änderung gehen keinen Baum ab (wie bisher), Läufe mit Änderung sichern weiter vor dem Schreiben.
- T6: enabled_inactive nimmt jeden gestoppten „enabled“-Dienst auf, auch einen sauber gestoppten (Admin-Stopp, wie systemctl stop unter Linux, Spec Ziel 5); gewollt endende Auto-Dienste nimmt die ignore-Liste der Monitoring-Regel aus. Auto-Start mit TriggerInfo zählt als „manual“. DelayedAutostart wird nicht gelesen (ändert enabled nicht, YAGNI). w32tm-Leap-Indikator wird über Position und Wert gelesen, nicht über das Label (nur englisch verifiziert).
