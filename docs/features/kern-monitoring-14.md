<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-14 — Monitoring-Module für Windows Server, Windows-Rollen und Windows-Backup

Roadmap: R-1245 (Windows Server: AD DS, DHCP, DNS, IIS, Updates, Ereignisse, Zertifikate, RDS), R-1246 (Rollen:
Hyper-V, DFS-R, SQL Server, WSUS, Dateiserver, Druck, Defender), R-1436 (Windows Server Backup, Veeam-Agent für
Windows). Kevin 2026-11-09 diktiert (Monitoring-Konzept §6.8, §6.13, §6.12), vor dem Release 0.47.0.

## Problem / Motivation

- Der Katalog hat kein einziges Windows-Modul. Der Agent läuft unter Windows, misst dort aber nur Host-Metriken und
  einzelne Dienste (`unit`).
- Die Discovery liest Units nur unter Linux (`linuxHost` in `apps/agent/internal/discovery/discovery.go`). Ein
  Windows-Modul würde deshalb nie erkannt, selbst wenn es im Katalog stünde.
- Für AD-Replikation, Hyper-V, Defender usw. fehlen die Lesewege: WMI/CIM-Abfragen, Ereigniszähler, der
  Zertifikatsspeicher, der Update-Agent.

## Ziel & Nicht-Ziele

**Ziel:** Windows-Dienste werden erkannt, und die Module aus Konzept §6.8, §6.13 und die Windows-Zeilen aus §6.12
melden Zustände und Zähler. Es gelten die Leitplanken (Konzept §3.13, Kevin 2026-11-09):

- nur eine Freigabeliste: feste Befehle mit festen Argumenten; WMI/CIM nur Abfragen (`SELECT`), keine
  Methodenaufrufe; das WQL steht im Agent-Code, der Server nennt nur eine Ansicht;
- kein Dienst verliert spürbar Leistung; teure Lesewege (Update-Suche) laufen täglich;
- zum Server gehen nur Zahlen, Booleans und Zustände, keine Namen, keine Ereignistexte, kein `KeyProtector`.

**Nicht-Ziele:**

- `repadmin *`, `dcdiag /c`, `Measure-VM`, WSUS-Sync oder -Cleanup, der Resume-Befehl aus DFS-R-Ereignis 2213:
  nie (Konzept).
- `dcdiag`: die Ausgabe ist lokalisierter Text; die Dienste NTDS, Netlogon, KDC, DFSR und W32Time prüft schon
  `unit`. Gezielte `dcdiag`-Tests bleiben weg.
- SQL Server: SYSTEM hat meist kein Login. Ohne einmalige Freigabe nur Dienst und Ereignisse (Konzept); die
  Abfrage von `msdb` und der Express-Grenze kommt erst mit einer Freigabe-Funktion (eigene Zeile).
- DFS-R-Backlog über fremde Hosts (nur auf Wunsch, Konzept).
- Keine Offline-cab-Suche bei Updates.

## Betroffene Komponenten & Dateien

- **Agent** (`apps/agent/`):
  - `internal/discovery/`: Windows-Dienste als Units (`golang.org/x/sys/windows/svc/mgr`), neue Datei
    `discovery_windows.go`.
  - `internal/probe/`: neue Windows-Dateien für die Bausteine (`wmi_windows.go`: feste Abfragen über
    `github.com/yusufpapurcu/wmi`, heute schon indirekt über gopsutil im Modulgraph; `eventlog_windows.go`:
    Ereigniszähler über `wevtapi.dll` `EvtQuery`/`EvtNext`; `certstore_windows.go`: `LocalMachine\My`) und die
    Ansichten (`host_windows.go`, `app_windows.go`, je mit Test), dazu `sensor_app.go`/`sensor_host.go` für die
    Registrierung.
  - `internal/allowlist/allowlist.go`: `repadmin /showrepl localhost /csv`, `appcmd list site|apppool /xml`.
  - `go.mod`: `yusufpapurcu/wmi` wird direkte Abhängigkeit; `THIRD_PARTY_LICENSES.md`.
