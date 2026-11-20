### Changed

- **Monitoring: stabile Objekte für Container und Gast-Backups:** Ein Compose-Container ist über Projekt, Dienst und
  Nummer bekannt und bleibt nach einer Neuanlage dasselbe Objekt; ein Gast-Backup über Cluster und VMID, auch nach dem
  Umzug auf einen anderen Node. Nach dem Agent-Update erscheinen diese Objekte einmal neu, die alten gelten als
  verschwunden.
- **Monitoring: Glocke beim Ausschalten und Löschen:** Die Entwarnung an die Glocke geht nach der Antwort; ein nicht
  erreichbarer Hub hält das Ausschalten oder Löschen eines Checks nicht mehr auf.

### Fixed

- **Monitoring: Verlauf:** Zustandswechsel desselben Objekts innerhalb einer Minute erscheinen wieder einzeln, und
  „nicht erhoben“ steht in den Metriken als ok statt als unbekannt.
- **Monitoring: Zustand gleichzeitiger Ergebnisse:** Das erste Ergebnis eines Checks und das Aufräumen verschwundener
  Objekte laufen geordnet mit anderen Ergebnissen desselben Checks.
