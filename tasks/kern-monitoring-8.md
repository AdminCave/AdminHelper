<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Module Webserver, Datenbanken und Backup-Werkzeuge — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-8 · Review: pro Task
Spec: docs/features/kern-monitoring-8.md (Roadmap R-1231, R-1232, R-1233)
Heavy: linux-full — neue Agent-Ansichten, Fühler-Felder und Freigabeliste (`apps/agent`), kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Gebaut wird erst nach den Merges von kern-monitoring-10 und kern-monitoring-7 (dieselben Dateien); vor T1
`origin/main` in den Branch mergen.

### T1 — R-1233: Fühler unit mit Laufergebnis, file_age mit jüngster Datei  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_local_linux.go, apps/agent/internal/probe/sensor_local_linux_test.go, apps/agent/internal/probe/sensor_local.go, apps/agent/internal/probe/sensor_local_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @acfea187a 2026-11-13T22:35:05+01:00
Review: approve (.ah-out/review/kern-monitoring-8/T1.verdict.json)
Änderung: `unit` liefert unter Linux zusätzlich `result`, `exec_status` und `last_run_age_s` (systemd-Properties
`Result`, `ExecMainStatus`, `ExecMainExitTimestampMonotonic`). `file_age` nimmt statt `path` auch `newest_in`
(Verzeichnis, nicht rekursiv, nur reguläre Dateien, Obergrenze der Einträge) und meldet Alter und Größe der jüngsten
Datei, nie ihren Namen.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T14

### T2 — R-1233: Ansichten mit lokal hinterlegtem Zugang, Nutzung password  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/sensor_app_test.go, apps/agent/internal/probe/sensor_http.go, apps/agent/internal/probe/probe.go, apps/agent/internal/probe/probe_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @d93ba5e16 2026-11-13T22:41:55+01:00
Review: approve (.ah-out/review/kern-monitoring-8/T2.verdict.json)
Änderung: Der Fühler `app` reicht den Zugang einer Probe an Ansichten weiter, die ihn ausdrücklich nehmen (Liste
erlaubter Nutzungen je Ansicht, sonst wie heute ein Fehler). Neue Nutzung `password`: Sie gibt das Passwort nur als
Umgebungsvariable an genau ein freigegebenes Kommando weiter (`allowlist.RunEnv`), nie als Argument und nie ins Log.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T14

### T3 — R-1231: Ansichten web_config, nginx_status, apache_status  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_web.go, apps/agent/internal/probe/app_web_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @d31fdfe36 2026-11-13T23:02:13+01:00
Review: approve (.ah-out/review/kern-monitoring-8/T3.verdict.json)
Änderung: `web_config` startet je Unit den Konfigurationstest (`nginx -t`, `apachectl -t`/`apache2ctl -t`, `haproxy
-c -f <cfg>`) und meldet `ok`, keinen Text. `nginx_status` und `apache_status` lesen `stub_status` bzw. `mod_status
?auto` nur von einem Loopback-Ort, den die Konfiguration schon nennt; fehlt er, `unsupported`. Felder: Zähler und
Belegung. Fallen (`nginx -s`, `apachectl graceful|restart`, `haproxy -sf`) als Negativtest. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T14
Abhängt von: T2

### T4 — R-1231: Ansicht haproxy_servers (auch OPNsense-Plugin)  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_haproxy.go, apps/agent/internal/probe/app_haproxy_test.go, apps/agent/internal/probe/sensor_proto.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @d26380e5e 2026-11-13T23:16:33+01:00
Review: approve (.ah-out/review/kern-monitoring-8/T4.verdict.json)
Änderung: Stats-Socket aus der Konfiguration (`stats socket`, unter OPNsense `/var/run/haproxy.socket`), `show stat` und
`show servers state`; gezählt werden Backends down, Server down, Server in Wartung (`srv_admin_state`), ohne Namen.
Ohne Socket `unsupported`. Läuft unter Linux und FreeBSD. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T14

### T5 — R-1231: Ansicht fpm_pools über die FastCGI-Statusseite  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_fpm.go, apps/agent/internal/probe/app_fpm_test.go, apps/agent/internal/probe/sensor_proto.go, apps/agent/internal/probe/sensor_proto_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @51d467d3a 2026-11-13T23:35:51+01:00
Review: approve (.ah-out/review/kern-monitoring-8/T5.verdict.json)
Änderung: Pools aus `pool.d` der Unit; je Pool mit `pm.status_path` eine FastCGI-Anfrage (`FCGI_BEGIN_REQUEST`,
`FCGI_PARAMS`, `?json`) an den eigenen Socket; Summe von listen queue, max children reached, slow requests; dazu die
Zahl der Pools, die auf TCP außerhalb von Loopback ohne `listen.allowed_clients` lauschen. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T14

### T6 — R-1231: Ansicht pm2_apps  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_pm2.go, apps/agent/internal/probe/app_pm2_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: An Unit `pm2-<user>` gebunden; `runuser -u <user> -- pm2 jlist` (Nutzer als eigene Argumentklasse, nie
root); meldet Apps gesamt, errored, stopped und die Summe der Neustarts. Fallen (`pm2 restart|reload|delete|flush`)
als Negativtest. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T14

