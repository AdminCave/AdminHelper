# Agent: Proxmox-Storage-Abfrage, hängende Netz-Freigaben, Ressourcen-Deckel, Befehls-Freigabeliste — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-6 · Review: pro Task
Spec: docs/features/kern-monitoring-6.md (Roadmap R-1219, R-1220, R-1221, R-1222)
Heavy: linux-full — apps/agent (Collectors, systemd-Unit); die Box-Nachbauten von R-1219/R-1220 laufen als Beweis in T1/T3 auf einer Pool-VM der eigenen Lane
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1220: Netz-Dateisysteme im Unterprozess mit Timeout, hängende Freigabe als Befund  [~] (Befund an Box widerlegt: gopsutil disk.Partitions(false) liefert nur Dateisysteme ohne nodev in /proc/filesystems (nfs, nfs4, cifs, fuse.* sind nodev), collectDisks fragt Netz-Freigaben nie ab. Pool-VM Debian 13, nfs4 hard, Server gestoppt: stat -f hängt über 20 s, collectDisks von main kehrt nach 0 s zurück)
Komponente: agent · Dateien: apps/agent/internal/monitor/collector.go, apps/agent/internal/monitor/collector_test.go, apps/agent/internal/monitor/netfs.go, apps/agent/internal/monitor/netfs_test.go, apps/agent/internal/monitor/report.go, apps/agent/cmd/adminhelper-agent/main.go, apps/agent/cmd/adminhelper-agent/statfs.go, apps/agent/cmd/adminhelper-agent/statfs_test.go
Änderung:
- `collectDisks` fragt Mounts der Netz-Dateisysteme (nfs, nfs4, cifs, smb3, smbfs, fuse.sshfs, glusterfs, ceph) nicht mehr selbst ab. Das übernimmt ein versteckter Unterbefehl `adminhelper-agent statfs <mount>` als Unterprozess, mit 5 s Timeout je Mount.
- Ein Timeout landet mit Mount und fstype in `resources.disks_unresponsive`; der Lauf geht weiter.
- Lokale Dateisysteme bleiben unverändert.
- Neue Dateien bekommen einen SPDX-Header.
- Test: Mit gestubbtem Unterprozess gibt es drei Fälle: ok, Timeout (der Eintrag in `disks_unresponsive`) und Fehler (der Mount fehlt still wie heute). Dazu der Unterbefehl gegen ein lokales Verzeichnis.
- Box-Nachbau vor dem Fix (Pool-VM der eigenen Lane): eigene NFS-Freigabe hart einhängen, den NFS-Server stoppen, `adminhelper-agent run --once` vom Stand `main` hängt bis zum Abbruch. Mit dem Fix endet der Lauf, und `disks_unresponsive` nennt den Mount. Ergebnis in den Commit-Body.
Beweis: Konzept §9 Befund 2 (nfs(5) `hard` ist Standard) · main@4b7b80d9b apps/agent/internal/monitor/collector.go collectDisks
Dedup-Key: bug:agent:collector.go:collectDisks
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/... ./cmd/...
Doku: → T7

### T2 — R-1220: Monitoring warnt bei nicht antwortender Netz-Freigabe  [~] (verworfen mit T1 (R-1220 widerlegt), kein disks_unresponsive im Bericht)
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_agent_resources_checker.py
Änderung:
- `_grade_disks` liest `resources.disks_unresponsive` (über `capped_objects`, `entry_text`) und meldet je Eintrag, der nicht in `ignore_mounts` steht, eine Warnung „Network share <mount> not responding“. Keine Metrik.
- Ohne das Feld (älterer Agent) bleibt alles wie heute.
- Tests: Warnung; Mount auf der Ignorierliste; Feld fehlt; Feld kaputt (kein Array, Einträge ohne mount).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_resources_checker.py
Doku: → T7
Abhängt von: T1

