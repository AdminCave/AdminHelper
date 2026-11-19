### Added

- **Monitoring: Objekte der Checks:** Ein Check fuehrt die Dinge, die er bewertet, als Objekte mit eigenem, gedaempftem
  Zustand: Platten (`smart_health`), ZFS-Pools, Gast-Backups (`proxmox_backup`), Container, CPU, RAM, Mounts, Sensoren,
  Dienste (`service_process`), Neustart, Updates und Uhrzeit. Ein Check ohne Objekte steht als ein Objekt. Was ein
  vollstaendiges Ergebnis nicht mehr nennt, gilt als verschwunden und wird nach 30 Tagen geloescht.
- **Monitoring: Objekt-API:** `GET /api/monitoring/objects` (admin-only) liefert die Objekte, schlechteste zuerst, mit
  Filtern nach Server, Check und Art, verschwundene auf Wunsch, mit `limit`/`offset`; der Status kennt dort zusaetzlich
  `not_collected` (nicht erhoben).
- **Monitoring: Statuswechsel-Log:** Jeder gedaempfte Statuswechsel eines Checks und eines Objekts wird protokolliert,
  unabhaengig von den Alert-Regeln, und 90 Tage aufbewahrt; das Update uebernimmt den bisherigen Alert-Log einmal.

### Changed

- **Monitoring: Verlaufsmarken:** Die Statusmarken im Verlauf eines Servers kommen aus dem Statuswechsel-Log und zeigen
  jetzt auch Wechsel ohne Alert-Regel, im Wartungsfenster und von oder nach `info`; das erste Ergebnis eines neuen
  Checks zaehlt nur, wenn es ein Problem ist.
