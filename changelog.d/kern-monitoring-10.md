### Added

- **Monitoring: Module fuer Netz, DNS/DHCP/Zeit und Reverse Proxies:** die Erkennung findet WireGuard, OpenVPN,
  fail2ban, CrowdSec, keepalived, Tailscale, Headscale, BIND, Unbound, Pi-hole, AdGuard Home, Kea, dnsmasq,
  isc-dhcp-server, chrony, NTPsec, Caddy, Traefik, Nginx Proxy Manager und Squid. Neben Unit oder Container liest der
  Agent je Dienst Kennzahlen auf dem eigenen Host: Alter der WireGuard-Handshakes, verbundene OpenVPN-Clients,
  fail2ban-Jails ohne Logdatei, veraltete CrowdSec-Bouncer, gehaltene keepalived-Adressen, Tailscale-Verbindung und
  Schluesselablauf, Zonen und rekursive Clients von BIND, SERVFAIL-Anteil von Unbound, Auslastung der Kea- und
  dnsmasq-Pools, Synchronisation und Offset von chrony und NTPsec, Ablauf der Zertifikate von Caddy, Traefik und Nginx
  Proxy Manager, fehlschlagende Caddy-Upstreams und der Cache-Manager von Squid. Dafuer startet der Agent nur
  Lesekommandos aus einer festen Liste mit festen Argumenten; zum Server gehen nur Zahlen, nie Schluessel, Adressen,
  Namen oder Konfigurationsinhalte. Die neuen Checks brauchen einen Agent in der Version des Monitoring-Dienstes; ein
  aelterer meldet sie `unknown`. Doku: Monitoring, Abschnitt App-Module (DE+EN).
