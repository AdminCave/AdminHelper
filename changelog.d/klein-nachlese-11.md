### Fixed

- **Monitoring: Windows DNS Server ohne doppelten Fund:** Port 53 gehoert dem Modul `windows-dns`; er erscheint nicht
  zusaetzlich als Port-Fund, weil Windows-Sockets keinen Dienst nennen.
