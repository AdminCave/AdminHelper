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

### T1 — R-1576: Programmordner beim Dienst-Install mit festen Rechten  [x]
Komponente: agent · Dateien: apps/agent/internal/service/service_windows.go, apps/agent/internal/service/service_windows_test.go, tasks/kern-windows-1.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @929bb7059 2026-11-18T15:03:10+01:00
Review: approve (.ah-out/review/kern-windows-1/T1.verdict.json)
Änderung: `Install()` legt den eigenen Programmordner `%ProgramFiles%\AdminHelper Agent` (Program Files über die
Known-Folder-API) mit `config.EnsureSecureDir` an (wie der Datenordner) statt `MkdirAll` und kopiert das Binary erst
danach; ein vorhandener Ordner wird ebenso eingerichtet. Test auf Windows: DACL geschützt, nur SYSTEM und
Administratoren; Ordner ist der eigene.
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

### T3 — R-1545, R-0708: frpc als Kindprozess des Agent-Dienstes  [x]
Komponente: agent · Dateien: apps/agent/internal/frpc/platform_windows.go, apps/agent/internal/frpc/supervisor_windows.go, apps/agent/internal/frpc/supervisor_windows_test.go, apps/agent/internal/frpc/frpcpin.go, apps/agent/cmd/adminhelper-agent/run_windows.go, tasks/kern-windows-1.md, apps/agent/internal/frpc/tcptable.go, apps/agent/internal/frpc/tcptable_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @96249132c 2026-11-18T15:16:46+01:00
Review: approve (.ah-out/review/kern-windows-1/T3.verdict.json)
Änderung: Supervisor im Dienstprozess: startet `frpc.exe -c <frpc.toml>` aus dem Programmordner nach Prüfung des
gepinnten SHA-256 (`frpcpin.go`, SPDX), in einem Job-Objekt mit KILL_ON_JOB_CLOSE; Neustart mit Backoff, wenn frpc
endet; Reload über die Admin-API wie Linux. Die Hooks (`enableFrpcService`, `restartFrpc`, `disableFrpc`,
`reloadFrpc`, `frpcActive`, `frpcDown`, `frpcOwnsAdminPort`) gehen an den Supervisor; außerhalb des Dienstprozesses
melden sie einen Fehler statt Erfolg (R-0708). Neue Dateien mit SPDX-Header. Tests auf Windows mit einem Fake-frpc
(Test-Binary): Start, Hash falsch → Fehler, Prozessende → Neustart, Stopp, Kind stirbt mit dem Job.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T7
Abhängt von: T1, T2

### T4 — R-1577: service install als Update, uninstall --purge, frpc.exe ablegen  [x]
Komponente: agent · Dateien: apps/agent/internal/service/service_windows.go, apps/agent/internal/service/service_windows_test.go, apps/agent/cmd/adminhelper-agent/main.go, tasks/kern-windows-1.md, apps/agent/internal/service/install_plan.go, apps/agent/internal/service/install_plan_test.go, apps/agent/internal/service/purge_other.go, apps/agent/internal/config/securedir_windows.go, apps/agent/internal/config/securedir_windows_test.go, apps/agent/internal/frpc/frpcpin.go, apps/agent/internal/frpc/supervisor_windows.go, apps/agent/cmd/adminhelper-agent/service_cmd_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @16eccd1c1 2026-11-18T15:36:26+01:00
Review: approve (.ah-out/review/kern-windows-1/T4.verdict.json)
Änderung: `Install()` erkennt einen vorhandenen Dienst (SCM über `golang.org/x/sys/windows/svc/mgr`), stoppt ihn,
tauscht Agent und `frpc.exe` (aus dem Ordner des laufenden Binarys, Hash wie T3 geprüft; fehlt sie: Warnung, Agent
ohne Tunnel), zieht Konfiguration und Wiederanlauf nach und startet; sonst Neuanlage wie heute. Eine alte Installation
in `%ProgramFiles%\AdminHelper` (T1) zieht dabei in `%ProgramFiles%\AdminHelper Agent` um: Dienst auf den neuen Pfad,
alte Agent-Dateien weg, der Ordner bleibt (er gehört der Desktop-App). Agent und `frpc.exe` entstehen gleich mit
Owner Administratoren (Security-Descriptor beim Anlegen, kein Fenster mit dem installierenden Konto als Owner). `service uninstall
--purge` entfernt zusätzlich Programm- und Datenordner. Tests: Befehlsfolge über Hooks plattformneutral, auf Windows
Install zweimal hintereinander.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T7
Abhängt von: T1, T3

### T5 — R-1545: frpc.exe als Release-Asset, Pin-Gleichstand in CI  [x]
Komponente: scripts · Dateien: .github/workflows/release.yml, .github/workflows/ci.yml, tasks/kern-windows-1.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @706e9cb3a 2026-11-18T16:00:31+01:00
Review: approve (.ah-out/review/kern-windows-1/T5.verdict.json)
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