- **Monitoring** (`apps/monitoring/app/catalog/`): `sensors.py` (Felder und Ziele der neuen Ansichten), neue
  Module unter `modules/` (je mit Test).
- **Doku:** `docs/admin/monitoring.html` (App-Module), `docs/developer/agent.html` (Sensoren, Discovery),
  `docs/developer/monitoring.html` (Katalog), je DE+EN; `changelog.d/kern-monitoring-14.md`; `THIRD_PARTY_LICENSES.md`.

## Datenmodell / API / Migrationen

- Keine Migration, keine REST-Änderung. Der Discovery-Block trägt unter Windows jetzt Units (Dienstname,
  Zustand); die Feldform bleibt.
- Neue Ansichten der Sensoren `app` und `host`; ein älterer Agent meldet sie `invalid`, der Check steht auf
  `unknown`.

## Ansichten (Agent)

| Ansicht | Sensor, Ziel | Leseweg | Felder (Auszug) |
|---|---|---|---|
| `ad_replication` | app, Unit NTDS | `repadmin /showrepl localhost /csv` (15 min) | Partner, Fehler, Alter der letzten Replikation |
| `dhcp_scopes` | app, Unit DHCPServer | CIM `root/Microsoft/Windows/DHCP` `PS_DhcpServerv4ScopeStatistics` | höchste Auslastung, Scopes über 80/95 % |
| `iis_state` | app, Unit W3SVC | `appcmd list site/apppool /xml` | gestoppte Sites, gestoppte App-Pools |
| `rds_licenses` | app, Unit TermServLicensing | `Win32_TSLicenseKeyPack` | ausgegeben / gesamt, Tage bis Ablauf |
| `win_updates` | host | WUA `Online=false` (täglich), `RebootRequired`, `LastSearchSuccessDate` | offene, sicherheitsrelevante, Neustart nötig, Alter der Suche |
| `win_events` | host | Level 1–2 in System und Application seit dem letzten Lauf | Zahl |
| `win_certs` | host | `LocalMachine\My` | Zahl, kleinste Resttage |
| `hyperv` | app, Unit vmms | `root/virtualization/v2` `Msvm_ComputerSystem`, Heartbeat, Replikation, Checkpoints | VMs nicht gesund, Heartbeat verloren, Replikat kritisch, älteste Checkpoints |
| `dfsr` | app, Unit DFSR | `root/MicrosoftDFS` `DfsrReplicatedFolderInfo`, Ereignisse 2213/4012 | Ordner im Fehler, Ereignisse |
| `storage` | host | `MSFT_VirtualDisk`/`MSFT_PhysicalDisk`, `MSFT_FSRMQuota`, `Win32_ShadowCopy`, `Win32_EncryptableVolume.ProtectionStatus` | ungesunde Disks, Kontingente über 90 %, Alter der jüngsten Schattenkopie, Volumes ohne Schutz |
| `print` | app, Unit Spooler | `Win32_PrintJob`, `Win32_Printer` | hängende Aufträge, Drucker im Fehler |
| `cups_queues` | app, Unit cups (Linux) | `lpstat -p` mit `LC_ALL=C` | deaktivierte Queues |
| `defender` | host | `root/Microsoft/Windows/Defender` `MSFT_MpComputerStatus`, `MSFT_MpThreatDetection` | Echtzeitschutz, Signaturalter, passiver Modus, neue Funde |
| `mssql_events` | app, Unit MSSQL* | Ereignisse Level 1–2 der SQL-Quelle | Zahl |
| `wsus` | app, Unit WsusService | Ereignisse, freier Platz am Inhaltsordner | siehe Offene Fragen |
| `win_backup` | host | Ereignisse `Microsoft-Windows-Backup` 4/5 | Alter des letzten Erfolgs, Fehlschläge |
| `veeam_windows` | app, Unit VeeamEndpointBackupSvc | Ereignis 190 im Log „Veeam Agent“ | Alter des letzten Laufs, Ergebnis über den Level |

