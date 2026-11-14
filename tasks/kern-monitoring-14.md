<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Module Windows Server, Windows-Rollen und Windows-Backup — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-14 · Review: pro Task
Spec: docs/features/kern-monitoring-14.md (Roadmap R-1245, R-1246, R-1436)
Heavy: linux-full — Discovery und neue Ansichten im Agent (`apps/agent`); Windows über den CI-Job `agent-windows` (keine Windows-Vorlage im Pool), kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Gebaut wird erst nach den Merges von kern-monitoring-8 und kern-monitoring-30 (`sensor_app.go`, `sensors.py`,
`allowlist.go`); vor T1 `origin/main` in den Branch mergen. Windows-Code prüft lokal `GOOS=windows go vet` und
`go test -c`; laufen lässt ihn nur der CI-Job `agent-windows`. Das Ergebnis steht im Commit-Body.

### T1 — R-1245: Discovery liest die Windows-Dienste  [x]
Komponente: agent · Dateien: apps/agent/internal/discovery/discovery.go, apps/agent/internal/discovery/discovery_windows.go, apps/agent/internal/discovery/discovery_other.go, apps/agent/internal/discovery/discovery_test.go, apps/agent/internal/discovery/discovery_windows_test.go, apps/agent/internal/discovery/discovery_linux.go, apps/agent/internal/probe/sensor_local_windows.go, apps/agent/internal/probe/sensor_local_windows_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @8a6a5cebf 2026-11-14T11:10:47+01:00
Review: approve (.ah-out/review/kern-monitoring-14/T1.verdict.json)
Änderung: Unter Windows listet `collectUnits` die Dienste über den Dienst-Manager (`svc/mgr`, nur lesend): Name
und Zustand, gekürzt auf die Grenzen des Vertrags. Neue Dateien `discovery_windows.go` und
`discovery_windows_test.go` (SPDX-Header, Build-Tag `windows`).
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/discovery/
Doku: → T9

### T2 — R-1245: Lesebausteine WMI, Ereignisse, Zertifikatsspeicher  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/wmi_windows.go, apps/agent/internal/probe/eventlog_windows.go, apps/agent/internal/probe/certstore_windows.go, apps/agent/internal/probe/winread_windows_test.go, apps/agent/go.mod, apps/agent/go.sum, THIRD_PARTY_LICENSES.md, apps/agent/internal/probe/winread.go, apps/agent/internal/probe/winread_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @c3d678a1d 2026-11-14T11:25:47+01:00
Review: approve (.ah-out/review/kern-monitoring-14/T2.verdict.json)
Änderung: `wmiQuery` nimmt nur Abfragen aus einer festen Tabelle (Namensraum, Klasse, Eigenschaften); kein WQL von
außen, keine Methoden. `countEvents` zählt über `EvtQuery`/`EvtNext` nach Kanal, Quelle, IDs, Level und Zeitfenster,
ohne Text zu rendern. `certStore` liest `LocalMachine\My`. Tests: echte Abfrage gegen `Win32_OperatingSystem`
und das System-Log (CI `agent-windows`), Abfragebau als Tabellentest. `yusufpapurcu/wmi` wird direkt; neue
Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T9
Abhängt von: T1

### T3 — R-1245: Ansichten AD DS, DHCP, IIS, RDS, Updates, Ereignisse, Zertifikate  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/winviews.go, apps/agent/internal/probe/winviews_windows.go, apps/agent/internal/probe/winviews_other.go, apps/agent/internal/probe/winviews_test.go, apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/sensor_host.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @259874fea 2026-11-14T11:59:34+01:00
Review: approve (.ah-out/review/kern-monitoring-14/T3.verdict.json)
Änderung: Ansichten `ad_replication` (`repadmin /showrepl localhost /csv`), `dhcp_scopes`, `iis_state`
(`appcmd list site|apppool /xml`), `rds_licenses`, `win_updates` (WUA `Online=false`), `win_events`, `win_certs`;
nur Zahlen und Zustände. Die Parser werden mit Fixtures getestet. Neue Dateien mit SPDX-Header. Acht Dateien, weil
Registrierung und Freigabeliste zur Ansicht gehören.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/ ./internal/allowlist/
Doku: → T9
Abhängt von: T2

