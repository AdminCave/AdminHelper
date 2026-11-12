### Added

- **Agent: Schonung unter Last:** ist ein Host zwei Laeufe in Folge stark belastet (Load je CPU ab 2,0, ausser in
  Containern und unter Windows; I/O-Wartezeit ab 25 %, nur Linux; weniger als 10 % RAM verfuegbar), setzt der Agent
  Docker, Proxmox, ZFS, SMART, die Proben und die Erkennung aus; nach drei ruhigen Laeufen misst er wieder alles.
  Ressourcen, Systemzustand und Dienste laufen weiter. Der Report traegt den neuen Block `self.load_shed`.
- **Monitoring: Last-Schonung auswerten:** die Checks ausgesetzter Sammler behalten ihren letzten Status ohne die
  45-min-Grenze der Drossel und melden "(skipped: load shedding)", bis sie wieder bewertet werden; `agent_resources`
  warnt nach 30 min Schonung, die Metrik `monitor_agent_load_shed` zeigt den Zustand. Ein Report ohne den Block
  bleibt wie bisher. Doku: Agent, Monitoring (DE+EN).