Ereignistexte sind lokalisiert; der Agent zählt nur nach Kanal, Quelle, ID und Level und rendert keinen Text.

## Externe Integrationen

- learn.microsoft.com: WQL, `Msvm_*` (Hyper-V WMI v2), `DfsrReplicatedFolderInfo`, `MSFT_MpComputerStatus`,
  Storage-Management-API, `Win32_TSLicenseKeyPack`, `Win32_EncryptableVolume`, Windows Update Agent API
  (`IUpdateSearcher.Online`), `EvtQuery`, `CertOpenStore`, `repadmin /showrepl`, `appcmd`.
- Vor jeder Ansicht die Klasse und ihre Eigenschaften an der Doku prüfen. Was sich nicht belegen lässt, steht
  im Code-Kommentar und im Modul-Docstring als „nicht verifiziert“.

## Trade-offs & Alternativen

- **PowerShell-Cmdlets** (`Get-ADReplicationPartnerMetadata`, `Get-MpComputerStatus`): ein PowerShell-Start kostet
  Sekunden CPU und Speicher je Lauf. Direkte WMI/CIM-Abfragen sind billiger (Konzept §6.13 „ohne PowerShell-Start“).
- **IIS über `root/WebAdministration`:** den Zustand gibt dort nur die Methode `GetState()` her. Methodenaufrufe
  sind ausgeschlossen, darum `appcmd list … /xml`, ein reiner Lesebefehl mit XML-Ausgabe (nicht lokalisiert).
- **Ereignisse mit Cursor vs. Zeitfenster:** Ein Zeitfenster gleich dem Check-Intervall (XPath `timediff`) hält
  den Agent zustandslos; ein Ereignis an der Fenstergrenze kann doppelt oder gar nicht zählen. Für einen
  Warnzähler genügt das.
- **Neue Abhängigkeit:** `yusufpapurcu/wmi` (MIT) ist schon im Modulgraph über gopsutil. Eigenes COM über `go-ole`
  wäre mehr Code für dasselbe.

## Risiken & Rollback

- **Plattform:** Die Go-Suite läuft nativ im CI-Job `agent-windows` (Windows Server ohne Rollen). Die Rollen-
  Klassen (AD DS, Hyper-V, DFS-R, DHCP, RDS, WSUS, FSRM) gibt es dort nicht. Geprüft werden also Bau, Abfragebau,
  das Lesen der Antwort aus Fixtures und eine echte Abfrage gegen `Win32_OperatingSystem` und das System-Log. Auf
  einem echten Windows Server mit den Rollen ist nichts davon gelaufen: „nicht verifiziert“ (Offene Fragen).
- Ein Rollen-Modul, dessen Klasse fehlt, meldet `unsupported`, der Check `unknown`; nichts stürzt ab.
- Rollback: Revert des Merges, keine Daten.

## Doku-Impact

App-Module (neue Windows-Gruppe) und Discovery in `docs/admin/monitoring.html`; Sensoren, Ansichten und Discovery in
`docs/developer/agent.html`; Katalog in `docs/developer/monitoring.html`; je DE+EN; CHANGELOG-Fragment;
`THIRD_PARTY_LICENSES.md`.

## Offene Fragen

1. **Verifikation unter Windows:** Im Pool gibt es keine Windows-Vorlage. Die Rollen-Ansichten sind nur gegen
   Fixtures und die CI-Box geprüft. Empfehlung: so bauen und mergen, den Rest als Prüfzeile vor dem Release führen
   (wie R-0541); Alternative: eine Windows-Server-Vorlage im Pool backen (Kevins Wort).
2. **WSUS:** Die letzte Synchronisation steht nur in der WSUS-Datenbank bzw. der .NET-API, beides kein Leseweg
   nach der Freigabeliste. Empfehlung: Dienst, freier Platz am Inhaltsordner und Ereignisse des Sync-Fehlers;
   „letzte Synchronisation“ fehlt.
3. **`dcdiag`** fällt weg (lokalisierte Ausgabe, Dienste deckt `unit` ab). Empfehlung: so lassen.
