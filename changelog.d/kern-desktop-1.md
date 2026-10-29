### Changed

- **Desktop: Verbindungslisten hoechstens 16 MiB:** Der Abgleich mit dem Server und mit einer Sync-Quelle liest
  die Liste der Verbindungen bis 16 MiB, wie ein Playbook; eine groessere Antwort ist ein Fehler, und die
  bisherigen Verbindungen bleiben.
