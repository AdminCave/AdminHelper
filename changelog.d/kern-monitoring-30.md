### Added

- **Monitoring: deeper application checks:** OnlyOffice compares its health check answer, Keycloak,
  Mattermost and Vaultwarden are checked over plain HTTP or TLS, whichever their port speaks, OpenLDAP
  rates its certificate by the share of its lifetime left, and Pi-hole, AdGuard Home, Unbound and BIND
  are asked for `localhost` on their own port 53 every five minutes. An agent older than the monitoring
  service leaves these checks `unknown` ("invalid") until it is updated, the four web checks and OpenLDAP's
  certificate check too.
