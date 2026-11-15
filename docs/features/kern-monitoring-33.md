# kern-monitoring-33 — Nextcloud All-in-One und die Last der Jitsi-Bridge

Roadmap: R-1383 (FEAT), R-1388 (FEAT). Zug `tasks/kern-monitoring-33.md` der Kern-Session. Beide Zeilen kamen aus
kern-monitoring-29 hierher, weil die Quellen fehlten; die Quellen unten sind jetzt Primärquellen (Quellcode der
Projekte, 2026-11-15).

## Problem

- **R-1383:** Nextcloud All-in-One (AIO) wird nicht erkannt. Das Modul `nextcloud` nimmt die AIO-Images ausdrücklich
  nicht (`test_all_in_one_and_foreign_images_are_not_taken_for_nextcloud`), weil das tägliche Backup die Container
  stoppt: Ein Check `state ne running` würde jede Nacht alarmieren.
- **R-1388:** Das Modul `jitsi-videobridge` misst die Last der Bridge nicht. Der Docstring nennt zwei Gründe:
  `/colibri/stats` ist im Paket und im Image aus, und `/metrics` sei Prometheus-Text. Der zweite stimmt nur ohne
  `Accept`-Header (siehe Quellen).

## Quellen (Primär, gelesen 2026-11-15)

- AIO `Containers/mastercontainer/daily-backup.sh`: legt vor dem Stoppen `/mnt/docker-aio-config/data/
  daily_backup_running` an (Volume des Mastercontainers) und löscht die Datei erst, nachdem die Container wieder
  gestartet sind. `cron.sh` setzt einen unterbrochenen Lauf fort, solange die Datei liegt. Ein Backup aus der
  Oberfläche startet den Container `nextcloud-aio-borgbackup` und legt die Datei nicht an.
- AIO `php/containers.json`: feste Containernamen `nextcloud-aio-*`. Dauerhafte Container haben `restart:
  unless-stopped`. `borgbackup`, `watchtower` und `domaincheck` laufen nur zeitweise und haben keine Restart-Policy.
  Images `ghcr.io/nextcloud-releases/aio-*`, der Mastercontainer `ghcr.io/nextcloud-releases/all-in-one` (README,
  ältere Anleitungen `nextcloud/all-in-one`).
- JVB `doc/statistics.md`, `jvb/src/main/resources/reference.conf` (`videobridge.rest.prometheus.enabled = true`),
  jicoco `MetricsContainer.getMetrics`: `/metrics` auf dem privaten HTTP-Server antwortet bei `Accept:
  application/json` mit einem flachen JSON-Objekt `{"<metrik>": <wert>, …}`; ohne `Accept` OpenMetrics-Text.
  `VideobridgeMetrics.kt` registriert die Last als `stress` (0 = keine Last, 1 = volle Kapazität, mehr erlaubt).
  `jvb.conf` des Images (docker-jitsi-meet) überschreibt `rest.prometheus` nicht; der private Server hört auf
  `0.0.0.0:8080`.
- Jicofo im Image: REST nur mit `JICOFO_ENABLE_REST` auf `0.0.0.0`, sonst auf der Loopback des Containers.

## Ziel & Nicht-Ziele

Ziel:
- **R-1388:** Der HTTP-Sensor bekommt den Parameter `accept` (nur `application/json`), der Agent setzt dann den
  Header `Accept`. `jitsi-videobridge` v2 bekommt die Checks `load` (Container, Port 8080) und `service_load`
  (Paket) auf `/metrics` mit dem Feld `data.stress`: über 0.8 `warning`. Alle 5 Minuten wie `health`.
- **R-1383:** Neues Modul `nextcloud-aio`, erkannt am Image des Mastercontainers, Instanz `container`. Dazu:
  - Check `master`: der Mastercontainer selbst (`state`/`health`/`restarts`, wie überall).
  - Neue Ansicht `nextcloud_aio` des `app`-Sensors am Mastercontainer. Sie meldet nur Zahlen und Wahrheitswerte:
    `containers` (dauerhafte AIO-Container), `stopped` (davon nicht laufend, 0 während eines Backups), `backup`
    (die Datei liegt oder `nextcloud-aio-borgbackup` läuft) und `backup_age_s` (Alter der Datei, 0 ohne).
    Regeln: `stopped > 0` `critical`, `backup_age_s > 21600` (6 h) `warning`.
- Das Modul `nextcloud` bleibt bei seinem Nein zu AIO-Images; sein Docstring verweist auf das neue Modul.

Nicht-Ziele (YAGNI):
- Kein HTTP-Check auf `status.php` des Apache-Containers von AIO: Während des Backups ist er gestoppt, und eine
  Regel kann heute nicht auf das Feld eines anderen Checks schauen. Er alarmierte also jede Nacht. Port und TLS
  (`APACHE_PORT`) braucht ohne diesen Check niemand. Bedingungen über Checks hinweg werden eine eigene Roadmap-Zeile.
