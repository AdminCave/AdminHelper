### Fixed

- **Server: Slash am Ende von `MONITOR_SERVICE_URL`:** Ein Slash am Ende brach den Monitoring-Cleanup nach dem
  Loeschen eines Servers und den Tag-Sync (404). Alle Aufrufe des Servers ans Monitoring bauen ihre URL jetzt an einer
  Stelle.
