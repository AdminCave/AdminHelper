### Changed

- **install.sh: Admin-Passwort nur im Skript:** Ein in der aufrufenden Shell exportiertes `ADMIN_PASSWORD` gibt das
  Passwort nicht mehr an die Kindprozesse von install.sh weiter.

### Fixed

- **agent-install.sh -h:** Die Hilfe druckt nur noch den Kopfkommentar, nicht mehr die Zeile `set -euo pipefail`.
