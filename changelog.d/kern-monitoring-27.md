### Fixed

- **Monitoring: Fehlertext eines Alarmkanals wird immer gespeichert:** enthaelt die Antwort eines Kanals Zeichen, die
  die Datenbank nicht aufnimmt, steht an ihrer Stelle ein Ersatzzeichen; der Alarmdurchlauf geht nicht mehr verloren.
- **Monitoring: aeltere Zeilen mit ungueltigen Unicode-Escapes lesbar:** Pruefungen, Status und Vorlagen mit solchen
  gespeicherten Werten liefern ein Ersatzzeichen statt eines Serverfehlers.
- **Monitoring: Dienste-Fehlerzeilen nachgehaertet:** das Ausschalten der Fehlerzeilen eines Servers und ein
  gleichzeitig eingehender Dienste-Bericht laufen nacheinander; nach dem Ausschalten bleiben keine Zeilen sichtbar.
