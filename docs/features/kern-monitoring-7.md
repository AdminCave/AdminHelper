<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-7 — Katalog-Module für Speicher, Hardware, USV und den Proxmox-Ausbau

Roadmap: R-1228, R-1229, R-1230 (FEAT, Kevin 2026-11-09, Monitoring-Konzept, vor 0.47.0). Ledger:
`tasks/kern-monitoring-7.md`. Baut auf dem Modul-Katalog (R-1223), dem Fühler `app` (R-1404) und den Ansichten mit
Lesekommandos aus kern-monitoring-10 (`runAppTool`) auf; gebaut wird erst nach dem Merge von kern-monitoring-10
(dieselben Dateien `sensors.py`, `sensor_app.go`, `allowlist.go`).

## Problem / Motivation
Ein Host mit Software-RAID, LVM-Thin, Hardware-RAID-Controller, BMC, USV, Proxmox VE, Proxmox Backup Server oder
Ceph zeigt AdminHelper heute nur Platten-Füllstand, SMART, den ZFS-Poolzustand und den Backup-Stand der Proxmox-Gäste
(`proxmox_backup`, `zfs_health`, Vorlagen `proxmox-host`/`zfs-storage`). Ein degradiertes md-Array, ein volllaufender
Thin-Pool (alle Gäste bekommen I/O-Fehler), eine defekte Platte hinter dem Controller, ein kritischer IPMI-Sensor,
eine USV im Batteriebetrieb ohne laufendes `upsmon`, ein hängender Backup-Scheduler, verlorenes Quorum, ein
fehlgeschlagener PBS-Verify oder `HEALTH_ERR` in Ceph bleiben unbemerkt.

- **R-1228 Speicher und Hardware:** mdadm (sysfs), LVM-Thin (Daten/Metadaten %, Zustand, Timeout = „LVM beschäftigt“),
  Hardware-RAID (storcli/storcli2/perccli nur mit `nolog`, ssacli; hostweit nacheinander), IPMI lokal (`ipmitool` mit
  SDR-Cache, nur wenn `/dev/ipmi*` existiert, kein Redfish).
- **R-1229 USV:** NUT (`upsc` ohne Zugang: OB/LB/FSD/OVER, Laufzeit, Ladung, Data stale, läuft `upsmon`?) und
  apcupsd (`apcaccess`).
- **R-1230 Proxmox-Ausbau:** Job-Ergebnis und hängender Scheduler, Replikation, Quorum/HA, Updates (GET `apt/update`),
  Abo; PBS (GC/Verify/Sync/Prune, Datastore mit `estimated-full-date`, Wartungsmodus); ZFS Scrub-Alter, vdev-Fehler,
  Snapshot-Frische; Ceph health/df.

Leitplanken wie in kern-monitoring-10 (Konzept §3.6, §3.8, §3.13; Kevin 2026-11-09): kein Dienst verliert spürbar
Leistung; der Agent fragt nur seinen eigenen Host; ein Programm startet er nur aus der Freigabeliste mit festen
Argumenten; zum Server gehen nur Zahlen, Wahrheitswerte und Zustände, nie Namen von Gästen, Platten, Seriennummern,
Pfade oder Konfigurationsinhalte. Nie: `zpool scrub`, `echo check > sync_action`, `storcli … start learn`/`delete
events`/ohne `nolog`, `ipmitool sel clear`, Treiber laden, `upsmon -c fsd`, `upscmd`, `upsrw`, `pvesh … POST`
(`apt/update` nur GET), `pvesh get /nodes/<n>/storage` (aktiviert jeden Storage, Konzept §9 Befund 1), `targetcli`,
`dmsetup` ohne `--noflush`.

## Bestand (bleibt, wird nicht doppelt gebaut)
- vzdump-Fehler je Gast, Gäste ohne Backup-Job und veraltete Backups liest heute schon der Collector
  (`apps/agent/internal/monitor/plugins.go` `buildBackupIndex`, `readBackupJobs`, `readBackupErrors`) und bewertet der
  Check `proxmox_backup` (`apps/monitoring/app/checkers/plugins.py` `ProxmoxBackupChecker`). Storage liest er schon über
  `/cluster/resources --type storage` (Befund 1 erledigt).
