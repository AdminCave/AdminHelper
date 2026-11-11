### Security

- **Monitoring: strengere Bindung von Modul-Checks:** Passen mehrere Container eines Compose-Dienstes, bindet das
  Uebernehmen keinen davon; der Grund nennt die Kandidaten.
- **Monitoring: strengere Pruefung von Agent-Reports und Vorlagen:** Ein Agent-Report ist hoechstens 10 MiB gross,
  auch innerhalb des Compose-Netzes (sonst 413). Eine Probe-Vorlage wird nach dem Ersetzen ihrer Platzhalter erneut
  geprueft; haelt sie nicht, entsteht kein Check, und das Zuruecksetzen eines solchen Checks antwortet mit 409.

### Fixed

- **Agent: Zugangsdaten lesen ohne zu blockieren:** Unter Windows scheitert das Speichern von Zugangsdaten nicht mehr,
  waehrend ein anderer Prozess die Datei liest; unter Linux haengt der Agent nicht an einer FIFO statt der Datei.
- **Monitoring: Log-Sensor und Probe-Ziele:** Die API nimmt fuer den Log-Sensor nur Units und Filter an, die der Agent
  ausfuehrt (sonst 422), statt dass der Check dauerhaft `unknown` bleibt.
- **Monitoring-Erkennung:** Nach einem unvollstaendigen Scan kommt der naechste nach 2 bis 4 Stunden statt erst nach
  24 bis 48. Wird ein Dienst ausser ueber seine Unit auch ueber Container, Prozess oder Markerdatei erkannt, laesst ein
  Stopp der Unit seinen Fund unveraendert, statt ihn als geaendert zu melden.
- **Monitoring: gebremste Sammler:** Ein vom Agenten gebremster Sammler laesst den Status seiner Checks hoechstens
  45 Minuten stehen; danach werden sie wieder bewertet.
