### Fixed

- **Desktop: Monitoring nur fuer Admins:** Menuepunkt und Seite "Monitoring" erscheinen nur noch in einer Admin-Sitzung
  (der Server antwortet allen anderen 403); ein Aufruf von `/monitoring` zeigt ihnen das Dashboard.
- **Desktop: Namensfeld der Verbindung:** Haengt eine Verbindung an einem Server, bleibt das Namensfeld gesperrt, bis die
  Serverliste geladen ist; vorher liess sich der Anzeigename versehentlich als eigener Text speichern.
