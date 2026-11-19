### Added

- **Monitoring: Web-Domains von aussen:** das Modul `web_domain` (Version 2) legt je uebernommener Domain zwei zentrale
  Checks an — `dns` (Aufloesung, Delegation, DNSSEC, alle 15 min) und `outside` (TLS-Handshake auf dem Port des vHosts,
  CAA, ARI, stuendlich). Den Ablauf des Zertifikats meldet weiter nur der Agent-Check `certificate`; Namen mit
  Special-Use-Endung (etwa `.lan`, `.home.arpa`, `.internal`) bekommen keine zentralen Checks. Katalog-Checks koennen
  damit zentral sein (`central: true`).
- **Monitoring: zentraler Sensor `tls` mit `expiry: false`:** bewertet Restlaufzeit und Ablauf nicht, prueft Name und
  Kette weiter.
