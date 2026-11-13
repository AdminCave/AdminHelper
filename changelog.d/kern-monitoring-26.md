### Changed

- **Agent: Proben-Waechter kennt weitere Weiterleiter und Super-Server:** Proben weisen Ports ab, die weitere
  Port-Weiterleiter oder `xinetd`/`inetd` halten, wie bisher schon bei der Socket-Aktivierung durch systemd.

### Fixed

- **Agent: klarere Abweisung nach dem Verbinden:** Eine volle Accept-Queue oder eine Verbindung, die der Dienst sofort
  beendet, gilt nicht mehr als Umleitung, bekommt eine eigene Meldung und sperrt den Port nicht fuer eine Stunde.
