### Added

- **Monitoring: vHosts von nginx und Apache im Docker-Container:** die Erkennung meldet sie auf den veroeffentlichten
  Ports des Hosts, und `web_domain` prueft sie wie die des Hosts. Der Agent liest die Konfiguration und die
  Zertifikatsdatei ueber das Archiv des Containers (`docker cp`), startet im Container nichts und laesst Dateien, die
  nach Schluessel aussehen, ungelesen.
