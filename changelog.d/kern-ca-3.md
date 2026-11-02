### Security

- **CA: Vertrauen nur an den gefuehrten Zwischenzertifikaten:** frps und der Server nehmen Client-Zertifikate nur
  an, wenn ein aktuelles oder abgeloestes Zwischenzertifikat ihres Scopes sie ausgestellt hat. Nach
  `rotate-intermediates --compromised <scope>` und dem Neustart des `ca-issuer` gelten Zertifikate des gesperrten
  Zwischenzertifikats dort nicht mehr. Neues Volume `ca-trust` (Betrieb, CA-Rotation).
