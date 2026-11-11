### Fixed

- **Desktop: eingebettetes RDP uebersteht die Groessenaenderung an xrdp:** sendet der Server waehrend der
  Reaktivierung Daten auf einem statischen Kanal, verarbeitet die Sitzung sie danach, statt die Verbindung
  abzubrechen.
- **Desktop: H.264 aus bleibt aus, auch waehrend eine Sitzung startet:** wird H.264 abgeschaltet, waehrend eine
  Sitzung gerade die Einstellungen gelesen hat, laedt sie die OpenH264-Bibliothek nicht mehr herunter.
