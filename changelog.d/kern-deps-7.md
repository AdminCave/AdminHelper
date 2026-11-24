### Changed

- **Server und Monitoring: kleinere Images:** Die ungenutzten Pakete `python-multipart` (Server) und `greenlet`
  (Server und Monitoring, kam ueber `sqlalchemy[asyncio]` ohne Async-Engine) fallen aus den Locks;
  `pytest-asyncio` aus den Test-Abhaengigkeiten des Servers.
