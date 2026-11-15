### Added

- **Monitoring: Modul `nextcloud-aio`:** Nextcloud All-in-One wird am Image des Mastercontainers erkannt. Der
  Agent zaehlt alle 5 Minuten die Container, die All-in-One dauerhaft betreibt; ein gestoppter Container ist
  `critical`, ausser waehrend des naechtlichen Backups, das sie absichtlich stoppt. Ein Backup laenger als 6 Stunden
  warnt. Der Agent prueft die Markierung des Backups nur auf Existenz und Alter und liest keine Konfiguration.
- **Monitoring: Last der Jitsi-Videobridge:** `jitsi-videobridge` v2 liest alle 5 Minuten `stress` aus `/metrics`
  an 8080; ueber 0,8 warnt. Dafuer nimmt der HTTP-Sensor den Parameter `accept` (nur `application/json`). Ein
  aelterer Agent meldet die neuen Checks als `invalid`, bis er aktualisiert ist. Doku: Monitoring, Agent (DE+EN).
