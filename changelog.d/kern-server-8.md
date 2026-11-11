### Fixed

- **Server: doppelter Query-Parameter:** ein Query-Parameter, den das Schema als Einzelwert beschreibt, ergibt bei
  mehrfacher Angabe 422 statt still den letzten Wert zu nehmen, wie schon im Monitoring.
