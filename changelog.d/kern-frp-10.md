### Changed

- **FRP: frps prueft auch die Anmeldung eines Hosts:** Die vom Server erzeugte `frpc.toml` traegt den Schluessel des
  Hosts zusaetzlich an der Wurzel (`metadatas.ahProxyKey`, nur solange der Host aktive Tunnel hat), und frps legt
  jede Anmeldung eines Clients dem Plugin `frps-policy` vor: ein Host meldet sich nur mit seinem Schluessel an,
  andere Benutzer (der STCP-Visitor des Desktops) brauchen keinen. Das frps-Log zeigt dazu `login admitted` bzw.
  `login refused` mit Grund. **Update-Reihenfolge:** erst die Agents auf mindestens v0.47.0, dann den Server;
  eine von Hand verteilte `frpc.toml` danach neu verteilen.
