### Changed

- **Desktop: "Nur provisionieren" fragt den Token ab:** Der Befehl fuer Hosts mit installiertem Paket uebergibt den
  Provisionierungs-Token nicht mehr als Argument, sondern mit `--token-stdin`; `adminhelper-agent provision` liest ihn
  als erste Eingabezeile. Der Token steht wie beim Einzeiler daneben zum Kopieren. Ein Agent ohne `--token-stdin`
  meldet die unbekannte Option; dann zuerst das Paket aktualisieren.

### Fixed

- **Desktop: Zuruecksetzen der Geraete-Identitaet meldet ein gescheitertes Loeschen:** Konnte der Desktop die
  Identitaet nicht aus dem Schluesselbund loeschen, meldete das Zuruecksetzen bisher trotzdem Erfolg. Jetzt zeigt es
  einen Fehler; hat der Server die Identitaet schon widerrufen, sagt die Meldung das. Der Desktop versucht dabei alle
  Eintraege der Identitaet zu loeschen, nicht nur bis zum ersten Fehler.