- Kein Jicofo: Seine REST-Schnittstelle ist im Image ohne `JICOFO_ENABLE_REST` vom Host aus nicht erreichbar
  (Loopback des Containers), und keine LAN-Sonde (Konzept §10 Nr. 4).
- Kein `/colibri/stats` und keine weiteren JVB-Metriken außer `stress`.
- Kein Lesen von `configuration.json` des Mastercontainers (trägt Passwörter); nur `stat` der Markierungsdatei.

## Betroffene Komponenten & Dateien

- Agent `apps/agent/internal/probe/`: `sensor_http.go` (+ Test) für `accept`. Neu `app_nextcloud_aio.go` (+ Tests,
  SPDX-Header), Eintrag in `sensor_app.go`, in `target.go` die Felder `Name` und `HostConfig.RestartPolicy.Name` von
  `containerInfo`.
- Monitoring `apps/monitoring/app/catalog/`: `sensors.py` (`HttpParams.accept`, Ansicht `nextcloud_aio`), neu
  `modules/nextcloud_aio.py`, `modules/jitsi_videobridge.py` (v2), `modules/nextcloud.py` (nur Docstring). Tests
  `test_catalog_jitsi.py`, `test_catalog_sensors.py`, neu `test_catalog_nextcloud_aio.py`.
- Doku Admin und Entwickler DE+EN, `changelog.d/kern-monitoring-33.md`.

## Ablauf der Ansicht `nextcloud_aio`

1. `inspectContainer` des Ziels, des Mastercontainers: Er muss laufen (`Pid > 0`).
2. Unter seiner Wurzel (`/proc/<pid>/root`, `os.Root`) ein `Lstat` von
   `mnt/docker-aio-config/data/daily_backup_running`. Eine reguläre Datei bedeutet Backup, ihr Alter ist
   `backup_age_s` (`now - mtime`, nie negativ). Fehlt sie, kein Backup. Ein Link oder ein anderer Typ ist ein Fehler.
   Der Inhalt wird nie gelesen.
3. `docker ps --all` und ein `docker inspect` über alle (wie `dockerPublications`): Gezählt werden die Container mit
   Namen `nextcloud-aio-*` und Restart-Policy `unless-stopped`, außer dem Mastercontainer selbst. `stopped` sind die
   davon, die nicht laufen. `nextcloud-aio-borgbackup` läuft → Backup.
4. Während eines Backups ist `stopped` 0. Kein Name und kein Pfad steht in einem Wert oder Fehler.

## Datenmodell / API / Migrationen

Keine Alembic-Migration und keine OpenAPI-Änderung. Neue Katalog-Version `jitsi-videobridge` v2 und neues Modul
(Angebot statt Auto-Rollout, Kevin 2026-11-11 zu R-1264). Der Parameter `accept` ist eine Erweiterung des
Vertrags Server → Agent: Ein alter Agent lehnt ihn ab (`invalid` wegen unbekanntem Parameter), deshalb baut der
Agent zuerst (T1 vor T2).

## Trade-offs & Alternativen

- **Ansicht im Agent (gewählt)** statt einer Bedingung über Checks im Server: Eine Regel `state ne running, außer
  wenn backup` bräuchte im Server den Wert eines anderen Checks (`checkers/probe.py` wertet je Check). Die Ansicht
  entscheidet auf dem Host aus zwei Quellen derselben Stunde; der Preis ist kein Einzel-Check je AIO-Container.
  Welcher Container steht, zeigt die Container-Liste des Hosts.
- **`stopped` 0 während des Backups** statt eines eigenen Zustands: Ein hängendes Backup fängt `backup_age_s` (6 h).
  Ein Backup aus der Oberfläche ohne Datei hat kein Alter; es endet mit dem Container `borgbackup`.
- **`accept` als Parameter** statt `Accept: application/json` bei jedem `data.`-Check: Andere Dienste könnten auf
  den Header anders antworten (Content Negotiation); der Parameter ändert nur die Checks, die ihn setzen.

## Risiken & Rollback

- Fremde Wurzel: nur `Lstat` über `os.Root`, kein Lesen, kein Link folgen (wie `wordpress_version`).
- Ein alter Agent mit `jitsi-videobridge` v2: die neuen Checks `invalid`, die alten laufen weiter. Rollback: Version
  zurück, Ansicht und Parameter sind additiv.

## Doku-Impact

`docs/admin/monitoring.html` (+ EN): Modultabelle `nextcloud-aio` neu, `jitsi-videobridge` mit Last, „Nicht
abgedeckt“ angepasst. `docs/developer/agent.html` (+ EN): Ansicht `nextcloud_aio`, Parameter `accept` des
HTTP-Sensors. Changelog-Fragment.

## Offene Fragen

Keine für Kevin: Das Weglassen des HTTP-Checks bei AIO folgt aus „Backup-Fenster ohne Fehlalarm“ der Zeile. Die
Bedingung über Checks hinweg wird eine Zeile `neu` zur Triage.
