<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Linux-Extras und AdminHelper überwacht sich selbst — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-9 · Review: pro Task
Spec: docs/features/kern-monitoring-9.md (Roadmap R-1234, R-1235)
Heavy: linux-full — neue Ansichten, Fühler und Freigabeliste im Agent (`apps/agent`); kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Gebaut wird nach den Merges von kern-monitoring-8, -30, -14, -11 und -20 (`sensor_host.go`, `allowlist.go`,
`sensors.py`, `sensor_local.go`); vor T1 `origin/main` in den Branch mergen.

### T1 — R-1234: Ansichten systemd_timers und kernel_taint  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/host_linux_extras.go, apps/agent/internal/probe/host_linux_extras_test.go, apps/agent/internal/probe/sensor_host.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: `systemd_timers` (`systemctl list-timers --all`, dann `show -p Id,Result` der auslösenden Dienste; Zahl der
Timer und der gescheiterten letzten Läufe) und `kernel_taint` (`/proc/sys/kernel/tainted` als Bits, Livepatches in
Transition aus `/sys/kernel/livepatch/*/transition`, nur lesend). Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/ ./internal/allowlist/
Doku: → T8

### T2 — R-1234: Ansichten needrestart und apt_state  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/host_linux_extras.go, apps/agent/internal/probe/host_linux_extras_test.go, apps/agent/internal/probe/sensor_host.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: `needrestart` (`needrestart -b`, nur die Zeilen `NEEDRESTART-KSTA`, `-UCSTA`, Zahl der `-SVC`) und
`apt_state` (`dpkg --audit`, `apt-mark showhold` mit `LC_ALL=C`, Zahlen; Log von unattended-upgrades: Alter des
letzten Laufs, Fehler im letzten Lauf). Nie `apt-get check`; ein Test hält fest, dass die Freigabeliste es nicht
kennt.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/ ./internal/allowlist/
Doku: → T8
Abhängt von: T1

### T3 — R-1234: Katalog und Module Linux-Extras  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/systemd_timers.py, apps/monitoring/app/catalog/modules/needrestart.py, apps/monitoring/app/catalog/modules/kernel.py, apps/monitoring/app/catalog/modules/apt.py, apps/monitoring/tests/test_catalog_linux_extras.py
Änderung: `HOST_VIEW_FIELDS` um die Ansichten aus T1/T2, gleich wie im Agent. Module nach Konzept §6.14: gescheiterte
Timer > 0 warning; Kernel-Status ≥ 2 warning, Dienste > 0 warning; OOPS/MCE/bad page critical, Livepatch in Transition
warning; `dpkg --audit` > 0 warning, letzter unattended-upgrades-Lauf > 2 Tage warning, Fehler > 0 warning.
Erkennung über Marker (Pfade, Pakete) wie `mdadm.py`. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_linux_extras.py tests/test_catalog_sensors.py
Doku: → T8
Abhängt von: T2

### T4 — R-1235: Pfad im Container für certfile und file_age, Fühler fs  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_local.go, apps/agent/internal/probe/target.go, apps/agent/internal/probe/sensor_fs.go, apps/agent/internal/probe/sensor_fs_test.go, apps/agent/internal/probe/sensor_local_test.go
Änderung: `certfile` und `file_age` nehmen optional das Ziel `container`: der Pfad gilt im Container und wird über
`Mounts` aus `docker inspect` (Bind/Volume, längster passender Ziel-Präfix) auf den Host abgebildet; ohne passenden
Mount `invalid`, kein Pfad in einer Meldung. Neuer Fühler `fs` (`statfs`, ohne Ziel oder mit Ziel `container`):
`used_pct`, `free_bytes`, `inodes_used_pct`. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T8

### T5 — R-1235: Katalog: Container-Ziel, Fühler fs, Modul adminhelper  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/adminhelper.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/tests/test_catalog_adminhelper.py
Änderung: `SENSOR_TARGETS` erlaubt `container` für `certfile`/`file_age`/`fs`, `FsParams`. Modul `adminhelper`
(`compose_project`, Images `ghcr.io/admincave/adminhelper/*`): Container laufen; `http` `/health` (monitoring:8080),
`/healthz` (ca-issuer:8090); `tls` Gateway 443 und `certfile` frps-/CA-Zertifikat relativ zur Laufzeit; `file_age`
`/backups` am Dienst `pg-backup` (> 26 h warning, > 50 h critical); `fs` `/victoria-metrics-data` 80/90 %. Pfade
und Ports gegen `docker-compose.yml` und den CA-Issuer prüfen. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_sensors.py tests/test_catalog_adminhelper.py
Doku: → T8
Abhängt von: T4

### T6 — R-1235: Monitoring-Dienst meldet Scheduler-Verzug und Mailzustellung  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/main.py, apps/monitoring/tests/test_health.py
Änderung: nach Kevins Antwort (Spec, Offene Fragen 1).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_health.py
Doku: → T8

### T7 — R-1235: Modul adminhelper prüft Scheduler-Verzug und Mailzustellung  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/adminhelper.py, apps/monitoring/tests/test_catalog_adminhelper.py
Änderung: `http` auf `/health/detail` mit `data.scheduler_lag_s` (> 600 s warning, > 1800 s critical) und
`data.mail_failed_24h` > 0 warning; Modulversion hoch.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_adminhelper.py
Doku: → T8
Abhängt von: T5, T6

### T8 — Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-9.md
Änderung: Linux-Extras, Modul „AdminHelper selbst“, Fühler `fs`, Container-Ziel für `certfile`/`file_age`, Ansichten;
`changelog.d/kern-monitoring-9.md` unter `### Added`, ohne Umlaute. `doc-smoke --env` lokal fahren.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die genannten Dateien
Task-Review: am Ende
Abhängt von: T3, T5

## Entscheidungen
- Fehlgeschlagene Units meldet der Agent schon (`monitor/services_linux.go`, Systemcheck); der Zug ergänzt nur die
  Timer.
- Der `/healthz` des Gateways hört nur im Container auf `127.0.0.1:8081`; das Gateway prüfen `tls` auf 443 und der
  Container-Zustand.
- Kevin 2026-11-14: T6/T7 wie empfohlen: neue Route `GET /health/detail` nur im Compose-Netz, `/health` bleibt unverändert; übrige Monitoring-Entscheidungen wie im Ledger vorgeschlagen.