### T7 — Doku: Windows-Abschnitt der Agent-Verteilung, Changelog  [x]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-windows-1.md, tasks/kern-windows-1.md, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d86f359c4 2026-11-18T16:11:51+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Windows-Abschnitt DE+EN: Programmordner `%ProgramFiles%\AdminHelper Agent` (auch in monitoring.html und
developer/agent.html), `frpc-windows-x86_64.exe` neben den Agent legen, Install = Update, `uninstall --purge`, Tunnel
laufen jetzt auf Windows, Starttyp und `enabled_inactive` auf Windows (gewollt endende Auto-Dienste über die
Ausnahmen der Dienst-Regel), Defender-Hinweis; developer/cicd.html DE+EN (aus T5): `frp-consistency` prüft
`PinnedVersion` gegen `FRP_VERSION` und frpc.exe gegen `ExeSHA256`, Release-Asset `frpc-windows-x86_64.exe`;
Changelog-Fragment.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/kern-windows-1.md
Task-Review: am Ende

### T8 — R-1583: Dienstnamen auf Windows ohne Groß-/Kleinschreibung  [~] (Kevin 2026-11-18: Agent unverändert, Monitoring vergleicht Dienstnamen case-insensitiv (R-0436, Kern 1))
Komponente: agent · Dateien: apps/agent/internal/monitor/scquery.go, tasks/kern-windows-1.md
Änderung: nach Kevins Antwort.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (nach Antwort)

### T9 — R-1576: Desktop zeigt den neuen Programmordner im Credential-Befehl  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/card/CredentialDialog.svelte, apps/desktop/ui/src/components/monitoring/card/CredentialDialog.test.ts, tasks/kern-windows-1.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @63f78fdce 2026-11-18T16:04:52+01:00
Review: approve (.ah-out/review/kern-windows-1/T9.verdict.json)
Änderung: Der PowerShell-Befehl für Windows-Hosts ruft `C:\Program Files\AdminHelper Agent\adminhelper-agent.exe` (T1);
Test erwartet den neuen Pfad.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/card/CredentialDialog.test.ts
Doku: → T7
Abhängt von: T1

### T10 — Doku: system_state je Plattform (Fund der Abschlussprüfung)  [x]
Komponente: scripts · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @2681243e6 2026-11-18T16:21:40+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Der Report-Block `system_state` steht als „nur Linux“ beschrieben; seit T6 sendet Windows `time_synchronized`, FreeBSD schon vorher `reboot_required` und `security_updates`. Je Plattform die Felder nennen, DE+EN.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/monitoring.html, docs/en/developer/monitoring.html
Task-Review: am Ende

### T11 — Fake-frpc im Windows-Test endet nicht mehr am Deadlock (Fund der PR-CI)  [x]
Komponente: agent · Dateien: apps/agent/internal/frpc/supervisor_windows_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @03097a1e1 2026-11-18T16:59:48+01:00
Review: approve (.ah-out/review/kern-windows-1/T11.verdict.json)
Beweis: PR #574 CI-Lauf 44336869597, Job „Go Agent (test, Windows)“: `TestSupervisorStartsRestartsAndStopsFrpc` „restart: stop frpc: TerminateProcess: Access is denied“. `fakeFrpcMain` blockiert mit `select {}`; ohne weitere Goroutine bricht die Go-Laufzeit mit „all goroutines are asleep - deadlock!“ und Exit 2 ab (Probe unter Linux: exit status 2), der Fake stirbt also sofort, und `Kill` trifft einen endenden Prozess.
Änderung: Der Fake wartet mit `time.Sleep` in einer Schleife statt `select {}`, bis der Supervisor ihn beendet.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (Testcode)

### T12 — Lockstep-Test kopiert frpcpin.go mit (Fund der PR-CI)  [x]
Komponente: server · Dateien: apps/server/tests/test_release_images.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @b584bfc1b 2026-11-18T17:00:59+01:00
Review: approve (.ah-out/review/kern-windows-1/T12.verdict.json)
Beweis: PR #574 CI-Lauf 44336869597, Server-Shards 1/2: `test_the_lockstep_job_reads_the_frp_version_of_the_frps_image` rot; der Step „Compare the FRP_VERSION pins“ liest seit T3 `apps/agent/internal/frpc/frpcpin.go`, die Kopie in `_PINNED` hat die Datei nicht.
Änderung: `frpcpin.go` in `_PINNED` aufnehmen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_release_images.py
Doku: keine (Testcode)

