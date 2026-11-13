### Added

- **Monitoring: mehr App-Checks:** Nextcloud bekommt Container- und Status-Check auch ohne Compose oder unter anderem
  Dienstnamen; Bitwarden fragt `/alive` am nginx (8443 mit TLS, sonst 8080); das OnlyOffice-Image fragt
  `/healthcheck` auf 8000, sobald der Agent den Port im Container lauschen sieht; Wiki.js 2 fragt `/healthz` (mit
  Datenbank-Pool), ein Wechsel auf Wiki.js 3 macht den Fund geaendert und schaltet den Check beim Uebernehmen ab.
- **Agent: Inventar mit Unit und lauschenden Container-Ports:** je Socket die systemd-Unit des Prozesses, je laufendem
  Container mit eigenem Netz die TCP-Ports, auf denen darin etwas lauscht (nur Linux).

### Fixed

- **Monitoring: Port einer App-Unit kein eigener Fund mehr:** Der Port einer erkannten Anwendung aus dem Paket (etwa
  `gitea.service` auf 3000, slapd, Odoo) erscheint nicht mehr zusaetzlich als Fund des Moduls `port` — ein
  uebernommener solcher Fund wird nach zwei Scans `gone`.
