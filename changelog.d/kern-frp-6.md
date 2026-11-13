### Added

- **FRP: Tunnel-Schluessel je Host erneuern:** der Schluessel, mit dem frps die Proxys eines Hosts annimmt, hat je
  Server eine Generation. Jede Provisionierung erneuert ihn, ein Admin auch von Hand im Desktop (Reiter Tunnel,
  „Tunnel-Schluessel erneuern“) oder per `POST /api/servers/{id}/frp-key/rotate`. Der Agent holt die neue `frpc.toml`
  beim naechsten Lauf; von Hand verteilte `frpc.toml` sind danach neu zu verteilen. Bestehende Hosts behalten ihren
  Schluessel bis zur ersten Erneuerung.
