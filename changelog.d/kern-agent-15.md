### Changed

- **Monitoring: Windows-DHCP ohne IPv4-Bereich meldet unknown:** ein DHCP-Server ohne Bereich galt bisher still als
  ok; der Check zeigt jetzt unknown.
- **Monitoring: nie aktualisierte Defender-Signaturen sind critical:** der Agent meldet das Alter 65535 statt keines
  Werts; der Check zeigt critical statt unknown.
