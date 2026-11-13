<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Module Speicher, Hardware, USV und Proxmox-Ausbau — Task-Ledger
Status: geplant · Branch: feature/kern-monitoring-7 · Review: pro Task
Spec: docs/features/kern-monitoring-7.md (Roadmap R-1228, R-1229, R-1230)
Heavy: linux-full — neuer Fühler, Agent-Ansichten und Freigabeliste (`apps/agent`), kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Gebaut wird erst nach dem Merge von kern-monitoring-10 (dieselben Dateien); vor T1 `origin/main` in den Branch mergen.

### T1 — R-1228: Fühler host mit den Ansichten mdadm und lvm_thin  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_host.go, apps/agent/internal/probe/host_storage.go, apps/agent/internal/probe/host_storage_test.go, apps/agent/internal/probe/sensor_host_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: Fühler `host` ohne Ziel (Muster `opnsense`: nur `view`); `mdadm` liest sysfs (`md.rst`), `lvm_thin` startet
`lvs` mit festen Argumenten über die Freigabeliste, Timeout 15 s → `busy`. Nur Zähler und Prozente, keine Namen.
Fallen (`mdadm --action`, `dmsetup` ohne `--noflush`, `lvchange`) als Negativtest. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T10

### T2 — R-1228: Ansichten raid_ctrl und ipmi_sensors  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_host.go, apps/agent/internal/probe/host_hw.go, apps/agent/internal/probe/host_hw_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: Controller-CLIs nur mit `J nolog` bzw. `ssacli … show status`, hostweit nacheinander (Mutex); IPMI nur bei
vorhandenem Gerät, SDR-Cache einmal je Agent-Start im Zustandsverzeichnis, dann `-S <cache> sdr elist`. Parser gegen
Beispielausgaben der Hersteller-Doku (Quelle im Kommentar, an Hardware ungeprüft). Fallen (`start learn`, `delete
events`, `sel clear`, `sel elist`) als Negativtest. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T10

### T3 — R-1228: Katalog-Fühler host und Module mdadm, lvm-thin, hwraid, ipmi  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/mdadm.py, apps/monitoring/app/catalog/modules/lvm_thin.py, apps/monitoring/app/catalog/modules/hwraid.py, apps/monitoring/app/catalog/modules/ipmi.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/tests/test_catalog_storage.py
Änderung: `host` in `SENSORS` ohne Ziel, `HOST_VIEW_FIELDS`, `HostParams`; vier Module mit Markern, Regeln und Karten
nach der Spec; Tests für Schema, Felder und Regeln. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_sensors.py tests/test_catalog_storage.py
Doku: → T10
Abhängt von: T1, T2

### T4 — R-1229: Ansichten nut_ups und apcupsd  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_ups.go, apps/agent/internal/probe/app_ups_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: `upsc -l localhost` und `upsc <ups>@localhost` (UPS-Name als Argumentklasse), nur `ups.status`,
`battery.runtime`, `battery.charge`; `apcaccess -u status`, nur vier Schlüssel. Fallen (`upscmd`, `upsrw`, `upsmon -c`)
als Negativtest. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T10

### T5 — R-1229: Module nut und apcupsd  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/nut.py, apps/monitoring/app/catalog/modules/apcupsd.py, apps/monitoring/tests/test_catalog_ups.py
Änderung: Module mit Units, Regeln (LB/FSD/OVER/stale → critical, OB/RB → warning, Laufzeit < 600 s → warning;
`nut-monitor` nicht aktiv → critical) und Karten. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_ups.py tests/test_catalog_sensors.py
Doku: → T10
Abhängt von: T4

### T6 — R-1230: Ansichten pve_cluster, pve_jobs, pve_updates  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_pve.go, apps/agent/internal/probe/app_pve_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: feste `pvesh get`-Pfade (Spec), höchstens vier Aufrufe je Ansicht, `apt/update` nur GET; nur Zähler,
Zustände und Alter, keine Gast- oder Knotennamen. Fallen (`pvesh create|set|delete`, `/nodes/<n>/storage`) als
Negativtest. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T10

### T7 — R-1230: Ansichten pbs_status, ceph_health, zfs_snapshots  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_pbs.go, apps/agent/internal/probe/app_pbs_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
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
