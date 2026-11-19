### Added

- **Agent: Fehlerzeilen fehlgeschlagener Dienste:** ist der Schalter fuer Fehlerzeilen an, sendet der Linux-Agent zu
  jedem fehlgeschlagenen Dienst die letzten 10 Journal-Eintraege, einmal je Ausfall und schon auf dem Agent
  geschwaerzt; unter Last setzt er das aus und holt es danach nach. Windows und FreeBSD senden keine Fehlerzeilen.

### Changed

- **SMART: schlafende Platten werden nicht mehr geweckt:** der Agent laesst eine Platte im Standby schlafen und meldet
  sie nur als schlafend; `smart_health` behaelt ihren letzten gelesenen Stand samt Status, und der Desktop zeigt
  "schlaeft, letzter Stand von ...".
