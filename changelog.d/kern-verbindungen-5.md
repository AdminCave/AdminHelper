### Changed

- **Server: Zertifikat-Vertrauen nur per Benutzer-Login:** ein API-Schluessel darf `trustCert` einer Verbindung nicht
  mehr einschalten (`403`); unveraendert zuruecksenden oder ausschalten geht weiter. Traegt eine Verbindung
  `trustCert`, darf ein Schluessel auch Host, Port, Typ, Benutzername und Domaene nicht aendern.
