### Fixed

- **Agent (Windows): Zugangsdaten trotz kurz gesperrter Datei:** `monitor credential set` und das Lesen der
  Zugangsdaten warten bis zu zwei Sekunden, wenn ein Virenscanner oder Indexer `credentials.json` gerade haelt, statt
  mit `Access is denied` abzubrechen.
