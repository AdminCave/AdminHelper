### Fixed

- **Agent-Installation: abgebrochene Provisionierung:** Scheitert die Provisionierung auf einem schon
  eingebundenen Host, stellt `agent-install.sh` die Repo-Konfiguration des Hosts wieder her.
- **Update: aeltere Datenbank-Sicherungen:** `update.sh` macht Dump-Dateien in `backups/` nur fuer den Besitzer
  lesbar; gelingt das nicht, nennt es eine Warnung.
