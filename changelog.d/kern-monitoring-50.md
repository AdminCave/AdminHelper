### Added

- **Monitoring: Fehlerzeilen und „Mehr Log“ unter Windows und FreeBSD:** der Windows-Agent schickt zu einem
  gestoppten Auto-Start-Dienst mit Exit-Code bis zu 10 geschwaerzte Zeilen aus System- und Application-Log, einmal je
  Ausfall. „Mehr Log“ im Desktop liest je Plattform des Servers das Journal (Linux), das Ereignisprotokoll ueber
  PowerShell (Windows) oder `/var/log/messages` (FreeBSD, OPNsense), weiter mit den Rechten des SSH-Logins.
