### Added

- **Monitoring: Module und Erkennung:** der Agent erstellt etwa einmal am Tag (oder auf Anforderung) ein Inventar
  seines Hosts — Units, lauschende Ports, Container, Marker, erkannte Protokolle; nur Namen, Ports und Zustaende, nie
  Konfigurationsinhalte, Kommandozeilen oder Umgebungsvariablen. Der Monitoring-Dienst gleicht es mit seinem
  Modul-Katalog ab und legt Funde in einen Eingang (`/api/monitoring/findings`, nur Admins); erst das Uebernehmen legt
  Checks an, geloescht wird nie etwas. Der Katalog bringt zunaechst das Modul `port` (lauschender Port ohne bekannten
  Dienst) mit.
- **Monitoring: Check-Typ `probe`:** eingebaute, nur lesende Sensoren des Agents (HTTP, TLS, Protokoll, Unix-Socket,
  DNS, Datenbank, Journal-Zaehler, Units, Prozesse, Container, Zertifikats- und Dateialter) messen Dienste des
  eigenen Hosts nach einem Plan, den der Agent ueber `GET /api/monitoring/agent/{server_id}/plan` holt. Ziele sind
  nur Loopback, eigene Adressen und eigene Container. Neue Checks aus einem Katalog-Update laufen still mit, bis der
  Fund uebernommen ist.
- **Agent: `monitor credential set|delete|list`:** Zugangsdaten fuer Probes bleiben auf dem Host; der
  Monitoring-Dienst erfaehrt nur, welche Namen gespeichert sind.
- **Agent: Selbstdrosselung:** der Agent misst, was jeder Collector je Lauf kostet, meldet es
  (`monitor_agent_collector_*`) und laesst Docker, Proxmox, ZFS, SMART und die Erkennung bei wiederholten
  Zeitlimit-Treffern seltener laufen; die Checks darauf behalten dann ihren Zustand. Report-Version 4; aeltere Agents
  arbeiten mit dem neuen Monitoring-Dienst weiter wie bisher, nur ohne Module.
