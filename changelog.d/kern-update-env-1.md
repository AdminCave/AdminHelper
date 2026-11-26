### Fixed

- **Update/Installation: .env-Pruefung fuer Docker Compose ab v5.8.0:** `update.sh` und `install.sh` lehnen eine
  `.env`-Zeile ohne Schluesselnamen (`=wert`) und ein Leerzeichen in der letzten Zeile ohne Zeilenumbruch und ohne `=`
  vorab ab, mit der Zeilennummer. Compose ab v5.8.0 bricht an beidem jeden Aufruf ab; bisher scheiterte das Update erst
  dort.