- `zpool status -j` liefert schon Scrub-Zustand, Scrub-Ende und vdev-Zähler (`zpoolDetails`); `ZfsHealthChecker`
  zeigt sie nur an, bewertet sie aber nicht. Dieser Zug bewertet sie (T9).

## Ziel & Nicht-Ziele
**Ziel:** je Bereich ein Katalog-Modul unter `apps/monitoring/app/catalog/modules/` und, wo nötig, eine Ansicht.

**Neuer Fühler `host`** (Empfehlung, siehe Trade-offs): mdadm, LVM-Thin, Controller und BMC gehören zu keiner Unit
und keinem Container. Wie der Fühler `opnsense` nimmt `host` kein Ziel, nur `view`; erkannt wird das Modul über
Marker (`detect.markers`, ein Pfad oder Paket), die Instanz heißt nach dem Modul (`discovery._instances`, wie OPNsense).
Ansichten an Units (NUT, apcupsd, PVE, PBS, Ceph) bleiben beim Fühler `app`.

Ansichten (Entwurf; Formate, Pfade und Felder belegt jede Agent-Task an der offiziellen Doku bzw. am Quelltext und
nennt die Quelle im Kommentar; Unbelegtes fährt nicht mit oder steht als „nicht verifiziert“ in der Task):

| Fühler/Ansicht | Quelle (lesend) | Felder (Entwurf) |
|---|---|---|
| `host`/`mdadm` | `/sys/block/md*/md/{array_state,degraded,raid_disks,sync_action,mismatch_cnt}`, `md/dev-*/state` | `arrays`, `degraded`, `faulty_devices`, `resyncing`, `mismatch_cnt` |
| `host`/`lvm_thin` | `lvs --reportformat json --units b -o lv_attr,data_percent,metadata_percent --select segtype=thin-pool` (Timeout 15 s) | `pools`, `max_data_pct`, `max_meta_pct`, `failed` (Attr D/F/M), `busy` |
| `host`/`raid_ctrl` | `storcli`/`storcli2`/`perccli` `/call show all J nolog`, `ssacli ctrl all show status`; hostweit nacheinander (Mutex) | `controllers`, `vd_not_optimal`, `pd_failed`, `bbu_bad` |
| `host`/`ipmi_sensors` | `ipmitool -S <cache> sdr elist` (Cache einmal je Agent-Start mit `sdr dump` im Agent-Zustandsverzeichnis), nur wenn `/dev/ipmi0`, `/dev/ipmi/0` oder `/dev/ipmidev/0` existiert | `sensors`, `critical`, `noncritical` |
| `app`/`nut_ups` | `upsc -l localhost`, `upsc <ups>@localhost` (nur `ups.status`, `battery.runtime`, `battery.charge`) | `ups`, `on_battery`, `low_battery`, `fsd`, `overload`, `replace_battery`, `stale`, `min_runtime_s`, `min_charge_pct` |
| `app`/`apcupsd` | `apcaccess -u status` (nur `STATUS`, `BCHARGE`, `TIMELEFT`, `NUMXFERS`) | `online`, `on_battery`, `low_battery`, `commlost`, `charge_pct`, `runtime_s`, `transfers` |
| `app`/`pve_cluster` | `pvesh get /cluster/status`, `/cluster/ha/status/current`, `/cluster/replication`, `/nodes/<n>/replication` | `quorate`, `nodes_offline`, `ha_error`, `replication_failed` |
| `app`/`pve_jobs` | `pvesh get /cluster/backup`, `/nodes/<n>/tasks --typefilter vzdump --limit 50` (nur Status/Endzeit) | `jobs`, `last_run_age_s`, `jobs_failed` |
| `app`/`pve_updates` | `pvesh get /nodes/<n>/apt/update` (GET, liest die vorhandene Liste, kein Refresh), `/nodes/<n>/subscription` (nur `status`) | `updates`, `subscription_active` |
| `app`/`pbs_status` | `proxmox-backup-manager` bzw. `proxmox-backup-debug api get` auf `/admin/datastore`, `/status/datastore-usage` (nur Füllstand, `estimated-full-date`), `/nodes/localhost/tasks?errors=1` (nur Typ/Status) | `datastores`, `max_used_pct`, `min_full_days`, `maintenance`, `tasks_failed` (GC/Verify/Sync/Prune) |
| `app`/`ceph_health` | `ceph health -f json`, `ceph df -f json` (nur Zähler, Status, `percent_used`) | `health`, `checks`, `max_pool_used_pct`, `raw_used_pct` |
| `app`/`zfs_snapshots` | `sanoid --monitor-snapshots` (nur wenn installiert; Exit-Code und Status-Zeile) | `status` |

