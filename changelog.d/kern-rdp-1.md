### Added

- **Desktop: RDP im Tab (Vorschau):** Die Einstellung *RDP -> Client fuer RDP* oeffnet RDP-Verbindungen wahlweise
  in einem Tab von AdminHelper statt im RDP-Client des Systems (Standard bleibt der Client des Systems, bis die
  Pruefung unter Windows durch ist); das Menue am Verbinden-Knopf waehlt den Weg auch fuer einen einzelnen Start.
  Der Tab zeigt das Bild per WebGL, leitet nach einem Klick Tastatur und Maus weiter (Strg+Alt+Pos1 gibt die
  Tastatur frei) und hat Strg+Alt+Entf, Screenshot, Verbindungsinfo, Leistungsprofil und Trennen; die Fusszeile
  zeigt Bildrate, Aufloesung, Bandbreite und Latenz. Ein unbekanntes oder geaendertes Server-Zertifikat bestaetigt
  der Nutzer im Tab. Ohne gespeichertes Passwort fragt der Tab; ein getipptes Passwort bleibt nur im Tab. Neue
  Befehle `rdp_session_screenshot` und `rdp_session_info`, `rdp_session_start` nimmt ein optionales `password`,
  der Bild-WebSocket meldet `stats` und nimmt `cad`. Doku: Desktop-Entwicklerdoku und Admin-Handbuch (DE+EN).

### Changed

- **Desktop: eingebettetes RDP pinnt jedes Zertifikat:** IronRDP kommt jetzt vom Fork `AdminCave/IronRDP`
  (Upstream plus eine Option in `ironrdp-tls`); damit braucht auch ein Zertifikat einer oeffentlichen CA eine
  Bestaetigung, bevor die eingebettete Sitzung verbindet.
