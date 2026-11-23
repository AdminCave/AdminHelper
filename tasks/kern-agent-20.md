# kern-agent-20 — Task-Ledger
Status: aktiv · Branch: feature/kern-agent-20 · Review: pro Task
Spec: docs/features/kern-agent-20.md (Roadmap R-0688)
Heavy: linux-full — apps/agent (Monitoring-Report); Windows-Dateien prüft der PR-Job agent-windows, FreeBSD nur quer gebaut
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Gilt für T2–T8: die Dateien unter `apps/agent/internal/monitor/testdata/report/` bleiben unverändert (der Vertrag aus
T1); jede Task baut zusätzlich quer `GOOS=windows go vet ./...` und `GOOS=freebsd go vet ./...` in `apps/agent` und
nennt das Ergebnis im Commit-Body.

### T1 — R-0688: Golden-Vertrag des Reports je Block  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/report_golden_test.go, apps/agent/internal/monitor/report_golden_linux_test.go, apps/agent/internal/monitor/report_golden_windows_test.go, apps/agent/internal/monitor/testdata/report/docker_compose.json, apps/agent/internal/monitor/testdata/report/docker.json, apps/agent/internal/monitor/testdata/report/docker_unavailable.json, apps/agent/internal/monitor/testdata/report/host_linux.json, apps/agent/internal/monitor/testdata/report/load_shed_clear.json, apps/agent/internal/monitor/testdata/report/load_shed_over.json, apps/agent/internal/monitor/testdata/report/proxmox.json, apps/agent/internal/monitor/testdata/report/proxmox_unavailable.json, apps/agent/internal/monitor/testdata/report/report_keys_linux.json, apps/agent/internal/monitor/testdata/report/report_shape_linux.json, apps/agent/internal/monitor/testdata/report/resources_disks.json, apps/agent/internal/monitor/testdata/report/resources_network.json, apps/agent/internal/monitor/testdata/report/resources_swap_cpu.json, apps/agent/internal/monitor/testdata/report/services_freebsd.json, apps/agent/internal/monitor/testdata/report/services_linux.json, apps/agent/internal/monitor/testdata/report/services_windows.json, apps/agent/internal/monitor/testdata/report/smart_absent.json, apps/agent/internal/monitor/testdata/report/smart.json, apps/agent/internal/monitor/testdata/report/systemd_failed_logs.json, apps/agent/internal/monitor/testdata/report/systemd_freebsd.json, apps/agent/internal/monitor/testdata/report/systemd_linux.json, apps/agent/internal/monitor/testdata/report/systemd_windows.json, apps/agent/internal/monitor/testdata/report/systemd_windows_sc_failed.json, apps/agent/internal/monitor/testdata/report/system_state_freebsd.json, apps/agent/internal/monitor/testdata/report/system_state_linux.json, apps/agent/internal/monitor/testdata/report/system_state_windows_failed.json, apps/agent/internal/monitor/testdata/report/system_state_windows.json, apps/agent/internal/monitor/testdata/report/top_processes.json, apps/agent/internal/monitor/testdata/report/zfs.json, apps/agent/internal/monitor/testdata/report/zfs_unavailable.json
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @457b96c4f 2026-11-23T12:52:01+01:00
Review: approve (.ah-out/review/kern-agent-20/T1.verdict.json)
Änderung: Neue Tests (SPDX-Header) halten das heutige JSON jedes Blocks in `testdata/report/<block>.json` fest, gebaut über die vorhandenen Seams und Assemble-Funktionen mit festen Eingaben: resources-Teile (Memory/Load/Netzwerk ohne Host-Werte über die reinen Formfunktionen, sonst die Schlüsselmenge), host, processes, self/load_shed, systemd + services (Linux, Windows), system_state je Plattform, docker, proxmox, zfs, smart/smart_absent, service_logs, und die Schlüsselmenge von `buildReportWithState` mit gestubbten Collectoren. Vergleich über dekodiertes JSON (`null`/`[]` und fehlende Schlüssel zählen), Flag `-update` schreibt die Dateien neu. Gegenprobe: ein umbenannter Schlüssel in einem Collector macht den Test rot.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: → T9