### T3 — R-1219: Storage-Zustand aus /cluster/resources, Backup-Inhalt höchstens alle 30 min  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/plugins.go, apps/agent/internal/monitor/plugins_test.go, apps/agent/internal/monitor/reportstate.go, apps/agent/internal/monitor/reportstate_test.go, apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/report_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @98696a92a 2026-11-09T18:48:07+01:00
Review: approve (.ah-out/review/kern-monitoring-6/T3.verdict.json)
Änderung:
- `buildBackupIndex` liest die Backup-Storages des Nodes aus `pvesh get /cluster/resources --type storage`: `node` gleich dem lokalen Node, `content` enthält `backup`, `status`.
- Ein Storage, der nicht `available` ist, ist `backup_index_incomplete` wie heute; sein Inhalt wird nicht abgefragt.
- Den Inhalt (`/nodes/<n>/storage/<sid>/content --content backup`) fragt der Agent nur, wenn der im Report-State gespeicherte Index älter als 30 min ist. Sonst nimmt er den gespeicherten Index.
- `/nodes/<n>/storage` ruft der Agent nicht mehr auf.
- Vorher die Felder im PVE-API-Viewer nachlesen (WebFetch, Quelle im Commit-Body).
- Tests: Cache frisch ohne Content-Aufruf, Cache alt mit Aufruf, Storage nicht verfügbar, State ohne Index.
- Box-Nachbau: Pool-VM mit Proxmox VE auf Debian und einem NFS-Storage auf eine eigene Freigabe, dann den NFS-Server stoppen. `pvesh get /nodes/<n>/storage` vorher (aktiviert bzw. wartet ~10 s) gegen `/cluster/resources` (sofort). Ergebnis in den Commit-Body. Ist der PVE-Nachbau im Pool nicht machbar: STOPP für den Nachbau und Bericht, nicht für den Fix.
Beweis: Konzept §9 Befund 1 (pve-storage Storage.pm/NFSPlugin.pm/CIFSPlugin.pm, nicht an Box geprüft) · main@4b7b80d9b apps/agent/internal/monitor/plugins.go buildBackupIndex
Dedup-Key: bug:agent:plugins.go:buildBackupIndex
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/...
Doku: → T7

### T4 — R-1221: Ressourcen-Deckel für Unit und Windows-Dienst  [x]
Komponente: agent · Dateien: apps/agent/systemd/adminhelper-agent.service, apps/agent/internal/service/service_linux.go, apps/agent/internal/service/service_linux_test.go, apps/agent/cmd/adminhelper-agent/run_windows.go, apps/agent/cmd/adminhelper-agent/run_windows_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @a83fad335 2026-11-09T18:32:29+01:00
Review: approve (.ah-out/review/kern-monitoring-6/T4.verdict.json)
Änderung:
- Ausgeliefertes und dynamisches Unit bekommen `Nice=19`, `IOSchedulingClass=idle`, `CPUQuota=50%`, `MemoryMax=256M` und `OOMPolicy=continue`.
- Ein Test vergleicht die `[Service]`-Zeilen beider Units, ohne `ExecStart`, damit die Zwillinge nicht auseinanderlaufen.
- Unter Windows setzt `runLoop` beim Start `SetPriorityClass(IDLE_PRIORITY_CLASS)` auf den eigenen Prozess; ein Fehler wird geloggt, der Dienst läuft weiter.
- frpc.service bleibt unberührt.
- Windows-Teil verifiziert über den CI-Job `agent-windows`, Ergebnis im PR.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/service/... ./cmd/...
Doku: → T7

### T5 — R-1222: Freigabeliste für jeden externen Befehl der Collectors  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/allowlist.go, apps/agent/internal/monitor/allowlist_test.go, apps/agent/internal/monitor/plugins.go, apps/agent/internal/monitor/smart.go, apps/agent/internal/monitor/system_linux.go, apps/agent/internal/monitor/services_linux.go, apps/agent/internal/monitor/services_windows.go, apps/agent/internal/monitor/updates_linux.go
Änderung:
- `runTimed`/`runTimedEnv` wandern nach `allowlist.go` und prüfen vor dem Start jeden Aufruf gegen eine feste Liste: Befehl, feste Argumente, und für variable Teile ein Muster (Gerätepfad, Unit-Name, Node, Storage-ID). Ein Aufruf außerhalb der Liste wird nicht gestartet und liefert einen Fehler.
- Tests:
  - AST-Test: Keine andere Nicht-Test-Datei unter `internal/monitor` ruft `exec.Command`/`exec.CommandContext` auf.
  - Tabellentest: Jeder heutige Aufruf (docker, pvesh, zpool, smartctl, systemctl, sc, needs-restarting, timedatectl, apt-get, dnf) besteht.
  - Negativtest: Keine Falle aus Konzept §3.6 besteht, u. a. `postfix check`, `apt-get check`, `zpool scrub`, `pvesh get /nodes/<n>/storage`, `docker exec`.
- Neue Dateien bekommen einen SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/...
Doku: → T7
Abhängt von: T3

### T6 — R-1221: Rücksicht bei Last  [?] (Was lässt der Agent bei hoher Last aus, und wie erfährt der Server davon? Empfehlung: in arch-monitoring-module verschieben)
Komponente: agent · Dateien: apps/agent/internal/monitor/report.go
Änderung: Nach Kevins Antwort.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/...
Doku: → T7

