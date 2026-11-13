<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Module Speicher, Hardware, USV und Proxmox-Ausbau — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-7 · Review: pro Task
Spec: docs/features/kern-monitoring-7.md (Roadmap R-1228, R-1229, R-1230)
Heavy: linux-full — neuer Fühler, Agent-Ansichten und Freigabeliste (`apps/agent`), kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Gebaut wird erst nach dem Merge von kern-monitoring-10 (dieselben Dateien); vor T1 `origin/main` in den Branch mergen.

### T1 — R-1228: Fühler host mit den Ansichten mdadm und lvm_thin  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_host.go, apps/agent/internal/probe/host_storage.go, apps/agent/internal/probe/host_storage_test.go, apps/agent/internal/probe/sensor_host_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go, docs/features/kern-monitoring-7.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @b3ef7df82 2026-11-13T17:02:44+01:00
Review: approve (.ah-out/review/kern-monitoring-7/T1.verdict.json)
Änderung: Fühler `host` ohne Ziel (Muster `opnsense`: nur `view`); `mdadm` liest sysfs (`md.rst`), `lvm_thin` startet
`lvs` mit festen Argumenten über die Freigabeliste, Timeout 15 s → `busy`. Nur Zähler und Prozente, keine Namen.
Fallen (`mdadm --action`, `dmsetup` ohne `--noflush`, `lvchange`) als Negativtest. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T10

### T2 — R-1228: Ansichten raid_ctrl und ipmi_sensors  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_host.go, apps/agent/internal/probe/host_hw.go, apps/agent/internal/probe/host_hw_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go, docs/features/kern-monitoring-7.md, apps/agent/internal/probe/host_storage.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @7a10f9c3e 2026-11-13T17:24:47+01:00
Review: approve (.ah-out/review/kern-monitoring-7/T2.verdict.json)
Änderung: Controller-CLIs nur mit `J nolog` bzw. `ssacli … show status`, hostweit nacheinander (Mutex); IPMI nur bei
vorhandenem Gerät, SDR-Cache einmal je Agent-Start im Zustandsverzeichnis, dann `-S <cache> sdr elist`. Parser gegen
Beispielausgaben der Hersteller-Doku (Quelle im Kommentar, an Hardware ungeprüft). Fallen (`start learn`, `delete
events`, `sel clear`, `sel elist`) als Negativtest. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T10

### T3 — R-1228: Katalog-Fühler host und Module mdadm, lvm-thin, hwraid, ipmi  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/mdadm.py, apps/monitoring/app/catalog/modules/lvm_thin.py, apps/monitoring/app/catalog/modules/hwraid.py, apps/monitoring/app/catalog/modules/ipmi.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/tests/test_catalog_storage.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @908f51f77 2026-11-13T17:31:48+01:00
Review: approve (.ah-out/review/kern-monitoring-7/T3.verdict.json)
Änderung: `host` in `SENSORS` ohne Ziel, `HOST_VIEW_FIELDS`, `HostParams`; vier Module mit Markern, Regeln und Karten
nach der Spec; Tests für Schema, Felder und Regeln. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_sensors.py tests/test_catalog_storage.py
Doku: → T10
Abhängt von: T1, T2

### T4 — R-1229: Ansichten nut_ups und apcupsd  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_ups.go, apps/agent/internal/probe/app_ups_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @003e440cb 2026-11-13T17:42:13+01:00
Review: approve (.ah-out/review/kern-monitoring-7/T4.verdict.json)
Änderung: `upsc -l localhost` und `upsc <ups>@localhost` (UPS-Name als Argumentklasse), nur `ups.status`,
`battery.runtime`, `battery.charge`; `apcaccess -u status`, nur vier Schlüssel. Fallen (`upscmd`, `upsrw`, `upsmon -c`)
als Negativtest. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T10