### T2 — R-0688: Ressourcen, Host, Prozesse und Self typisiert  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/collector.go, apps/agent/internal/monitor/hostfacts.go, apps/agent/internal/monitor/processes.go, apps/agent/internal/monitor/loadgate.go, apps/agent/internal/monitor/selfmeasure.go, apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/collector_test.go, apps/agent/internal/monitor/loadgate_test.go, apps/agent/internal/monitor/plugins_test.go, apps/agent/internal/monitor/processes_test.go, apps/agent/internal/monitor/report_test.go, apps/agent/internal/monitor/reportstate_test.go, apps/agent/internal/monitor/selfmeasure_test.go, apps/agent/internal/monitor/servicelogs_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @3686dc3e3 2026-11-23T13:06:44+01:00
Review: approve (.ah-out/review/kern-agent-20/T2.verdict.json)
Änderung: `Resources`, `HostFacts`, `TopProcesses`, `LoadShedBlock`, `SelfBlock` als Structs mit `json`-Tags; `collectResources`, `collectHostFacts`, `collectTopProcesses`, `loadShed.block` liefern sie, `loadReadingOf` und `underLoad` lesen Felder statt Schlüssel. Der Report hängt die Structs vorerst noch in seine Map (T8 stellt sie um). Tests lesen Felder.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: → T9

### T3 — R-0688: Dienste typisiert, keine ungeprüfte Type-Assertion  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/services_linux.go, apps/agent/internal/monitor/services_freebsd.go, apps/agent/internal/monitor/services_windows.go, apps/agent/internal/monitor/rcservice.go, apps/agent/internal/monitor/scquery.go, apps/agent/internal/monitor/inventory.go, apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/services_linux_test.go, apps/agent/internal/monitor/allowlist_linux_test.go, apps/agent/internal/monitor/inventory_test.go, apps/agent/internal/monitor/rcservice_test.go, apps/agent/internal/monitor/report_test.go, apps/agent/internal/monitor/scquery_test.go, apps/agent/internal/monitor/servicelogs_linux.go, apps/agent/internal/monitor/servicelogs_linux_test.go, apps/agent/internal/monitor/servicelogs_other.go, apps/agent/internal/monitor/servicelogs_windows.go, apps/agent/internal/monitor/servicelogs_windows_test.go, apps/agent/internal/monitor/services.go, apps/agent/internal/monitor/services_freebsd_test.go, apps/agent/internal/monitor/services_test.go, apps/agent/internal/monitor/winevents.go, apps/agent/internal/monitor/winevents_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @5daf2c1ec 2026-11-23T13:21:58+01:00
Review: approve (.ah-out/review/kern-agent-20/T3.verdict.json)
Änderung: `ServiceHealth` (systemd-Block, mit `Watched`, `LogUnits`, `AllServices []ServiceEntry`, `EnabledInactive []string` …) und `WatchedService` als Structs für alle drei Plattformen; `collectServiceHealth`/`collectWatchedServices`/`assembleServiceHealth` liefern sie. Die Assertions `services_linux.go:61-62,72,85` entfallen, ebenso die Schlüsselzugriffe in `inventory.go:96` (`throttleInventory`) und `report.go` (`failedUnits`, `serviceLogUnits`). Mehr als acht Dateien, weil der Block auf drei Plattformen gleich aussehen muss; die übrigen Testdateien der Plattformen (`services_*_test.go`, `rcservice_test.go`, `scquery_test.go`, `inventory_test.go`) per `set-files`.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: → T9

