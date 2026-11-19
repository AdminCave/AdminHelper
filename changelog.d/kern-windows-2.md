### Changed

- **Agent unter Windows:** Die Datenordner unter `%ProgramData%\AdminHelper` bestimmt der Agent jetzt ueber die
  Windows-Ordnerpfade und nicht mehr ueber die Umgebungsvariable `ProgramData`, wie schon `service uninstall --purge`.
