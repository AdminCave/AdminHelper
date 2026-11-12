### Security

- **Monitoring: Proben auf dem eigenen Host enger gefasst:** der Agent verbindet sich nicht mit einem Port einer
  eigenen Adresse, auf dem kein Prozess lauscht (die Messung scheitert, der Check wird rot). Er erkennt weitere
  Weiterleiter (`systemd-socket-proxyd`, sslh, rinetd, redir), auch hinter einem Unix-Socket, und unter Windows die
  Portweiterleitung von `iphlpsvc`. Unter Linux prueft er nach dem Verbindungsaufbau, welcher Socket die Verbindung
  angenommen hat; ist es nicht der lauschende, setzt er sie zurueck und weist den Port eine Stunde lang ab (ein
  Neustart des Agents hebt das auf).
- **Monitoring: zentrale Checks:** der Dienst erkennt ein eigenes NAT64-Praefix der Umgebung ueber den
  System-Resolver (RFC 7050) und haelt eine Adresse darunter nur fuer oeffentlich, wenn die eingebettete
  IPv4-Adresse es ist.

### Changed

- **Monitoring: RDAP und Delegationspruefung:** der `rdap`-Check folgt einer Weiterleitung des RDAP-Servers
  hoechstens dreimal und nur zu einer https-URL, jedes Ziel wieder nur an oeffentlichen Adressen. Die
  Delegationspruefung fragt jede Adresse nur einmal, auch wenn mehrere Nameserver sie teilen. Doku: Monitoring
  (DE+EN).
