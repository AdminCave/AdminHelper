### Changed

- **frps prueft weitere Felder jeder Proxy-Anmeldung:** das Plugin `frps-policy` vergleicht jetzt auch die
  Benutzerliste (`allowUsers`) und den `secretKey` eines STCP-Tunnels mit dem, was der Server fuer ihn erzeugt
  (Policy-Format Version 2; Plugin und Server kommen im selben Image-Stand), und frps speichert den Host-Schluessel
  einer Anmeldung nicht mehr. Aendert sich, wer einen Server sieht, kommt ein neu angemeldeter STCP-Proxy erst nach dem
  naechsten Agent-Lauf wieder.
- **Eine Domain auf mehreren Servern braucht eine gemeinsame Gruppe:** die Tunnel-API lehnt einen HTTPS-Tunnel mit
  `409` ab, dessen Domain schon ein Tunnel eines anderen Servers traegt, wenn nicht alle dieselbe nicht leere
  `loadBalancer.group` haben; bestehende solche Tunnel laesst der Server fuer frps weg und warnt im Log (FRP-Tunnel in
  der Doku).
- **Neustart des frps-Plugins als Warnung:** startet der frps-Supervisor das Plugin neu, weil es nicht antwortet,
  schreibt er eine Warnung mit der Zahl der Neustarts (Betrieb in der Doku).
- **Agent:** nimmt einen weiteren Schluessel in der `frpc.toml` an, den eine spaetere Version des Servers schreibt;
  Agents vor dem naechsten Server-Update aktualisieren.

### Fixed

- **FRP-Server-Konfiguration mit Tunneln loeschen:** `DELETE /api/frp/server-config/{id}` endete mit `500`, wenn die
  Konfiguration Tunnel hatte; jetzt loescht es die Konfiguration samt ihren Tunneln.
