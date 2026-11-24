### Changed

- **Release: Image-Pins im eigenen Job:** Die Digests der eigenen Images fuer das Runtime-Bundle loest ein eigener Job
  mit nur lesendem Token auf; der Job, der signiert und den Draft anlegt, uebernimmt nur noch die Datei `IMAGES`.
- **Update: Pins vor jeder Aenderung:** `update.sh` liest und prueft die Image-Pins des Ziel-Release, bevor es etwas
  aendert; `install.sh` und `update.sh` legen keine Kopie von `IMAGES` mehr ins Installationsverzeichnis.

### Fixed

- **Install/Update: keine liegengebliebene `.env`-Kopie:** `install.sh` und `update.sh` schreiben ihre Arbeitskopien der
  `.env` mit `mktemp` und raeumen sie beim Beenden weg, auch nach einem Signal; vorher konnte ein Abbruch eine Kopie mit
  allen Secrets neben der `.env` zuruecklassen.
