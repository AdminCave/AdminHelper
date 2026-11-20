### Fixed

- **Agent: fehlgeschlagene Units nicht abfragbar:** Scheitert unter Linux `systemctl list-units --state=failed`,
  meldet der Agent den Grund; der Dienste-Check steht dann auf `unknown` statt „All services OK“.
