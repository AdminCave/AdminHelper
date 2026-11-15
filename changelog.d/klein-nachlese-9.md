### Fixed

- **Monitoring: Socket-Pfad in Bytes:** der Katalog prueft den Pfad eines Unix-Socket-Checks wie der Agent in Bytes
  (107), nicht in Zeichen; ein Pfad mit Umlauten, der zu lang ist, wird am Server abgewiesen statt beim Agent als
  `invalid`.
