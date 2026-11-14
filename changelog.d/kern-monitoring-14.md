### Added

- **Monitoring: Windows-Rollen und Windows-Backups:** die Erkennung listet unter Windows die Dienste des
  Dienst-Managers, und neue Katalog-Module pruefen Windows Update, Ereignisse und Maschinenzertifikate jedes
  Windows-Hosts, Active Directory (Replikation dieses DCs), DHCP, DNS, IIS, RDS-Lizenzen, Hyper-V, DFS-R, SQL Server
  (Standardinstanz), WSUS, Dateiserver (Speicherplaetze, Kontingente, Schattenkopien, BitLocker), Druckserver,
  Defender, Windows-Server-Sicherung und Veeam Agent fuer Windows, dazu CUPS unter Linux. Der Agent liest nur feste
  WMI-Abfragen, Ereigniszaehler, den Zertifikatsspeicher und je eine feste Zeile von `repadmin`, `appcmd` und
  `lpstat`, ohne PowerShell und ohne WMI-Methoden; zum Server gehen nur Zahlen, Alter und Ja/Nein-Werte. Nicht an
  einem Windows Server mit diesen Rollen geprueft. Doku: Monitoring, Abschnitte Erkennung und App-Module; Agent
  (DE+EN).
