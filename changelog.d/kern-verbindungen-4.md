### Changed

- **Server: bestimmte Verbindungs-Optionen nur per Benutzer-Login:** ein API-Schluessel darf Agent-Forwarding,
  Weiterleitungen, den Jump-Host, Laufwerke, Drucker, das RD-Gateway und das Ausschalten von NLA nicht mehr setzen
  oder aendern (`403`); unveraendert zurueckgesendete Werte gehen weiter durch. Traegt eine Verbindung eine dieser
  Optionen, darf ein Schluessel auch Host, Port, Typ, Benutzername und Domaene nicht aendern.
- **Server: Sitzungsverlauf nur fuer Benutzer-Konten:** `GET /api/connections/{id}/sessions` antwortet jedem
  API-Schluessel mit `403`.
- **Server und Desktop: IPv6 im Jump-Host nur im letzten Hop:** eine IPv6-Adresse in eckigen Klammern in einem
  frueheren Hop wird abgelehnt (`422` am Server, ein Fehler vor dem Start am Desktop).