### T4 — R-0688: Systemzustand, Updates und Paket-Audit typisiert  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/system_linux.go, apps/agent/internal/monitor/system_freebsd.go, apps/agent/internal/monitor/system_windows.go, apps/agent/internal/monitor/system_other.go, apps/agent/internal/monitor/updates.go, apps/agent/internal/monitor/pkgaudit.go, apps/agent/internal/monitor/system_linux_test.go, apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/systemstate.go, apps/agent/internal/monitor/pkgaudit_test.go, apps/agent/internal/monitor/report_golden_linux_test.go, apps/agent/internal/monitor/report_test.go, apps/agent/internal/monitor/system_freebsd_test.go, apps/agent/internal/monitor/system_windows_test.go, apps/agent/internal/monitor/updates_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @ca5c3c105 2026-11-23T13:32:33+01:00
Review: approve (.ah-out/review/kern-agent-20/T4.verdict.json)
Änderung: `SystemState` mit den Unterblöcken (Updates, Reboot, Uhrzeit, Paket-Audit …) als Structs; `collectSystemState` liefert ihn auf allen Plattformen, `reportState` bleibt wie er ist. Plattform-Tests per `set-files`.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: → T9

### T5 — R-0688: Docker-Block typisiert  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/plugins.go, apps/agent/internal/monitor/plugins_test.go, apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/loadgate_test.go, apps/agent/internal/monitor/report_golden_linux_test.go, apps/agent/internal/monitor/report_test.go, apps/agent/internal/monitor/selfmeasure_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @a5ae93d62 2026-11-23T13:42:49+01:00
Review: approve (.ah-out/review/kern-agent-20/T5.verdict.json)
Änderung: `DockerBlock`, `DockerContainer` und die Unavailable-Form als Structs; `collectDocker`, `putDockerDetails`, `dockerUnavailable`, `parseDockerPS` liefern bzw. füllen sie.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: → T9

### T6 — R-0688: Proxmox-Block typisiert  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/plugins.go, apps/agent/internal/monitor/plugins_test.go
Änderung: `ProxmoxBlock` mit Gästen, Cluster und Backup-Details als Structs; `collectProxmox`, `proxmoxUnavailable`, `putBackupDetails` liefern bzw. füllen sie. Die Antworten von `pvesh` (`pveString`, `pveBool`, `vmidList`) bleiben lose, sie sind externe Eingabe.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: → T9

### T7 — R-0688: ZFS und SMART typisiert  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/plugins.go, apps/agent/internal/monitor/plugins_test.go, apps/agent/internal/monitor/smart.go, apps/agent/internal/monitor/smart_test.go, apps/agent/internal/monitor/report.go
Änderung: `ZFSBlock` und `ZPool` als Structs (`collectZFS`, `zfsUnavailable`, `parseZpoolList`, `parseZpoolStatus`); `getFloat` entfällt, wenn kein Leser mehr übrig ist; `smart_absent` als Struct.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: → T9

### T8 — R-0688: `Report` als Struct, `BuildReport` liefert ihn  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/monitor.go, apps/agent/internal/monitor/report_test.go, apps/agent/internal/monitor/reportstate_test.go, apps/agent/internal/monitor/servicelogs_linux.go, apps/agent/internal/monitor/servicelogs_windows.go, apps/agent/internal/monitor/servicelogs_other.go, apps/agent/internal/monitor/plan_test.go
Änderung: `Report` mit `ReportVersion` (4), den Blöcken aus T2–T7, Probes, Credentials, Discovery und Self; `buildReportWithState` und `BuildReport` liefern ihn, `collectServiceLogs` liefert ein Struct, `PushReport` marshalt ihn. Keine `map[string]any` bleibt im Report-Pfad; was übrig bleibt (externe Eingaben), nennt der Commit-Body. Die Schlüsselmenge aus T1 bleibt gleich.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: → T9

### T9 — R-0688: Entwickler-Doku nennt Structs und Vertrag  [ ]
Komponente: scripts · Dateien: docs/developer/agent.html, docs/en/developer/agent.html
Änderung: `agent.html:121` (DE+EN) beschreibt die Report-Structs und den Golden-Vertrag unter `testdata/report/` statt `map[string]any`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/agent.html, docs/en/developer/agent.html
Task-Review: am Ende

## Entscheidungen
- Paket-Split (Collectoren getrennt von Push/Init) aus dem Vorschlag von R-0688 abgeteilt in eine eigene Zeile (Spec, Nicht-Ziele).
