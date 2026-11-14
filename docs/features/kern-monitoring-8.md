<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-8 — Katalog-Module für Webserver, Datenbanken und Backup-Werkzeuge

Roadmap: R-1231 (Web lokal), R-1232 (Datenbanken), R-1233 (Backup-Software). Kevin hat alle drei am 2026-11-09
diktiert (Monitoring-Konzept, vor Release 0.47.0). Sie bauen auf dem Fühler- und Modulmodell auf (`sensor_app.go`,
`app/catalog/`), das kern-monitoring-10 und kern-monitoring-7 zuletzt erweitert haben.

## Problem / Motivation

- **Web (R-1231):** Für nginx, Apache, HAProxy, PHP-FPM, CloudPanel und Node/pm2 kennt der Katalog heute nur Unit und
  Port. Dabei fällt ein kaputter Konfigurationsstand erst beim nächsten Reload auf (etwa durch certbot). Ein volles
  Worker- oder Pool-Limit und ein ausgefallenes HAProxy-Backend bleiben unsichtbar.
- **Datenbanken (R-1232):** Der Fühler `sql` liest Verbindungen, Replikation und Größe von MariaDB und PostgreSQL.
  Es gibt aber kein Modul, das sie erkennt und bewertet. Für Redis und Elasticsearch fehlt beides.
- **Backup (R-1233):** Ob ein Backup-Job lief, sagt heute nur der Unit-Zustand. Das Ergebnis des letzten Laufs, das
  Alter des letzten Snapshots und die Lage von UrBackup oder BackupPC fehlen. Für App-Backups (GitLab, 3CX) fehlt
  das Alter der jüngsten Datei.

## Ziel & Nicht-Ziele

**Ziel:** Erkennung, Ansichten und Regeln für die Dienste der drei Zeilen. Es gelten dieselben Regeln wie in
kern-monitoring-10 (Konzept §3.13):

- Der Agent startet nur Lesekommandos aus der Freigabeliste, mit festen Argumenten.
- Zum Server gehen nur Zahlen, Zustände und Alter, nie Namen, Adressen, Pfade oder Konfigurationsinhalte.
- Jede bekannte Falle steht als Negativtest in der Freigabeliste.

**Web:**

- **Konfigurationstest:** `nginx -t`, `apachectl -t` bzw. `apache2ctl -t` und `haproxy -c -f <cfg>` laufen
  täglich. Ein Fehlschlag ist ein Befund (warning).
- **Laufzeit:**
  - nginx `stub_status` und Apache `mod_status ?auto` nur, wenn der Admin sie auf Loopback eingerichtet hat. Der
    Agent legt nichts an.
  - HAProxy über den Stats-Socket aus der Konfiguration (`show stat`, `show servers state`): Backend DOWN →
    critical, Server DOWN → warning, Wartung (`srv_admin_state`) zählt getrennt. Das gilt auch für das
    OPNsense-Plugin (`/var/run/haproxy.socket`, FreeBSD-Agent).
  - PHP-FPM je Pool aus `pool.d` über die Statusseite (FastCGI, `?json`), nur mit `pm.status_path`. Die Ansicht
    meldet listen queue, Δ max children reached und Δ slow requests. Ein Pool, der auf TCP außerhalb von Loopback
    lauscht und kein `listen.allowed_clients` setzt, wird gezählt (Befund).
  - Node/pm2: `pm2 jlist` als Besitzer der Unit `pm2-<user>` liefert errored/stopped (critical) und Δ Neustarts
    (warning).
- **CloudPanel:** Ein Sammelmodul über nginx, PHP-FPM, MariaDB/MySQL, Redis, Varnish und ProFTPD. `clpctl` wird nie
  gestartet.

**Datenbanken:**

- **MariaDB/MySQL:** nur über den Unix-Socket (`sql`, unix_socket). Gemessen werden Verbindungen gegen
  `max_connections` (80 / 95 %), Fehler-Deltas (`Aborted_connects`, `Connection_errors_max_connections`), das
  Replikat (Threads, Lag > 300 s) und, falls aktiv, Galera (`wsrep_cluster_status`, `wsrep_ready`).
- **PostgreSQL:** peer als `postgres`. Gemessen werden `ping`, Verbindungen, das XID-Alter (stündlich; warning ab
  1,0 Mrd., critical ab 1,5 Mrd.), lange Transaktionen (> 1 h) und Replikation.
- **Redis:** `PING` und `INFO` (Standard-Sektionen, nie `INFO all`) über TCP-Loopback oder Socket. Bewertet werden
  `rdb_last_bgsave_status`, `aof_last_write_status`, Δ `rejected_connections`, Δ `evicted_keys` und der Speicher
  gegen `maxmemory`.
- **Elasticsearch:** `_cluster/health` (Status, nicht zugewiesene Shards) und `_health_report` stündlich (Indikator
  `disk`, bildet die Watermarks 85/90/95 % ab). Dazu kommt der Heap aus `_nodes/stats/jvm`. Eine Paketinstallation
  braucht einen lokal hinterlegten Nutzer mit Recht `monitor`; Zammad-Docker braucht keinen.

