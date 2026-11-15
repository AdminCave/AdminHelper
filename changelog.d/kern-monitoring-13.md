### Added

- **Monitoring: Modul `unifi-os-server`:** Ein UniFi OS Server wird an der Unit `uosserver.service` erkannt. Alle
  5 Minuten liest der Agent ueber die Integration API der Network-Anwendung, wie viele Geraete offline sind: ein
  Gateway offline ist `critical`, ein Geraet offline, dessen Uplink selbst online ist, `warning`. Dazu Dienst und
  Zertifikat des Web-Ports 11443. Der API-Key bleibt auf dem Host; weil ein Key nicht nur lesen kann, schickt der
  Agent nur `GET` auf einer festen Liste lesender Pfade und meldet nur Zahlen. Geprueft mit UniFi OS Server 5.1.42.
  Doku: Monitoring, Agent (DE+EN).

### Changed

- **Agent: rootless Podman:** Der Waechter weist Ports, die `pasta` weiterleitet, nicht mehr pauschal ab, sondern
  liest den Zielport aus den Argumenten von `pasta` und weist ein gesperrtes oder unklares Ziel ab.
