### Security

- **Server: Vertrauen in Proxy- und Gateway-Adressen gehaertet:** Die Namensaufloesung der vertrauten Adressen haelt
  sich auch im Fehlerfall an ihr fail-closed-Verhalten.

### Added

- **Server: abgewiesener Token-Refresh im Audit-Log:** Ein Refresh, den der Server unter `MTLS_ENFORCE=true` mangels
  Client-Zertifikat abweist, erscheint wie ein so abgewiesener Login im Audit-Log, als `auth.refresh_failed`.

### Fixed

- **Server: Anmeldung und Refresh ohne 500:** Ein sehr grosser `WEB_SESSION_MAX_HOURS` und ein Refresh-Token, der
  waehrend der Pruefung ablaeuft, fuehren nicht mehr zu einem Serverfehler. Der `403` ohne Client-Zertifikat an Login,
  Refresh und Bootstrap nennt keinen Scope mehr, den er nicht prueft.
