### Changed

- **Agent: RAM ohne rueckforderbaren ARC:** Unter Linux und FreeBSD zaehlt der ZFS-ARC oberhalb von `c_min` als
  frei; `memory_percent` und `memory_used_mb` liegen auf ZFS-Hosts deshalb unter dem, was `free` als belegt zeigt.
  Windows und Hosts ohne ARC melden unveraendert.

### Fixed

- **Agent: Self-Update eines enrollten Hosts:** Der Abruf des Updates nutzt dieselbe TLS-Konfiguration wie die
  uebrigen Verbindungen des Agents zum Gateway.
- **Agent: Netz-Mounts unter FreeBSD:** Ein haengender Mount wird erst wieder abgefragt, wenn seine letzte Abfrage
  geantwortet hat, so sammelt ein dauernd laufender Agent keine Threads an; ein lokaler Mount unterhalb eines
  Netz-Mounts wird mit Frist gelesen.
