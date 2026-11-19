### Fixed

- **Monitoring: Vorfall bleibt nach Abschalten offen:** wer einen Check abschaltet oder loescht, waehrend die Glocke
  sein Problem zeigt, schliesst jetzt den Vorfall (Entwarnung auf der Stufe des Alarms); ein wieder eingeschalteter
  Check beginnt bei `unknown`.
- **Monitoring: verlorene Glocken-Meldungen:** nimmt der Server eine Meldung fuer die Glocke nicht an, holt der
  Monitoring-Dienst sie jede Minute nach, hoechstens 20 Checks je Durchgang.