Module (Erkennung; Instanz):

| Zeile | Modul | Erkennung | Checks (Entwurf) |
|---|---|---|---|
| R-1228 | `mdadm` | Marker `/proc/mdstat` mit Paket `mdadm` | `host`/`mdadm`: `degraded gt 0` oder `faulty_devices gt 0` → critical |
| R-1228 | `lvm-thin` | Paket `lvm2`, Marker `/usr/sbin/lvs` | `host`/`lvm_thin`: Daten 80/90 %, Metadaten 70/80 %, `failed gt 0` → critical, `busy` → warning |
| R-1228 | `hwraid` | Marker `/opt/MegaRAID/storcli/storcli64`, `/usr/sbin/storcli2`, `/opt/dell/srvadmin/bin/perccli64`, `/usr/sbin/ssacli` (in T2 belegt) | `host`/`raid_ctrl` (15 min): `vd_not_optimal`/`pd_failed gt 0` → critical, `bbu_bad gt 0` → warning |
| R-1228 | `ipmi` | Marker `/dev/ipmi0` bzw. `/dev/ipmi/0` (+ `ipmitool`) | `host`/`ipmi_sensors` (10 min): `critical gt 0` → critical, `noncritical gt 0` → warning |
| R-1229 | `nut` | Units `nut-server.service`, `nut-monitor.service` | Unit `nut-monitor` aktiv (sonst critical: bei leerem Akku fährt nichts herunter); `nut_ups`: LB/FSD/OVER → critical, OB/RB → warning, `stale gt 0` → critical, Laufzeit < 600 s → warning |
| R-1229 | `apcupsd` | Unit `apcupsd.service` | `apcupsd`: COMMLOST/LOWBATT → critical, ONBATT → warning |
| R-1230 | `proxmox-ve` | Marker `/etc/pve/.version`, Unit `pvedaemon.service` | Unit `pvescheduler`; `pve_cluster` (5 min); `pve_jobs` (15 min, `last_run_age_s` > Plan + Puffer → warning); `pve_updates` (täglich, Info/Warning) |
| R-1230 | `proxmox-backup` | Unit `proxmox-backup-proxy.service`, Marker `/etc/proxmox-backup` | `pbs_status` (15 min): `tasks_failed gt 0` → critical, `max_used_pct` 80/90 %, `min_full_days lt 30` → warning, `maintenance` → warning |
| R-1230 | `ceph` | Units `ceph-mon@*`/`ceph-osd@*` | `ceph_health` (5 min): `HEALTH_ERR` → critical, `HEALTH_WARN` → warning, Pools 75/85 % |
| R-1230 | ZFS | bestehender `zfs_health` | Scrub älter als 35 Tage → warning, 60 Tage → critical; vdev-Zähler > 0 → warning; `zfs_snapshots` als eigenes Modul `sanoid` |

