### Fixed

- **Agent: Schonung unter Last auf ZFS-Hosts:** Der ZFS-ARC oberhalb seines Minimums (`c_min`) zaehlt fuer die Schonung
  unter Last als verfuegbarer Speicher (Linux und FreeBSD). Ein PVE- oder FreeBSD-Host mit warmem ARC setzte vorher
  Docker, Proxmox, ZFS, SMART, Proben und Erkennung dauerhaft aus. `memory_percent` im Report bleibt unveraendert.
