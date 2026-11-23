### Changed

- **Monitoring: stabile Objekte fuer Container und Gast-Backups:** Ein Compose-Container ist ueber Projekt, Dienst und
  Nummer bekannt und bleibt nach einer Neuanlage dasselbe Objekt; ein Gast-Backup ueber Cluster und VMID, auch nach dem
  Umzug auf einen anderen Node. Nach dem Agent-Update erscheinen diese Objekte einmal neu, die alten gelten als
  verschwunden.
- **Monitoring: Glocke beim Ausschalten und Loeschen:** Die Entwarnung an die Glocke geht nach der Antwort; ein nicht
  erreichbarer Hub haelt das Ausschalten oder Loeschen eines Checks nicht mehr auf.

### Fixed

- **Monitoring: Verlauf:** Zustandswechsel desselben Checks innerhalb einer Minute erscheinen wieder einzeln, und
  „nicht erhoben“ steht in den Metriken als ok statt als unbekannt.
- **Monitoring: Zustand gleichzeitiger Ergebnisse:** Das erste Ergebnis eines Checks und das Aufraeumen verschwundener
  Objekte laufen geordnet mit anderen Ergebnissen desselben Checks.
