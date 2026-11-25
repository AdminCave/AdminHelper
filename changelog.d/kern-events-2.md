### Changed

- **Server: verworfene Events:** Ist die Event-Warteschlange voll, loggt der Server je Ansturm nur das erste verworfene
  Event und eine Minute spaeter eine Zusammenfassung mit Anzahl und Typen, statt einer Warnung je Event; alle Admins
  bekommen dazu eine Notiz in der Glocke, hoechstens eine in 15 Minuten.