**Nicht-Ziele (YAGNI):**
- Kein Redfish (Konzept §10 Nr. 11: nur IPMI lokal), keine SEL-Auswertung (`sel elist` belastet kipmid; eigene Zeile,
  falls gewünscht), keine LVM-Überbuchung, kein Autoextend-Hinweis, kein mdadm `mismatch_cnt`-Alarm (nur Feld).
- Kein NUT-Selbsttest-Ergebnis, kein `upsc` gegen fremde Hosts, keine NUT-Zugangsdaten.
- PBS: kein Verify je Snapshot, keine Gruppen-Frische (teure Auflistungen, Konzept §6.4: höchstens täglich; eigene
  Zeile).
- Ceph: kein eigener Ceph-Nutzer `mon 'allow r'` (der Agent legt nichts auf dem Kunden-System an); er liest mit dem
  vorhandenen Admin-Keyring von root nur `health`/`df` (siehe Trade-offs).
- Keine Änderung an Web- oder Desktop-UI, keine neue Route, keine Migration.

## Betroffene Komponenten & Dateien
| Komponente | Dateien |
|---|---|
| Agent | neu `apps/agent/internal/probe/sensor_host.go` (Fühler `host`, Ansichten), `host_storage.go` (mdadm, LVM-Thin), `host_hw.go` (Controller, IPMI), je `_linux.go`/`_other.go` falls nötig und `_test.go`; `apps/agent/internal/probe/sensor_app.go` (`appViews`), neu `app_ups.go` (NUT, apcupsd), `app_pve.go` (PVE), `app_pbs.go` (PBS, Ceph, sanoid) mit Tests; `apps/agent/internal/allowlist/allowlist.go` (`commands`, Klassen `ups`, Fallen-Negativtests in `allowlist_test.go`) |
| Monitoring-Katalog | `apps/monitoring/app/catalog/sensors.py` (`SENSORS`, `HOST_VIEW_FIELDS`, `HostParams`, `APP_VIEW_FIELDS`, `APP_VIEW_TARGETS`, `AppParams`), `apps/monitoring/app/catalog/model.py` nur falls der Marker mehr braucht; neu je Modul `apps/monitoring/app/catalog/modules/<id>.py` (SPDX-Header) |
| Monitoring-Bewertung | `apps/monitoring/app/checkers/plugins.py` (`ZfsHealthChecker`: Scrub-Alter, vdev-Zähler) |
| Monitoring-Tests | `apps/monitoring/tests/test_catalog_sensors.py`, neu `tests/test_catalog_storage.py`, `tests/test_catalog_ups.py`, `tests/test_catalog_proxmox.py`; `tests/test_plugin_checkers.py` (ZFS) |
| Doku | `docs/admin/monitoring.html` (App-Module, Fühler `host`, „Nie aufgerufen“), `docs/developer/agent.html` (Freigabeliste, Fühler), `docs/developer/monitoring.html` (Fühler-Liste), je EN; `changelog.d/kern-monitoring-7.md` |

## Datenmodell / API / Migrationen
Keine Migration, keine neue Route. Neu sind der Fühlername `host` (Katalog `SENSORS`, Agent `sensors`) und Werte von
`view`. Ein älterer Agent kennt sie nicht und meldet die Checks `unknown`, bis er aktualisiert ist (wie
kern-monitoring-10). Die Bewertung von `zfs_health` ändert sich ohne Änderung der Vorlage (keine Template-Hash-Drift):
bestehende Installationen sehen nach dem Update neue Warnungen für alte Scrubs und vdev-Fehler.