### T5 — R-1229: Module nut und apcupsd  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/nut.py, apps/monitoring/app/catalog/modules/apcupsd.py, apps/monitoring/tests/test_catalog_ups.py, apps/monitoring/app/catalog/modules/nut_monitor.py, apps/monitoring/tests/test_catalog_sensors.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @bff0ad704 2026-11-13T17:45:30+01:00
Review: approve (.ah-out/review/kern-monitoring-7/T5.verdict.json)
Änderung: Module mit Units, Regeln (LB/FSD/OVER/stale → critical, OB/RB → warning, Laufzeit < 600 s → warning;
`nut-monitor` nicht aktiv → critical) und Karten. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_ups.py tests/test_catalog_sensors.py
Doku: → T10
Abhängt von: T4

### T6 — R-1230: Ansichten pve_cluster, pve_jobs, pve_updates  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_pve.go, apps/agent/internal/probe/app_pve_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @e98345d7b 2026-11-13T17:56:34+01:00
Review: approve (.ah-out/review/kern-monitoring-7/T6.verdict.json)
Änderung: feste `pvesh get`-Pfade (Spec), höchstens vier Aufrufe je Ansicht, `apt/update` nur GET; nur Zähler,
Zustände und Alter, keine Gast- oder Knotennamen. Fallen (`pvesh create|set|delete`, `/nodes/<n>/storage`) als
Negativtest. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T10

### T7 — R-1230: Ansichten pbs_status, ceph_health, zfs_snapshots  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_pbs.go, apps/agent/internal/probe/app_pbs_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @5380314f6 2026-11-13T18:09:31+01:00
Review: approve (.ah-out/review/kern-monitoring-7/T7.verdict.json)
Änderung: PBS über die lokale API-CLI (Pfade an der PBS-Doku belegt), Ceph `health`/`df` als JSON, sanoid
`--monitor-snapshots` nur wenn installiert. Fallen (`ceph … set`, `proxmox-backup-manager … update`, `sanoid --cron`)
als Negativtest. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T10

### T8 — R-1230: Module proxmox-ve, proxmox-backup, ceph, sanoid  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/proxmox_ve.py, apps/monitoring/app/catalog/modules/proxmox_backup.py, apps/monitoring/app/catalog/modules/ceph.py, apps/monitoring/app/catalog/modules/sanoid.py, apps/monitoring/tests/test_catalog_proxmox.py
Änderung: Module mit Units/Markern, Takten (5/15 min, täglich), Regeln und Karten nach der Spec. Neue Dateien mit
SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_proxmox.py tests/test_catalog_sensors.py
Doku: → T10
Abhängt von: T6, T7

### T9 — R-1230: zfs_health bewertet Scrub-Alter und vdev-Fehler  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/plugins.py, apps/monitoring/tests/test_plugin_checkers.py
Änderung: Scrub-Ende älter als 35 Tage → warning, 60 Tage → critical (Pools ohne Scrub-Angabe unbewertet, ein
laufender Scrub/Resilver nicht); vdev-Zähler > 0 → warning. Ohne Änderung der Vorlage `zfs-storage`. Test zuerst.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_plugin_checkers.py
Doku: → T10

