### Fixed

- **Update: Laufzeit-Snapshot:** `update.sh` legt den Snapshot fuer den Rollback unter einem frischen Namen an
  und spielt den Rollback aus seiner eigenen Kopie in einem privaten Temp-Ordner zurueck.
- **Restore: Herkunft des Archivs:** `restore.sh` prueft vor dem Einspielen Eigentuemer und Schreibrechte von
  Archiv und Ordner; ein Backup aus fremder Hand spielt es mit `--allow-foreign` ein.
- **Installation und Update: leerer Schluessel in der `.env`:** Ein Schluessel nur aus Leerzeichen wird mit
  Zeilennummer abgelehnt statt mit einem Shell-Fehler.

### Changed

- **Taegliche DB-Sicherung mit Leserolle:** `pg-backup` liest beide Datenbanken als `ah_backup`, die nur lesen
  darf. `init-secrets.sh` erzeugt dafuer `BACKUP_DB_PASSWORD`; `restore.sh` ergaenzt den Wert auf einem frischen
  Host, wenn das Backup ihn nicht traegt.
