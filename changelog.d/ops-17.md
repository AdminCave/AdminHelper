### Fixed

- **Agent-Installation: abgebrochene Provisionierung:** Scheitert die Provisionierung auf einem schon
  eingebundenen Host, stellt `agent-install.sh` die Repo-Konfiguration des Hosts wieder her.
- **Update: aeltere Datenbank-Sicherungen:** `update.sh` macht Dump-Dateien in `backups/` nur fuer den Besitzer
  lesbar; gelingt das nicht, nennt es eine Warnung.
- **Restore: Routinen und Typen:** `restore.sh` leert vor dem Einspielen auch Funktionen, Prozeduren und eigene
  Typen einer neueren Version; die Skripte raeumen ihre Arbeitskopien der `.env` auch unter aelteren bash-Versionen
  sauber weg.

### Changed

- **Taegliche DB-Sicherung je Dienst-Rolle:** `pg-backup` liest jede Datenbank mit ihrer Dienst-Rolle und braucht
  das Superuser-Passwort nicht mehr.
