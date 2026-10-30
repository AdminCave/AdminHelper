### Changed

- **install.sh: Admin-Passwort nur im Skript:** Ein in der aufrufenden Shell exportiertes `ADMIN_PASSWORD` gibt das
  Passwort nicht mehr an die Kindprozesse von install.sh weiter. Wer install.sh bisher mit exportiertem
  `ADMIN_PASSWORD` aufgerufen hat, erzeugt den Server-Container einmal neu (`docker compose up -d --force-recreate
  server` im Installationsverzeichnis) und ändert danach das Admin-Passwort.

### Fixed

- **agent-install.sh -h:** Die Hilfe druckt nur noch den Kopfkommentar, nicht mehr die Zeile `set -euo pipefail`.