### T7 — Doku: Agent- und Monitoring-Seiten, CHANGELOG  [ ]
Komponente: docs · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-monitoring-6.md
Änderung:
- Ressourcen-Deckel samt Override per `systemctl edit` und dem Hinweis „IO-Klasse idle wirkt je nach IO-Scheduler“.
- Proxmox-Backup-Inhalt alle 30 min.
- Entwicklerseite: neue Collector-Befehle nur über die Freigabeliste.
- DE und EN deckungsgleich, CHANGELOG-Fragment.
Verify: bash scripts/dev/verify.sh docs --strict
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-monitoring-6.md
Task-Review: am Ende

## Entscheidungen
- Kevin 2026-11-09 (Konzept §10): Befunde 1 und 2 werden auf einer Test-VM im Pool nachgestellt; es gibt nur eine Freigabeliste, die Fallen dienen als Prüfliste bzw. Negativtest; der Agent soll für Kunden nie spürbar sein.
- Überschneidung mit `feature/arch-freebsd-agent` in `collector.go`: Der Zug fährt trotzdem. Die Überschneidung ist nur die `skipFSTypes`-Map, T1 fasst sie nicht an, und das Konzept (§8.1) setzt diesen Zug vor die Agent-Arbeit der arch-Sessions. Wer zuerst merged, zwingt den anderen zum Nachziehen; die FreeBSD-Befehle brauchen dann Listeneinträge (T5).
- T1/T2 (R-1220) verworfen, Box-Nachbau 2026-11-09 auf einer Pool-VM der Lane: Netz-Dateisysteme erreichen `collectDisks` nicht (gopsutil `disk.Partitions(false)` filtert `nodev`), der hängende statfs-Pfad existiert nicht. Die Spec-Abschnitte zu R-1220 gelten nicht mehr; ob Netz-Freigaben künftig überwacht werden sollen, ist eine neue Frage an Kevin, kein Teil dieses Zugs.
- T4: `SetPriorityClass(IDLE_PRIORITY_CLASS)` sitzt in `agentService.Execute`, nicht in `runLoop`: unter Windows ist nur `Execute` der Dienstpfad, `runLoop` läuft dort nur interaktiv.
- T4: `CPUQuota=50%` statt der geplanten 25 %. Box-Messung 2026-11-09 (PVE 9.2, 2 vCPU, `systemd-run` mit den Deckeln): ein `pvesh get` braucht 2,3 s CPU, unter 25 % 9,5–10,0 s Wanduhr gegen `pluginTimeout` 15 s, unter 50 % 4,6–4,9 s. `Nice=19` lässt dem Host bei Konkurrenz ohnehin den Vortritt. Speicherspitze eines pvesh-Aufrufs 146 MB, unter `MemoryMax=256M`.
- T4: `OOMPolicy=continue` dazu (Reviewer T4): ohne sie gilt `DefaultOOMPolicy=stop`, und ein Kind über dem Deckel (pvesh, dnf, docker) beendete die ganze Unit samt Push; so endet nur das Kind, der Collector meldet den Fehler.
- T3, Box-Nachbau 2026-11-09 (Pool-VM, PVE 9.2 auf Debian 13, NFS-Storage auf eine eigene Freigabe): `status` in `/cluster/resources` ist laut `PVE::API2Tools::extract_storage_stats` genau dann `available`, wenn pmxcfs einen RRD-Eintrag des Storages hält. Nach dem Stopp des NFS-Servers blieb er 4–5 min `available` (pvestatd meldete ab 10 s „not online“) und wurde dann `unknown`. Ein Ausfall wird damit bis zu 5 min später `backup_index_incomplete` als vorher; in dieser Zeit gilt der gespeicherte Index oder, wenn er fällig ist, scheitert der Content-Aufruf mit „storage … is not online“. Hingenommen: das Backup-Alter wird in Stunden gemessen. Ein deaktivierter Storage fehlt in `/cluster/resources` ganz und wird übergangen. Jeder `pvesh`-Aufruf kostet 2,3–2,8 s (Perl-Start), Liste und Inhalt gleich; den 10-s-Verbindungstest eines toten entfernten Servers konnte der Nachbau nicht zeigen (die Freigabe lag auf demselben Host, die Verbindung wurde sofort abgelehnt).
- T3: Der Report-State und damit der Backup-Index werden nur nach erfolgreichem Push gespeichert (Reviewer-Nit). Ist der Server länger als 30 min weg, liest der Agent den Inhalt in jedem Lauf; hingenommen, gleiches Muster wie `updatesCheck`.
