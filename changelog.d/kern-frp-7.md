### Changed

- **FRP: Erneuern des Tunnel-Schluessels meldet den Abgleich:** die Antwort von
  `POST /api/servers/{id}/frp-key/rotate` traegt `policySynced`; konnte der Server die frps-Policy nicht schreiben,
  zeigt der Desktop eine Warnung statt der Erfolgsmeldung.
