### Changed

- **ca-issuer: Client-Identitaet nur vom Gateway:** Der ca-issuer wertet die Zertifikats-Header des Gateways wie der
  Server nur aus, wenn die Anfrage direkt vom Dienst `gateway` kommt; uvicorn im ca-issuer wertet keine
  Forwarded-Header mehr aus.