### T7 — R-1231: Module nginx, apache, haproxy, php-fpm, pm2, cloudpanel  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/__init__.py, apps/monitoring/app/catalog/modules/nginx.py, apps/monitoring/app/catalog/modules/apache.py, apps/monitoring/app/catalog/modules/haproxy.py, apps/monitoring/app/catalog/modules/php_fpm.py, apps/monitoring/app/catalog/modules/pm2.py, apps/monitoring/app/catalog/modules/cloudpanel.py, apps/monitoring/tests/test_catalog_web.py
Änderung: Ansichtsfelder und Ziele in `sensors.py`; sechs Module mit Erkennung (Unit/Image/Pfad), Takten
(Konfigtest täglich, Laufzeit 5 min), Regeln nach der Spec und Karten; CloudPanel als Sammelmodul. Neun Dateien:
Module und ihre Registrierung gehören zusammen. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_web.py tests/test_catalog_sensors.py
Doku: → T14
Abhängt von: T3, T4, T5, T6

### T8 — R-1232: Abfragen errors, galera, xid_age, long_tx und Ansicht es_nodes  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_sql.go, apps/agent/internal/probe/sensor_sql_test.go, apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_db.go, apps/agent/internal/probe/app_db_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: `sql` bekommt MariaDB `errors` (Aborted_connects, Connection_errors_max_connections) und `galera`
(`wsrep_cluster_status`, `wsrep_ready`), PostgreSQL `xid_age` (max `age(datfrozenxid)`) und `long_tx` (Zahl der
Transaktionen älter als 1 h). `es_nodes` liest auf Loopback `_nodes/stats/jvm,fs` und meldet höchsten Heap- und
Plattenanteil, ohne Knotennamen; optional mit Zugang `basic` (T2). Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T14
Abhängt von: T2

### T9 — R-1232: Module mariadb, postgres, redis, elasticsearch  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/__init__.py, apps/monitoring/app/catalog/modules/mariadb.py, apps/monitoring/app/catalog/modules/postgres.py, apps/monitoring/app/catalog/modules/redis.py, apps/monitoring/app/catalog/modules/elasticsearch.py, apps/monitoring/tests/test_catalog_db.py
Änderung: Erkennung über Unit/Image (MariaDB nie über TCP, `_NEVER_PROCESSES` bleibt); `sql`-Checks mit den neuen
Abfragen, Redis über `unixsocket`/`proto` mit `INFO`-Feldern, Elasticsearch über `http` (`_cluster/health`,
`_health_report` stündlich) und `es_nodes`; Regeln und Karten nach der Spec. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_db.py tests/test_catalog_sensors.py
Doku: → T14
Abhängt von: T8

### T10 — R-1233: Ansichten urbackup_status, backuppc_status, rsnapshot_status, veeam_sessions  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_backup.go, apps/agent/internal/probe/app_backup_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: UrBackup über die lokale Web-API mit Zugang `basic` (Felder unverifiziert, so markiert); BackupPC
`runuser -u backuppc -- BackupPC_serverMesg status`; rsnapshot Logdatei und Lockfile (veraltete PID); Veeam
`veeamconfig session list`. Nur Zähler und Alter. Fallen (`BackupPC_serverMesg backup`, `veeamconfig job start`,
`rsnapshot <stufe>`) als Negativtest. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T14
Abhängt von: T2