### T4 — R-1246: Ansichten Hyper-V, DFS-R, Speicher, Druck, Defender, SQL Server, WSUS  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/app_windows.go, apps/agent/internal/probe/host_windows.go, apps/agent/internal/probe/app_windows_test.go, apps/agent/internal/probe/host_windows_test.go, apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/sensor_host.go, apps/agent/internal/probe/app_cups.go, apps/agent/internal/probe/app_cups_test.go, apps/agent/internal/allowlist/allowlist.go
Änderung: Ansichten `hyperv`, `dfsr`, `storage` (ohne `KeyProtector`), `print`, `defender`, `mssql_events`, `wsus`
(Spec, Offene Frage 2: ohne letzte Synchronisation) und `cups_queues` (Linux, `lpstat -p` mit `LC_ALL=C`).
Parser mit Fixtures. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/ ./internal/allowlist/
Doku: → T9
Abhängt von: T3

### T5 — R-1436: Ansichten Windows Server Backup und Veeam-Agent für Windows  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/app_windows.go, apps/agent/internal/probe/host_windows.go, apps/agent/internal/probe/app_windows_test.go, apps/agent/internal/probe/host_windows_test.go, apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/sensor_host.go
Änderung: `win_backup` (Ereignisse `Microsoft-Windows-Backup` 4/5: Alter des letzten Erfolgs, Fehlschläge) und
`veeam_windows` (Ereignis 190 im Log „Veeam Agent“, Ergebnis über den Level). Ereignis-IDs als „nicht
verifiziert“ markiert, wo die Doku sie für aktuelle Versionen nicht belegt.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T9
Abhängt von: T2

### T6 — Katalog: Felder und Ziele der Windows-Ansichten  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/tests/test_catalog_sensors.py
Änderung: `APP_VIEW_FIELDS`/`APP_VIEW_TARGETS` und `HOST_VIEW_FIELDS` um die Ansichten aus T3–T5, gleich wie im
Agent.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_sensors.py
Doku: → T9
Abhängt von: T3, T4, T5

### T7 — R-1245: Module Windows Server  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/windows_host.py, apps/monitoring/app/catalog/modules/windows_ad.py, apps/monitoring/app/catalog/modules/windows_dhcp.py, apps/monitoring/app/catalog/modules/windows_dns.py, apps/monitoring/app/catalog/modules/windows_iis.py, apps/monitoring/app/catalog/modules/windows_rds.py, apps/monitoring/tests/test_catalog_windows_server.py
Änderung: Module nach Konzept §6.8 mit Erkennung über die Dienstnamen; Schwellen: Replikation > 12 h critical,
Scopes 80/95 %, gestoppte Sites/Pools, Updates (Neustart nötig, Suche älter als 3 Tage), Zertifikate relativ wie
`tls`, Ereignisse als Warnzähler. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_windows_server.py
Doku: → T9
Abhängt von: T6

### T8 — R-1246, R-1436: Module Windows-Rollen und Windows-Backup  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/hyperv.py, apps/monitoring/app/catalog/modules/dfsr.py, apps/monitoring/app/catalog/modules/mssql.py, apps/monitoring/app/catalog/modules/wsus.py, apps/monitoring/app/catalog/modules/windows_fileserver.py, apps/monitoring/app/catalog/modules/print_server.py, apps/monitoring/app/catalog/modules/defender.py, apps/monitoring/app/catalog/modules/windows_backup.py, apps/monitoring/app/catalog/modules/veeam_windows.py, apps/monitoring/tests/test_catalog_windows_roles.py
Änderung: Module nach Konzept §6.13 und §6.12 (Schwellen von dort; Spooler auf einem DC aus ist richtig; Defender
im passiven Modus neben einem Fremd-AV ist ein Befund). Zehn Dateien, weil jedes Modul eine kleine eigene Datei ist
und ein gemeinsamer Test sie prüft. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_windows_roles.py
Doku: → T9
Abhängt von: T6

### T9 — Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-14.md
Änderung: Windows-Gruppe der App-Module, Discovery unter Windows, Ansichten und Lesewege, Katalog;
`changelog.d/kern-monitoring-14.md` unter `### Added`, ohne Umlaute, mit dem Hinweis „nicht verifiziert auf einem
Windows Server mit den Rollen“.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die genannten Dateien
Task-Review: am Ende
Abhängt von: T7, T8

## Entscheidungen
- Kevin 2026-11-14: Offene Fragen 1–3 wie empfohlen: ohne Windows-Vorlage bauen und mergen, Prüfung vor dem Release als eigene Zeile; WSUS ohne „letzte Synchronisation“; `dcdiag` entfällt.
