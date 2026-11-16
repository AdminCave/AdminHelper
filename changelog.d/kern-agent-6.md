### Changed

- **Agent: Checks mit Zugangsdaten:** der Waechter fuer Proben am eigenen Host ist fuer Checks mit Zugangsdaten
  strenger (Linux, FreeBSD, Windows, auch Unix-Sockets); die Regel und ihr Ausweg ueber ein Unit- oder Container-Ziel
  stehen im Sicherheitsmodell der Monitoring-Seite. Checks, die sie nicht erfuellen, melden `not_allowed`.

### Fixed

- **Agent: lauschende Sockets unter Linux:** haelt ein Prozess eine Socket fuer einen anderen (etwa systemd bei
  Socket-Aktivierung), sieht der Waechter jetzt alle Prozesse der Socket statt zufaellig einen davon.
- **Agent: Discovery bei Containern mit vielen Ports:** lauscht ein Container auf mehr als 64 Ports, meldet der Agent
  sie als unbekannt; der Monitoring-Dienst wertete die bisher gekuerzte Liste als vollstaendig und Ports darueber als
  fehlend.