## Externe Integrationen
Je Ansicht die offizielle Doku bzw. der Quelltext, in der Task per WebFetch gelesen, Link im Kommentar: Linux
`Documentation/admin-guide/md.rst` (sysfs), `lvs(8)`/`lvmreport(7)`, Broadcom StorCLI-Referenz (`J`, `nolog`),
Dell PERC CLI, HPE `ssacli`, `ipmitool(1)` (`sdr dump`, `-S`, `sdr elist`), NUT `upsc(8)` und `ups.status`-Flags
(NUT Developer Guide), apcupsd-Handbuch (`apcaccess`, `STATUS`), PVE API-Viewer (`/cluster/status`,
`/cluster/ha/status/current`, `/cluster/replication`, `/nodes/{node}/apt/update`, `/nodes/{node}/subscription`), PBS
API-Viewer (`/status/datastore-usage`, `/admin/datastore`, Tasks), Ceph `ceph health`/`ceph df` JSON, sanoid
`--monitor-snapshots`. **Bis zur Task ist alles davon nicht verifiziert.** Hardware fehlt im Pool: Controller- und
IPMI-Parser laufen gegen Beispielausgaben aus der Hersteller-Doku, an echter Hardware ungeprüft.

## Trade-offs & Alternativen
- **Fühler `host` ohne Ziel** (Empfehlung) statt Bindung an eine Unit: `mdmonitor.service`, `lvm2-monitor.service`
  sind Oneshots oder fehlen, für Controller und BMC gibt es keine. `opnsense` zeigt das Muster (Marker, Instanz nach
  dem Modul, Fühler ohne Ziel). Alternative: Instanzart `host` im Modell — größer (Modell, Discovery, UI), ohne
  Mehrwert.
- **Lesekommandos statt eigener Parser für Binärschnittstellen:** `lvs`, `storcli`, `ipmitool`, `upsc`, `pvesh`,
  `ceph` sprechen ioctl, IPMI-KCS, das NUT-Netzprotokoll oder Perl-APIs; die Freigabeliste ist dafür gebaut. mdadm
  liest sysfs direkt (Mikrosekunden, kein Prozess).
- **pvesh-Aufrufe bündeln:** jeder Aufruf startet Perl (~0,3–0,5 s CPU). Takte 5/15 min und täglich, je Ansicht
  höchstens vier Aufrufe; `pve_updates` täglich.
- **Ceph mit dem Admin-Keyring von root** statt eigenem Nutzer: der Agent legt keine Nutzer an; `health`/`df` lesen
  nur. Wer das nicht will, deaktiviert den Check. Abweichung vom Konzept §6.11 („eigener Nutzer“), am Gate genannt.
- **ZFS-Bewertung im bestehenden Checker** statt neuem Modul: die Daten kommen schon; ein zweites Modul hieße doppelte
  Checks auf denselben Pools.

## Risiken & Rollback
- Controller-CLIs ohne `nolog` schreiben Logdateien, `storcli` ohne Mutex kann sich mit einem Admin-Aufruf überlagern:
  Freigabeliste nur mit `nolog`, ein Prozess-Mutex im Agent, Negativtest.
- `lvs` hängt bei suspendierten Geräten: Timeout 15 s → Feld `busy`, nie ein zweiter Aufruf im selben Lauf.
- `ipmitool sdr dump` schreibt die Cache-Datei ins Zustandsverzeichnis des Agents (nie anderswohin); ohne Gerät kein
  Aufruf (kein Laden von `ipmi_si`).
- Parser an Beispielausgaben: falsche Felder melden `unknown`, nie `ok`.
- Rollback: Revert der Task-Commits; Module verschwinden aus dem Katalog, übernommene Instanzen melden `unknown`.

## Doku-Impact
`docs/admin/monitoring.html` DE+EN: Abschnitt App-Module um Speicher/Hardware, USV und Proxmox/PBS/Ceph, der Fühler
`host`, die Liste „Nie aufgerufen“, die neue ZFS-Bewertung. `docs/developer/agent.html` und `monitoring.html` DE+EN:
Freigabeliste und Fühler. `changelog.d/kern-monitoring-7.md`.

## Offene Fragen
Keine aus Kevins Bereich: Umfang und Verhalten diktiert (Konzept, Zeilen). Selbst entschieden, am Gate genannt:
Fühler `host`; Ceph ohne eigenen Nutzer; ZFS-Bewertung ohne Vorlagenänderung; SEL und PBS-Snapshot-Verify nicht in
diesem Zug.
