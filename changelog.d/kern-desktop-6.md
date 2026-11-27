### Added

- **Desktop: Ping-Spalte abschaltbar:** Die Einstellung „Erreichbarkeit der Verbindungen pruefen" (Workspace & Sync) gilt je Workspace und steht standardmaessig auf an. Ist sie aus, baut die Seite Verbindungen keine Verbindungen zu den Hosts auf, und die Spalte bleibt leer.

### Fixed

- **Desktop und Web: Sitzung bleibt bei einer unbeantworteten Erneuerung:** Ein Verbindungsfehler oder ein 502, 503 oder 504 auf `/api/auth/refresh` beendet die Sitzung nicht mehr; die Anfrage scheitert mit einem Verbindungsfehler, und das naechste 401 versucht die Erneuerung erneut. Jede andere Antwort und die 30-s-Frist des Desktops beenden die Sitzung wie bisher.
- **Desktop: abgelaufenes Geraete-Zertifikat beim Login:** Statt „HTTP 400" meldet der Login `ERR_DEVICE_CERT_INVALID` mit dem Ausweg (Geraete-Identitaet zuruecksetzen, mit Einmal-Token neu registrieren). Ein abgelaufenes Zertifikat erkennt der Desktop schon vor dem Senden.
- **Desktop: Tunnel ohne Kontakt zum Tunnel-Server:** Die Anzeige zeigt einen laufenden frpc, der frps nicht erreicht oder dort abgewiesen wird, als „kein Kontakt zum Tunnel-Server" statt als verbunden.
- **Desktop: ein Fehler je RDP-Versuch:** Ein xfreerdp-Start mit Passwort meldete einen Fehlschlag teils doppelt.
- **Desktop: Benachrichtigungs-Feed laedt gebuendelt:** Viele Ereignisse waehrend eines Abrufs ergeben einen Nachlauf statt je einen Abruf, und eine aeltere Antwort ueberschreibt keine neuere.
