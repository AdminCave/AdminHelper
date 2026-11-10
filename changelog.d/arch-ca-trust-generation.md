### Added

- **CA-Issuer: Vertrauensgeneration unter `GET /ca/trust`:** Die Route antwortet mit mTLS hinter dem Gateway auf
  `:443` mit `{"generation":"<hex>"}`, dem SHA-256 ueber das DER der Zertifikate, die Enrollment und Erneuerung im
  Feld `chain` fuer den Scope des Client-Zertifikats ausgeben, in dieser Reihenfolge. Sie aendert sich mit
  `rotate-intermediates` und jedem Schritt von `rotate-root`. Doku: Entwickler-Architektur, Server (DE+EN), ADR 0001.

### Changed

- **Agent und Desktop: Erneuerung gleich nach einer Rotation:** Der Agent fragt in jedem Lauf nach der
  Vertrauensgeneration, der Desktop bei der Anmeldung und danach stuendlich. Nennt der ca-issuer eine andere als
  die des gehaltenen `ca.crt` bzw. der gespeicherten Kette, erneuern sie ihr Zertifikat sofort statt erst bei halber
  Laufzeit. Ein Server ohne die Route (404 oder die Web-Oberflaeche) laesst es bei der halben Laufzeit. Nach
  `rotate-intermediates` und den Schritten von `rotate-root` ist das Gateway jetzt gleich nach dem healthy
  ca-issuer neu zu starten. Doku: Betrieb, Benutzer, Troubleshooting, FRP-Tunnel, Agent-Deployment,
  Entwickler-Desktop (DE+EN).
