### Changed

- **Agent: Ressourcen-Deckel:** unter Linux laeuft der Agent mit `Nice=19`, IO-Klasse `idle`, hoechstens einem halben
  Kern (`CPUQuota=50%`) und `MemoryMax=256M`; ueberschreitet ein gestartetes Werkzeug den Speicher-Deckel, endet nur
  dieses, der Report geht trotzdem raus. Unter Windows laeuft der Dienst mit Prioritaet "Niedrig". Anheben per
  `systemctl edit adminhelper-agent.service`.
- **Agent: Proxmox-Backups:** den Zustand der Backup-Storages liest der Agent aus `/cluster/resources`, ohne einen
  Storage zu aktivieren; den Backup-Inhalt liest er hoechstens alle 30 Minuten.
- **Agent: Befehls-Freigabeliste:** die Collectors starten nur noch Befehle aus einer festen Liste lesender Aufrufe;
  ein anderer Aufruf startet nicht und erscheint als gescheiterter Aufruf.

