### Fixed

- **Agent: Schonung unter Last auf ZFS-Hosts:** Der ZFS-ARC oberhalb seines Minimums (`c_min`) zaehlt fuer die Schonung
  unter Last als verfuegbarer Speicher (Linux und FreeBSD), ausser in einem Container: dort ist `arcstats` der ARC des
  Hosts, der Speicher aber das Limit des Containers. Ein PVE- oder FreeBSD-Host mit warmem ARC setzte vorher Docker,
  Proxmox, ZFS, SMART, Proben und Erkennung dauerhaft aus. `memory_percent` im Report bleibt unveraendert.
- **Agent: Report-Versand nach einem Fehler:** Nach einem gescheiterten Versand liest der naechste Lauf die
  stuendliche Update-Zaehlung und den Backup-Index nicht erneut, sondern erst, wenn sie wieder faellig sind.
- **Agent (Windows): Self-Update gegen die Registrierungs-CA:** Das Self-Update prueft die TLS-Verbindung zum Repo-Port
  8445 gegen die bei der Registrierung erhaltene CA, wie der Report-Versand. Vorher galt dort nur das konfigurierte
  `cacert`.
- **Agent: englische Meldungen:** `provision` und die Befehlshilfen (`--help`) geben ihre Meldungen jetzt einheitlich
  englisch aus, wie die uebrigen Agent-Texte.
