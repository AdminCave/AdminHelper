### Changed

- **Zertifikate: Erneuerung mit Besitznachweis:** Agent und Desktop signieren bei der Erneuerung ihres Zertifikats
  die neue CSR mit dem Schluessel des bisherigen Zertifikats (`proof` an `/ca/renew`); der ca-issuer prueft den
  Nachweis. Eine Erneuerung ohne Nachweis nimmt er fuer ein Release noch an, damit aeltere Clients weiter erneuern.
- **ca-issuer: Entrypoint-Test:** Ein Test haelt fest, dass der ca-issuer weitergeleitete Absender-Header nicht
  uebernimmt.
