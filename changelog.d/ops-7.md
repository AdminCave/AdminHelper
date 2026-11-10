### Fixed

- **Restore: Rollen-Passwort mit `$$`:** `restore.sh` nimmt ein `$`, das in der `.env` als `$$` steht, wie Docker
  Compose als ein `$`; die Meldung bei einem Wert, den es nicht lesen kann, nennt den Ausweg über die Umgebung.
- **Update: Umzug auf PostgreSQL 18 prüft sein Ziel:** `update.sh` prüft vor dem Leeren der neuen Datenbank, dass der
  gestartete Container PostgreSQL 18 auf dem neuen Volume ist; sonst rollt es zurück.
- **Backup: vorsichtiger bei ungewöhnlichen Schlüsseln in der `.env`:** ein Schlüssel mit Nicht-ASCII-Zeichen wird beim
  Bereinigen der gesicherten `.env` vorsichtiger behandelt.
