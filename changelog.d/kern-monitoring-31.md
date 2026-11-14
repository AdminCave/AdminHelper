### Added

- **Monitoring: täglicher Konfigurationstest für BIND, Unbound, dnsmasq, keepalived, Squid und fail2ban:** der Agent
  startet einmal am Tag den Konfigurationstest des Dienstes (etwa `named-checkconf`, `squid -k parse`) und meldet nur,
  ob die Konfiguration lädt; eine, die nicht lädt, ist `warning`, bevor der nächste Neustart oder Reload scheitert.