### T13 — frpcpin.go im CI-Scope server (Fund der PR-CI)  [ ]
Komponente: server · Dateien: .github/scripts/ci_changes.py
Beweis: PR #574 CI-Lauf 44344584996, Server image lock 2/2: `test_every_path_a_python_suite_names_lies_in_the_scope_of_its_suite` rot; seit T12 nennt `apps/server/tests/test_release_images.py` `apps/agent/internal/frpc/frpcpin.go`, das außerhalb des Scopes `server` liegt: ein PR, der nur die Pin-Datei ändert, übersprünge die Server-Suite.
Änderung: `apps/agent/internal/frpc/frpcpin.go` in `SCOPES["server"]` aufnehmen, mit Kommentar.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ci_changes.py tests/test_release_images.py
Doku: keine (CI-Scope)

## Entscheidungen
- T2: Sync sichert das FRP-Verzeichnis beim ersten Lauf je Prozess vor jedem Lesen (atomic.Bool `frpDirSecured`); spätere Läufe ohne Änderung gehen keinen Baum ab (wie bisher), Läufe mit Änderung sichern weiter vor dem Schreiben.
- T6: enabled_inactive nimmt jeden gestoppten „enabled“-Dienst auf, auch einen sauber gestoppten (Admin-Stopp, wie systemctl stop unter Linux, Spec Ziel 5); gewollt endende Auto-Dienste nimmt die ignore-Liste der Monitoring-Regel aus. Auto-Start mit TriggerInfo zählt als „manual“. DelayedAutostart wird nicht gelesen (ändert enabled nicht, YAGNI). w32tm-Leap-Indikator wird über Position und Wert gelesen, nicht über das Label (nur englisch verifiziert).
- T1 (Kevin 2026-11-18): Agent in eigenen Ordner `%ProgramFiles%\AdminHelper Agent`, weil `%ProgramFiles%\AdminHelper` der MSI-Ordner der Desktop-App ist; T4 zieht alte Installationen um. Program Files kommt aus `KnownFolderPath`, nicht aus der Umgebung.
- T3: frpc.exe liegt neben dem Agent-Binary (`frpc.exe`, T4 legt sie dort ab); der Pin (`frpcpin.go`) ist der SHA-256 der entpackten frpc.exe aus dem Archiv, dessen Hash die Workflows pinnen (am 2026-11-18 gegen `FRP_SHA256_WINDOWS_AMD64` geprüft). Der Hash wird vor jedem Start und jedem `frpc reload` geprüft; zwischen Prüfung und Start schützt die DACL des Programmordners (T1). Das Kind tritt dem Job erst nach dem Start bei (Go startet nicht suspendiert); frpc startet keine eigenen Kinder. Die letzten 20 Ausgabezeilen gehen beim ungeplanten Ende ins Log, sonst wird die Ausgabe verworfen. Ein Start durch den Sync wartet nicht auf den Backoff. Der Besitz des Admin-Ports wird über `GetExtendedTcpTable` (PID des Kinds auf 127.0.0.1:port, kein fremder Prozess dort) geprüft, wie unter Linux über den Owner.
- T4: Install über den Dienst-Manager (`svc/mgr`) statt `sc.exe`; der Ablauf (lookup, stop, place, create/update, Wiederanlauf/Event-Quelle, Altbinary weg, start) steht plattformneutral in `install_plan.go` und ist mit Fakes getestet, auf Windows gegen den echten SCM (Fake-Dienst im Test-Binary, dreimal: neu, Umzug mit neuerem Binary, Wiederholung). Alle Dateien werden vor dem Stopp gelesen und frpc.exe gegen den Pin geprüft, ein falscher Hash ändert nichts; fehlt frpc.exe neben dem Binary (`frpc-windows-x86_64.exe` oder `frpc.exe`), nur Warnung. Der Stopp wartet auf Stopped und auf das Ende des Prozesses (sonst ist das Binary gesperrt); scheitert das Ablegen oder Umstellen, startet der alte Dienst wieder. Dateien entstehen über `config.WriteFileOwnedByAdministrators` (`.new` mit SDDL `O:BA` beim Anlegen, dann `MoveFileEx`), gleiche Inhalte bleiben liegen, eine kurze Sperre nach dem Stopp wird bis 15 s abgewartet. Beim Umzug fällt nur `adminhelper-agent.exe` im alten Ordner weg. `uninstall` ohne registrierten Dienst ist kein Fehler mehr (damit `--purge` nachgeholt werden kann); `--purge` lehnt Linux/FreeBSD vor jeder Änderung ab, entfernt auf Windows Programm- und Datenordner, beide über `KnownFolderPath` (nie aus der Umgebung des Aufrufers, gesetzte `ADMINHELPER_*_DIR` nur als Hinweis), nur mit Owner Administratoren/SYSTEM, nie relativ, nie eine Laufwerks- oder Freigabewurzel (`purgeable`, ohne Löschen getestet); das laufende Binary und sein Ordner gehen per `MOVEFILE_DELAY_UNTIL_REBOOT`. Neue und umgeschriebene Meldungen englisch. Zwölf Dateien statt acht: Ablauf, Owner-Schreiber, Pin-Export und `--purge` hängen am selben Install-Weg und werden gemeinsam geprüft.