**Backup:**

- **Planer-Ergebnis zuerst:** Der Fühler `unit` liefert dazu `result`, `exec_status` und `last_run_age_s` des
  Dienstes hinter einem Timer, nur unter Linux.
- **UrBackup:** Server-Status (`file_ok`/`image_ok`, `lastseen`, `nospc_fatal`, `database_error`) mit lokal
  hinterlegtem Web-Nutzer (Recht „status“).
- **BackupPC:** `BackupPC_serverMesg status` als Nutzer `backuppc`.
- **rsnapshot:** Logdatei und Lockfile (veraltete PID heißt abgebrochener Lauf); nie `du`, nie `diff`.
- **Veeam Agent für Linux:** `veeamconfig session list`.
- **Repo-Abfrage nur mit lokal hinterlegtem Passwort (Kevin §10 Nr. 12):**
  - restic `snapshots --json --latest 1 --no-lock`
  - borg `list --last 1 --json --bypass-lock`
  - kopia `snapshot list --json -n 1`
  - Duplicati `duplicati-server-util health`
- **App-Backups:** Der Fühler `file_age` bekommt die Form „jüngste Datei in einem Verzeichnis“. Damit misst er das
  Alter (< 26 h) und einen Größensturz (> 50 %) für GitLab (`/var/opt/gitlab/backups` bzw. das Volume) und 3CX
  (Pfad vom Admin).

**Nicht-Ziele (eigene Zeilen, am Gate genannt):**

- **Domains, Zertifikatsdateien und Datei-vs-ausgeliefert aus den vHosts** (Rest von R-1231): Das braucht das
  Auslesen der vHosts in der Erkennung, und die Namen gehen in den Funde-Eingang. Neue Zeile im Zug
  kern-monitoring-28.
- **Windows Server Backup und Veeam unter Windows** (Ereignisse, Rest von R-1233): Ein Leser für das
  Windows-Ereignisprotokoll fehlt im Agent; R-1245 (kern-monitoring-14) baut ihn. Neue Zeile dort.
- Repo-Abfragen gegen entfernte Backends (S3, B2, rclone …) mit eigenen Zugangsdaten: in v1 nur lokale und
  SFTP-Repos, die root schon erreicht. Die übrigen meldet die Ansicht als `unsupported`.
- `nginx -T` oder `apachectl -S` zum Server schicken; einen Status-Endpunkt anlegen; `postfix`, `clpctl`,
  `borg info`, `kopia maintenance` starten.

## Betroffene Komponenten & Dateien

- **Agent** (`apps/agent/internal/probe/`):
  - `sensor_app.go` (Ansichten-Tabelle)
  - neue Dateien: `app_web.go`, `app_haproxy.go`, `app_fpm.go`, `app_pm2.go`, `app_db.go`, `app_backup.go`,
    `app_repo.go`, je mit Test
  - `sensor_proto.go` (FastCGI-Anfrage für die Statusseite)
  - `sensor_sql.go` (neue Abfragen `errors`, `galera`, `xid_age`, `long_tx`)
  - `sensor_local_linux.go` (Unit-Felder)
  - `sensor_local.go` (`file_age` jüngste Datei)
  - `sensor_http.go` (Nutzung `password`)
- **Freigabeliste:** `apps/agent/internal/allowlist/allowlist.go` mit Test.
- **Monitoring:**
  - `apps/monitoring/app/catalog/sensors.py`, `model.py` (Credential-Nutzung `password`)
  - neue Module unter `app/catalog/modules/`: nginx, apache, haproxy, php_fpm, cloudpanel, pm2, mariadb, postgres,
    redis, elasticsearch, urbackup, backuppc, rsnapshot, veeam, restic, borg, kopia, duplicati, app_backups
  - `app/discovery.py` (`_NEVER_PROCESSES` bleibt; Erkennung über Unit/Image)
  - Tests `tests/test_catalog_web.py`, `tests/test_catalog_db.py`, `tests/test_catalog_backup.py`,
    `tests/test_catalog_sensors.py`
- **Doku:** `docs/admin/monitoring.html`, `docs/en/admin/monitoring.html`, `docs/developer/agent.html` und
  `docs/developer/monitoring.html` (DE+EN), dazu `changelog.d/kern-monitoring-8.md`.

## Datenmodell / API / Migrationen

- **Keine Alembic-Migration:** Module und Checks sind Katalog-Daten.
- **Vertrag Agent ↔ Monitoring (ändert sich):**
  - neue Ansichten im Fühler `app`
  - neue Abfragen im Fühler `sql`
  - neue Felder im Fühler `unit`
  - `file_age` mit Parameter `newest_in`
  - Credential-Nutzung `password`, die das Passwort als Umgebungsvariable an genau ein freigegebenes Kommando gibt
- **Ältere Agenten:** Ein älterer Agent meldet die neuen Checks `unknown` (wie in kern-monitoring-10).
- **Web/Desktop:** Server-API, Web und Desktop ändern sich nicht. Die Karten nutzen das bestehende Modul-Schema.

