### Fixed

- **Monitoring: doppelter Query-Parameter ergibt 422:** ein Parameter, den die API als einzelnen Wert beschreibt
  (etwa `offset` oder `limit`), wird bei mehrfacher Angabe mit 422 abgewiesen, statt still den letzten Wert zu nehmen.
