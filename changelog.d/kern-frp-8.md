### Added

- **FRP-Tunnel mit Protokoll `web`: Schema und Pfad:** der Tunnel-Dialog fragt fuer die automatische Verbindung
  Schema (`https` als Vorgabe bei Port 443, 8006, 8443 und 9443) und optional einen Pfad statt eines Benutzernamens;
  die API nimmt dafuer `auto_connection_scheme` und `auto_connection_path`. Die Verbindungsansicht zeigt die ueber den
  Tunnel aufgeloeste Adresse.

### Changed

- **Desktop: Web-Verbindung ueber einen STCP-Tunnel:** beim Oeffnen ersetzt der Desktop nur Host und Port der URL;
  Schema, Pfad und Query bleiben (bisher immer `http://127.0.0.1:<Port>`). Bei `https` zeigt der Browser die
  Zertifikatswarnung fuer `127.0.0.1`.
- **Server: Protokoll- oder Typwechsel eines Tunnels:** die verknuepfte Verbindung zieht mit (Typ, Host, Port, URL),
  auch eine von Hand verknuepfte.
