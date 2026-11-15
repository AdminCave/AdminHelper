<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Nextcloud All-in-One und die Last der Jitsi-Bridge — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-33 · Review: pro Task
Spec: docs/features/kern-monitoring-33.md (Roadmap R-1383, R-1388)
Heavy: linux-full — neue Ansicht und neuer HTTP-Parameter im Agent (`apps/agent`), kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1388: HTTP-Sensor mit Parameter `accept`  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_http.go, apps/agent/internal/probe/sensor_net_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @285a28bd9 2026-11-15T09:00:31+01:00
Review: approve (.ah-out/review/kern-monitoring-33/T1.verdict.json)
Änderung: `knownParams` nimmt `accept` an, einziger Wert `application/json` (sonst `invalid`); gesetzt schickt der
Agent den Header `Accept: application/json`. Test: der Header kommt beim Ziel an, ein anderer Wert ist `invalid`,
ohne den Parameter kein `Accept`-Header.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T5

### T2 — R-1388: `jitsi-videobridge` v2 mit der Last der Bridge  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/jitsi_videobridge.py, apps/monitoring/tests/test_catalog_jitsi.py, apps/monitoring/tests/test_catalog_sensors.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @6f35b6814 2026-11-15T09:02:22+01:00
Review: approve (.ah-out/review/kern-monitoring-33/T2.verdict.json)
Änderung: `HttpParams.accept: Literal["application/json"]` (gesetzt oder weggelassen, wie `host`). Checks `load`
(Container, `port_hint` 8080) und `service_load` (Unit, 8080) auf `/metrics` mit `accept`, Feld `data.stress`, alle
300 s, `data.stress` > 0.8 `warning`; Karte „Load“. Version 2, Docstring (Quellen, Jicofo nicht abgedeckt).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_jitsi.py tests/test_catalog_sensors.py
Doku: → T5
Abhängt von: T1

### T3 — R-1383: Ansicht `nextcloud_aio` am Mastercontainer  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/app_nextcloud_aio.go, apps/agent/internal/probe/app_nextcloud_aio_test.go, apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/target.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @27b1cbce2 2026-11-15T09:12:37+01:00
Review: approve (.ah-out/review/kern-monitoring-33/T3.verdict.json)
Änderung: Ablauf der Spec: `Lstat` der Markierung `mnt/docker-aio-config/data/daily_backup_running` unter der
Wurzel des Mastercontainers über `os.Root` (nie gelesen, kein Link), dann `docker ps --all` + `docker inspect`:
dauerhafte `nextcloud-aio-*`-Container (`unless-stopped`, ohne den Mastercontainer) zählen, `borgbackup` läuft →
Backup. Werte `containers`, `stopped` (0 im Backup), `backup`, `backup_age_s`. `containerInfo` bekommt `Name` und
`HostConfig.RestartPolicy.Name`. Neue Dateien mit SPDX-Header. Tests über `stubDocker`/`stubContainerRoot`: Backup
per Datei, per `borgbackup`, ohne Backup mit gestopptem Container, Link als Fehler, kein Name in Werten/Fehlern.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T5

### T4 — R-1383: Modul `nextcloud-aio`  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/nextcloud_aio.py, apps/monitoring/app/catalog/modules/nextcloud.py, apps/monitoring/tests/test_catalog_nextcloud_aio.py, apps/monitoring/tests/test_catalog_sensors.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @67dcb890c 2026-11-15T09:14:08+01:00
Review: approve (.ah-out/review/kern-monitoring-33/T4.verdict.json)
Änderung: Ansicht `nextcloud_aio` mit ihren Feldern und Ziel Container in `sensors.py`. Neues Modul (SPDX-Header),
erkannt an `ghcr.io/nextcloud-releases/all-in-one` und `nextcloud/all-in-one`, Instanz `container`: Check `master`
(Container) und `aio` (Ansicht, alle 300 s, `stopped` > 0 `critical`, `backup_age_s` > 21600 `warning`), Karte.
Docstring von `nextcloud` verweist auf das Modul. Test: Erkennung, Regeln, `nextcloud` nimmt AIO weiter nicht.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_nextcloud_aio.py tests/test_catalog_nextcloud.py tests/test_catalog_sensors.py
Doku: → T5
Abhängt von: T3

### T5 — Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-monitoring-33.md
Änderung: Modul `nextcloud-aio` (was es prüft, Backup-Fenster, nicht abgedeckt: `status.php`), `jitsi-videobridge`
mit Last und dem Nein zu Jicofo; Ansicht und Parameter `accept` in der Entwickler-Doku; Changelog-Fragment.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende
Abhängt von: T2, T4

## Entscheidungen
- Kein HTTP-Check auf `status.php` von AIO (Spec, Nicht-Ziele): er stünde jede Nacht im Backup-Fenster rot. Die
  Bedingung über Checks hinweg wird eine Roadmap-Zeile `neu`.
