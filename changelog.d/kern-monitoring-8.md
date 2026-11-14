### Added

- **Monitoring: Module fuer Webserver und PHP:** nginx, Apache, HAProxy, PHP-FPM, PM2, Varnish, ProFTPD und
  CloudPanel. Der Agent faehrt taeglich den Konfigurationstest des Webservers und liest die Statusseiten, die nginx,
  Apache und PHP-FPM schon auf Loopback ausliefern, die Backends und Server am Stats-Socket von HAProxy (nur `show`)
  und die Apps des PM2-Daemons als dessen Nutzer. CloudPanel bekommt eine Pruefung des Panel-Zertifikats; `clpctl`
  startet der Agent nie. Doku: Monitoring, Abschnitt App-Module (DE+EN).
- **Monitoring: Module fuer Datenbanken:** MariaDB (Verbindungen, abgebrochene Verbindungen, Replikation, Galera),
  PostgreSQL (Erreichbarkeit, Verbindungen, lange Transaktionen, Replikation, Alter der Transaktions-IDs), Redis
  (`INFO`: Persistenz, abgewiesene Verbindungen, verdraengte Schluessel, Speicher) und Elasticsearch (Cluster-Status,
  Knoten, Disk-Indikator). MariaDB und PostgreSQL fragt der Agent ohne gespeichertes Passwort ueber den lokalen
  Socket.
- **Monitoring: Module fuer Backups:** UrBackup, BackupPC, rsnapshot, Veeam Agent for Linux, restic, borg, kopia,
  Duplicati sowie die Backup-Verzeichnisse von GitLab (Paket und Docker) und 3CX. Gemeldet werden nur Zaehler, Alter
  und Groessen; ein Backup aelter als 26 Stunden warnt. restic, borg und kopia fragen das Repository der Unit ohne
  Sperre und nur mit einem Passwort, das der Admin auf dem Host hinterlegt (`monitor credential set`, neue Verwendung
  `password`); bis dahin warnt der Check. Die Passwortdatei eines Backup-Jobs liest der Agent nie.
- **Monitoring: Units hinter einem Timer:** Der Sensor `unit` meldet zusaetzlich Ergebnis, Exit-Status und Alter des
  letzten Laufs, die Erkennung findet Backup-Units auch zwischen zwei Laeufen, und `file_age` liest mit `newest_in`
  die juengste Datei eines Verzeichnisses. Diese Checks brauchen einen Agent in der Version des Monitoring-Dienstes;
  ein aelterer meldet sie `unknown`. Doku: Entwickler-Doku Agent und Monitoring (DE+EN).
