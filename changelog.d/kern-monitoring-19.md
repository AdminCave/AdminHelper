### Changed

- **Monitoring: Probe-Checks nur aus Modulen:** `probe`-Checks entstehen nur noch durch die Uebernahme eines
  Katalog-Moduls. Die Check-API legt keinen an (422), Templates nehmen keine `probe`-Definition (422), und an einem
  bestehenden Probe-Check aendert die API nur Regeln, Intervall, Timeout, Name, Beschreibung, Schweregrad, an/aus und
  `consecutive_*`. Der Plan an den Agent traegt nur Checks eines Moduls. Doku: Monitoring (DE+EN).

### Security

- **Agent: Zugangsdaten fuer Proben an ihr Ziel gebunden:** Beim ersten Einsatz nach `monitor credential set`
  bindet der Agent die Zugangsdaten an das Ziel des Checks; ein anderes Ziel bekommt sie nicht (`not_allowed`), bis
  sie neu gesetzt werden. Doku: Monitoring, Agent (DE+EN).
- **Agent: weitere Dienste, die eine Probe nie anspricht:** die API- und Konsolen-Dienste von Proxmox VE, Backup
  Server und Mail Gateway, weitere VM-Prozesse und Kubernetes-Knotendienste, Unix-Sockets in den
  Laufzeitverzeichnissen von Container-, VM-, Bus- und Sitzungsdiensten (auch ueber einen Link) und unter Linux
  veroeffentlichte Docker-Ports, die auf einen gesperrten Container-Port weiterleiten. Doku: Monitoring, Agent
  (DE+EN).