### T11 — R-1233: Ansichten restic_latest, borg_latest, kopia_latest, duplicati_health  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_repo.go, apps/agent/internal/probe/app_repo_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: Repo-Abfrage nur mit Zugang `password` (T2): `restic snapshots --json --latest 1 --no-lock`, `borg list
--last 1 --json --bypass-lock`, `kopia snapshot list --json -n 1`, `duplicati-server-util health`; Repo nur lokal
oder SFTP, sonst `unsupported`; meldet Alter des jüngsten Snapshots. Ohne `--no-lock`/`--bypass-lock` nicht in der
Liste; Fallen (`restic prune|forget|unlock`, `borg info|compact|break-lock`, `kopia maintenance run`) als Negativtest.
Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T14
Abhängt von: T2

### T12 — R-1233: Module urbackup, backuppc, rsnapshot, veeam  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/__init__.py, apps/monitoring/app/catalog/modules/urbackup.py, apps/monitoring/app/catalog/modules/backuppc.py, apps/monitoring/app/catalog/modules/rsnapshot.py, apps/monitoring/app/catalog/modules/veeam.py, apps/monitoring/tests/test_catalog_backup.py
Änderung: Module mit Erkennung, Takten (15 min bzw. 1 h), Regeln (fehlgeschlagen → critical, älter als 26 h →
warning) und Karten; dazu `unit`-Felder `result`/`exec_status`/`last_run_age_s` im Katalog. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_backup.py tests/test_catalog_sensors.py
Doku: → T14
Abhängt von: T1, T10

### T13 — R-1233: Module restic, borg, kopia, duplicati, app-backups und Nutzung password  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/model.py, apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/__init__.py, apps/monitoring/app/catalog/modules/restic.py, apps/monitoring/app/catalog/modules/borg.py, apps/monitoring/app/catalog/modules/kopia.py, apps/monitoring/app/catalog/modules/duplicati.py, apps/monitoring/app/catalog/modules/app_backups.py, apps/monitoring/tests/test_catalog_backup.py
Änderung: `Credential.use` nimmt `password`; Planer-Ergebnis (Timer-Unit) als Standard, Repo-Abfrage nur als Check
mit Zugang; App-Backups über `file_age newest_in` für GitLab (nativ und Volume) und 3CX (Pfad vom Admin): jüngste
Datei < 26 h, Größe nicht um mehr als 50 % gefallen; GitLab-Hinweis zu `gitlab-secrets.json` in der Karte. Neun
Dateien: Modelländerung, Module und Registrierung gehören zusammen. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_backup.py tests/test_catalog_sensors.py tests/test_check_configs.py
Doku: → T14
Abhängt von: T1, T11

### T14 — Doku Web, Datenbanken, Backup  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-8.md
Änderung: Modultabellen, Ansichten und Abfragen, Unit-Felder, `file_age newest_in`, Nutzung `password` und lokal
hinterlegte Zugangsdaten, „Nie aufgerufen“; Changelog-Fragment.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- HAProxy, PHP-FPM und Elasticsearch als Ansichten, weil ihre Antworten nach Namen geschlüsselt sind (Spec).
- Fremde Nutzer über `runuser -u <nutzer> --` wie bei PostgreSQL, kein setuid im Agent.
- Repo-Passwort als Credential-Nutzung `password`, nur als Umgebungsvariable eines freigegebenen Kommandos.
- Repo-Abfrage in v1 nur für lokale und SFTP-Repos; entfernte Backends `unsupported`.
- vHost-Domains/Zertifikatsdateien und Windows-Ereignisse in eigene Zeilen (Spec, Nicht-Ziele).
- T1: `exec_status` nur bei `ExecMainCode=1` (CLD_EXITED; nach einem Signal trägt ExecMainStatus die Signalnummer); `newest_in` nutzt das vorhandene `openDir` (O_DIRECTORY) und hört bei 10000 Einträgen auf.
- T3: Ein Statusort zählt nur auf Loopback, auf allen Adressen nur mit `server_name`/`ServerName`/`ServerAlias` localhost oder 127.0.0.1 (sonst träfe die Anfrage einen anderen Server); TLS-Listen werden übersprungen. nginx -T löst Includes nicht auf, darum je Datei. Apache: `<IfModule>`/`<IfDefine>` gelten als erfüllt (ein abgeschalteter Ort wird Abfragefehler statt unsupported); `slots` = Länge des Scoreboards, nicht MaxRequestWorkers. haproxy -c scheitert bei fehlender Datei wie bei kaputter: ohne `/etc/haproxy/haproxy.cfg` `unsupported`.
- T4: Backends aus `show stat -1 2 -1` (nur Backend-Zeilen, Status DOWN), Server aus `show servers state`: Wartung =
  `srv_admin_state & 0x67` (FMAINT, IMAINT, CMAINT, RMAINT, HMAINT; Drain zählt nicht), down = `srv_op_state 0`
  außerhalb der Wartung (1 startet, 3 stoppt sanft: beide dienen noch); beide Befehle gehen auf jeder Socket-Stufe
  (an HAProxy 3.4.7 mit `level user` und ohne Stufe geprüft). Socket = erstes absolutes `stats socket`/`unix@` aus
  `/etc/haproxy/haproxy.cfg`, dann `/usr/local/etc/haproxy.conf` (Ports); unter FreeBSD ohne Eintrag
  `/var/run/haproxy.socket` (OPNsense-Plugin; welche Datei os-haproxy schreibt, nicht verifiziert).
- 2026-11-13 T5: `fpm_pools` meldet pools, pools_read, pools_exposed und die Summen listen_queue,
  max_children_reached, slow_requests (Zähler seit Start; das Δ bildet der Server), nie Namen, Adressen oder Pfade.
  Pool-Verzeichnis nach Unit: `php<ver>-fpm` → `/etc/php/<ver>/fpm/pool.d`, `php-fpm` → `/etc/php-fpm.d` (Linux),
  `php_fpm`/`php-fpm` → `/usr/local/etc/php-fpm.d` (FreeBSD, nicht verifiziert); nur `*.conf`, sortiert, spätere
  Einstellung gewinnt, `$pool` ersetzt. Pools in `php-fpm.conf` selbst und `pm.status_listen` werden nicht gelesen.
  Eine Statusseite, die nicht antwortet, ist ein Fehler der Ansicht, kein stilles Auslassen. Live gegen PHP-FPM
  8.4.27 (Docker) geprüft: Unix-Socket über `dialUnix`, TCP über den Guard, Felder `listen queue`, `max children
  reached`, `slow requests`.
