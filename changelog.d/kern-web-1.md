### Fixed

- **Web: neue Anmeldung bleibt bestehen:** Eine Anmeldung beginnt im Web immer eine neue Sitzung, auch wenn der
  Client noch ein Token haelt; eine Anfrage aus der Zeit davor, die erst danach mit 401 beantwortet wird, beendet
  die neue Sitzung nicht mehr. Ebenso uebernimmt eine Anfrage der neuen Sitzung nicht mehr die Antwort eines
  Token-Refresh, der noch aus der alten Sitzung laeuft.