## Externe Integrationen

Alle Formate werden in der Task an der offiziellen Doku belegt. Die Quelle steht im Kommentar; was nur an
Beispielausgaben geprüft ist, heißt dort „nicht verifiziert“.

- **nginx:** `ngx_http_stub_status_module` (nginx.org/en/docs/http/ngx_http_stub_status_module.html)
- **Apache:** `mod_status` (httpd.apache.org/docs/2.4/mod/mod_status.html). Die Feldnamen von `?auto` sind laut
  Konzept unverifiziert.
- **HAProxy:** Management Guide, Kapitel 9.3 `show stat`, `show servers state` (docs.haproxy.org)
- **PHP-FPM:** Statusseite (php.net/manual/en/fpm.status.php), FastCGI 1.0 `FCGI_BEGIN_REQUEST`/`FCGI_PARAMS`
- **pm2:** `pm2 jlist` (pm2.keymetrics.io); die Feldnamen sind teils unverifiziert.
- **Datenbanken:**
  - MariaDB: Server Status Variables, Galera `wsrep_*`
  - PostgreSQL: Routine Vacuuming §24.1.5 (Wraparound), `pg_stat_activity`
  - Redis: `INFO`
  - Elasticsearch: Cluster health API, Health report API, Nodes stats API
- **Backup-Werkzeuge:**
  - restic `snapshots`, borg `list`, kopia `snapshot list`, `duplicati-server-util`
  - BackupPC: Dokumentation zu `BackupPC_serverMesg`
  - UrBackup: inoffizielle API (Wrapper des Autors), als unverifiziert markiert
- **systemd:** `org.freedesktop.systemd1` Properties `Result`, `ExecMainStatus` und `ExecMainExitTimestampMonotonic`

## Trade-offs & Alternativen

- **Ansichten statt allgemeiner Fühler:**
  - Für HAProxy, PHP-FPM und Elasticsearch gäbe es `unixsocket`/`http` mit `data.<pfad>`. Ihre Antworten sind aber
    nach Proxy-, Pool- oder Knotennamen geschlüsselt, und Namen gehen nie zum Server.
  - Deshalb zählt der Agent in einer Ansicht. Die Fühler `unixsocket`/`http` bleiben für Redis und `_cluster/health`,
    deren Felder flach sind.
- **Fremde Nutzer (pm2, BackupPC):** Diese Kommandos laufen über `runuser -u <nutzer> --`, wie heute `psql` für
  PostgreSQL.
  - Der Nutzer kommt aus einer festen Liste (`backuppc`) oder aus dem Unit-Namen `pm2-<user>`. In der Freigabeliste
    hat er eine eigene Argumentklasse.
  - Alternative wäre setuid im Agent: mehr eigener Code für dieselbe Wirkung, abgelehnt.
- **Passwort für Repo-Abfragen:**
  - Eine neue Credential-Nutzung `password` setzt genau eine Umgebungsvariable (`RESTIC_PASSWORD`,
    `BORG_PASSPHRASE`, `KOPIA_PASSWORD`) für genau das freigegebene Kommando.
  - Alternative: der Agent liest `--password-file` des Jobs. Das sind fremde Pfade und Formate; die Zugangsdaten
    sollen lokal hinterlegt sein (Kevin §10 Nr. 3), abgelehnt.
- **Zuschnitt:** vHost-Domains und die Windows-Ereignisse fahren in eigenen Zeilen, damit dieser Zug bei 13 Tasks
  und `linux-full` bleibt.

## Risiken & Rollback

- **Last:** Konfigurationstests nur täglich, Repo-Abfragen 1–6 h, `_health_report` stündlich. Alle Kommandos haben
  harte Timeouts (`busy`), der Ressourcen-Deckel aus §3.13 gilt.
- **Locks:** restic ohne `--no-lock` könnte das prune des Kunden scheitern lassen. Die Freigabeliste erlaubt
  restic nur mit `--no-lock` und borg nur mit `--bypass-lock`; ein Negativtest prüft das.
- **Fremde Nutzer und Passwörter** berühren den Risikopfad des Agents: `security` je betroffener Task.
- **Rollback:** Jede Task ist ein Commit. Module lassen sich einzeln aus `modules/__init__.py` nehmen.

## Doku-Impact

- Monitoring-Admin-Doku (DE+EN): Modultabellen Web, Datenbanken und Backup, „Nie aufgerufen“, Hinweis auf lokal
  hinterlegte Zugangsdaten.
- Entwickler-Doku Agent und Monitoring (DE+EN): Ansichten, Abfragen, Unit-Felder, `file_age newest_in`,
  Credential-Nutzung `password`.
- Changelog-Fragment.

## Offene Fragen

Keine aus Kevins Bereich. Die drei Zeilen sind diktiert, und die Zugangsdaten folgen §10 Nr. 3 und 12. Die Teilung
in zwei neue Zeilen steht am Gate.
