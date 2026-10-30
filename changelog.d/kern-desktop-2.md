### Changed

- **Desktop: "Nur provisionieren" fragt den Token ab:** Der Befehl fuer Hosts mit installiertem Paket uebergibt den
  Provisionierungs-Token nicht mehr als Argument, sondern mit `--token-stdin`; `adminhelper-agent provision` liest ihn
  als erste Eingabezeile. Der Token steht wie beim Einzeiler daneben zum Kopieren. Ein Agent ohne `--token-stdin`
  meldet die unbekannte Option; dann zuerst das Paket aktualisieren.
