### Added

- **Monitoring: taeglicher Konfigurationstest fuer BIND, Unbound, dnsmasq, keepalived, Squid und fail2ban:** der Agent
  startet einmal am Tag den Konfigurationstest des Dienstes (etwa `named-checkconf`, `squid -k parse`) und meldet nur,
  ob die Konfiguration laedt; eine, die nicht laedt, ist `warning`, bevor der naechste Neustart oder Reload scheitert.