### T10 — Doku Speicher, Hardware, USV, Proxmox  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-7.md
Änderung: Modul-Tabellen, Fühler `host`, „Nie aufgerufen“, ZFS-Bewertung, Freigabeliste; Changelog-Fragment.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- Fühler `host` ohne Ziel statt Bindung an eine Unit (Spec, Trade-offs).
- Ceph mit dem Admin-Keyring von root, kein eigener Nutzer (der Agent legt nichts an).
- ZFS-Bewertung im bestehenden Checker, Vorlage unverändert.
- T1: `lvs` ohne `--select segtype=thin-pool` (segtype ist ein Segment-Feld), Filter auf `lv_attr[0]=='t'` im Agent.
- T1: `degraded` zählt Arrays (fehlendes Gerät oder `array_state` inactive/broken), `mismatch_cnt` ist die Summe; Zustand `clear` zählt nicht als Array.
- T2: perccli liegt unter `/opt/MegaRAID/perccli/perccli64` (Dell kbdoc 000217748, rpm und deb), nicht unter `/opt/dell/srvadmin/bin/` wie im Plan; Marker in T3 entsprechend.
- T2: `storcli2` wird nicht aufgerufen: weder seine Argumente (`nolog`) noch sein JSON ließen sich in Quellen belegen; ein Aufruf ungeprüfter Syntax auf fremder Hardware ist das größere Risiko als die Lücke (9600er-Controller bleiben ohne Ansicht, Folgezeile bei Bedarf).
- T2: ssacli liest neben `show status` auch `ctrl all show config` (nur lesend): erst dort stehen die Zustände der logischen und physischen Laufwerke für `vd_not_optimal`/`pd_failed`. Neues Feld `ctrl_bad` (Controller-Status nicht Optimal/OK), weil storcli und ssacli ihn liefern und er sonst in keinem Feld landet.
- T2: SDR-Cache neu, wenn er fehlt oder älter als 24 h ist, statt „je Agent-Start“: der Agent läuft als Oneshot, je Start wäre jeder Lauf ein Dump. Dump in `.ipmi-sdr.cache.new`, dann rename; die Allowlist lässt `sdr dump` nur auf diesen Namen unter einem absoluten Verzeichnis ohne `..` zu.
- T2: Gesunde Zustände nach check_lsi_raid (VD `Optl`, PD `Onln`/`UGood`/`GHS`/`DHS`/`JBOD`; `Rbld` zählt als `pd_failed`), BBU-Codes 0/8/4096 nach storcli.py; IPMI `elist`-Zustände aus ipmitool `ipmi_sdr.c` (lnc/unc → noncritical, lcr/ucr/lnr/unr/cr/nr → critical, `ns` zählt nicht). Fehlermeldungen tragen keine stderr-Zeile der CLIs (Seriennummern).
- T2 → T3: Katalog-Timeout für `ipmi_sensors` und `raid_ctrl` 30 s (Höchstwert `timeout_s`): je Aufruf 14 s, zwei Aufrufe (Dump + elist, ssacli status + config) passen hinein.
- T3: `ipmi` alle 15 min statt 10 (der Katalog kennt nur 300/900/3600/86400 s); `lvm_thin` 300 s mit `timeout_s` 30 über den 15 s von lvs, damit „beschäftigt“ als Wert ankommt, nicht als Zeitüberschreitung.
- T3: Ein Marker trifft mit einem seiner Pfade oder Pakete (Agent `checkMarkers`), ein UND gibt es nicht: `mdadm` erkennt `/proc/mdstat` oder Paket `mdadm`, `lvm-thin` `lvs` oder Paket `lvm2`; ein Host ohne Arrays/Pools meldet 0. `ipmi` erkennt nur die Gerätedatei (nicht `ipmitool`), ohne ipmitool meldet die Ansicht „nicht unterstützt“.
- T4: `nut_ups` fragt je UPS `upsc <ups>@localhost` einmal (alle Variablen, nur drei gelesen) statt drei Einzelaufrufe; stale = Exit 1 mit „Data stale“ oder „Driver not connected“ (clients/upsclient.c). Fehlen Laufzeit/Ladung bei allen UPS, bleiben `min_runtime_s`/`min_charge_pct` weg statt 0. UPS-Namen außerhalb der Klasse `upsname` (kein `@`, `:`, führendes `-`) sind ein Fehler, kein stilles Auslassen.
- T4: apcupsd `TIMELEFT` gilt als Dezimalminuten; laut apcstatus.c (SVN trunk) ist die Nachkommastelle der Sekundenrest, Abweichung < 1 min, nicht gegen ein echtes apcupsd geprüft.
- T5: `nut-monitor` ist ein eigenes Modul (Unit `nut-monitor.service`, nur Service-Check), nicht ein zweiter Unit-Check im Modul `nut`: eine Instanz gehört zu genau einer Unit, `Target` trägt keinen zweiten Unit-Namen, und inaktive Units findet die Erkennung nicht (`app/discovery.py`). Ein Host, der nur `upsmon` gegen einen fremden upsd fährt, bekommt so auch die Prüfung.
- T5: Abweichung vom Plan: keine Regel `min_runtime_s lt 600`. `_rate` (`app/checkers/probe.py`) wertet ein fehlendes Feld als unbewertbar und hält den Check auf `unknown`, wenn keine andere Regel greift; viele Treiber melden keine Laufzeit. Laufzeit und Ladung stehen als Werte und auf der Karte, den Alarm trägt das LB-Flag des Treibers (aus dessen Laufzeit-/Ladungsgrenzen). Kevin am Ende nennen.
- T6: `pve_cluster` fragt `/nodes/<n>/replication` statt `/cluster/replication`: Letzteres ist nur die Job-Konfiguration ohne Zustand (pve-manager `Cluster.pm` → `ReplicationConfig`); `replication_failed` zählt Jobs mit `fail_count > 0`. `ha_error` zählt Dienste mit `crm_state` `error`, `fence` oder `recovery` (ha-manager-Doku „Service States“). Knotenname = kurzer Hostname wie `monitor.collectProxmox`, weil `localhost` nicht in jedem Handler ersetzt wird (`pvesh.pm`).
- T6: `jobs_failed` = fehlgeschlagene vzdump-Läufe in Folge seit dem letzten nicht fehlgeschlagenen (Status weder `OK` noch `WARNINGS…`), damit ein späterer guter Lauf die Meldung löst; `last_run_age_s` fehlt ohne Lauf. Die Statuswörter aus pve-common sind nicht live geprüft.
- T7: `pbs_status` fragt die PBS-API über `proxmox-backup-debug api get` (lokal, nur get), nicht `proxmox-backup-manager` (dessen Unterbefehle schreiben teils); `tasks_failed` zählt Jobs (worker_type + worker_id der Präfixe garbage_collection, verif, sync, prune), deren neuester beendeter Lauf weder `OK` noch `WARNINGS…` ist, damit ein späterer guter Lauf die Meldung löst; je Präfix ein Aufruf `--typefilter <präfix> --limit 50`, damit Backup- und Reader-Tasks einen Job-Lauf nicht aus dem Fenster drängen (zusammen fünf `api get` je Lauf, Rust-Daemon über Loopback). Abweichung von der Spec (Zeile 68: `/admin/datastore`, `tasks?errors=1`): `/config/datastore` für den Wartungsmodus, `/status/datastore-usage` für Belegung und Schätzung, Tasks ohne `errors`, weil erst der neueste Lauf je Job entscheidet; T10 zieht die Spec nach. Nicht live geprüft: die Statuswörter, ob `typefilter` Teilstrings matcht (Quelle tasks.rs) und was `estimated-full-date` ohne Verlauf trägt; 0, negativ oder in der Vergangenheit (schrumpfender Store) ergibt kein `min_full_days`.
- T7: `ceph_health` liest `status` und `checks` auf oberster Ebene von `ceph health -f json` und die Anteile 0..1 aus `ceph df -f json` (Quelle HealthMonitor.cc/PGMap.cc, nicht an einem Cluster geprüft); jede andere Form ist ein Fehler. `zfs_snapshots` liest nur den Exit-Code von `sanoid --monitor-snapshots` (0/1/2 → ok/warning/critical, sonst Fehler), nie die Ausgabe mit Dataset-Namen; ob sanoid auf die Sperre eines laufenden `--cron` wartet, ist nicht geprüft (Werkzeug-Timeout 10 s begrenzt). Ziel-Unit für sanoid (oneshot) wählt T8.
