### Changed

- **Ein Name je Server, abgeleitete Namen ueberall:** ein Server braucht nur noch seinen Namen (am besten seinen FQDN);
  seine Adresse folgt dem Namen, ausser eine abweichende (IP, interner Name) ist eingetragen, und ein Name ist nur
  einmal vergeben (ohne Gross-/Kleinschreibung). Verbindungen eines Servers und Tunnel tragen nur noch einen optionalen
  Zusatz und heissen "{Server} · {Zusatz}", ohne Zusatz "{Server} · SSH|RDP|Web", ueber einen Tunnel mit "(FRP)" — eine
  Umbenennung des Servers erreicht alle. Die API gibt den Anzeigenamen als `name`, den gespeicherten Zusatz als `label`
  und bei Servern `customHostname` aus; Clients von vorher arbeiten weiter. Namen, die nur den Server oder den Tunnel
  kopierten (etwa "… (via FRP)"), werden mit dem Update zum leeren Zusatz.
- **FRP kennt Server und Tunnel an ihren IDs:** `user` in frpc ist die Server-ID, der Proxy-Name die Tunnel-ID, frps
  fuehrt einen Proxy als "{Server-ID}.{Tunnel-ID}"; eine Umbenennung aendert keine FRP-Konfiguration mehr. Mit dem Update
  wechseln alle Tunnel einmal: Agents holen ihre neue frpc.toml beim naechsten Lauf, der Desktop sein Besucher-Bundle
  beim naechsten Abgleich; die lokalen Ports bleiben. Eingebettetes RDP ueber einen Tunnel fragt einmal erneut nach dem
  Zertifikat, weil die Pins den Tunnel jetzt an seiner ID nennen.
- **Desktop:** der Server-Dialog fragt Name und optional eine Adresse; Verbindungs- und Tunnel-Dialoge fragen einen
  optionalen Zusatz und zeigen den Anzeigenamen vorab; "nach Server" gruppiert Verbindungen unter ihrem Server, auch
  die ueber einen Tunnel.

### Fixed

- **FRP-Statusseite:** ein Proxy, dessen Server- oder Tunnelname einen Punkt trug (ein FQDN), fand seinen Tunnel nicht;
  Proxies werden jetzt ganz ueber "{Server-ID}.{Tunnel-ID}" zugeordnet.
- **Server-API:** `PUT /api/servers/{id}` mit `name: null` antwortete 500, jetzt 422.
