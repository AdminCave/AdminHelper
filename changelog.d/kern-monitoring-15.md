### Security

- **Agent: eine Befehls-Freigabeliste fuer alle Werkzeugaufrufe:** Auch die Probe-Sensoren (Log, Dienst, Container,
  Datenbank) und die Erkennung starten Werkzeuge nur noch ueber die feste Befehls-Freigabeliste der Collectors; ein
  Aufruf ausserhalb der Liste startet nicht.
- **Agent: strengere Zuordnung von Probe-Zielen:** Der Agent ordnet einen Prozess einem Container nur zu, wenn alle
  cgroups passen, die beide nennen. Einen Port, den allein systemd haelt (Socket-Aktivierung), weist er als
  `not_allowed` ab, weil der Dienst dahinter nicht feststeht.

### Fixed

- **Agent-Erkennung: veroeffentlichte Ports nach Adresse und Port:** Veroeffentlichen zwei Container denselben Port
  auf verschiedenen Host-Adressen, ordnet die Erkennung jeden Listener dem Container seiner Adresse zu.
