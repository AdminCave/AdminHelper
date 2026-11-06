### Added

- **Desktop: Backend fuer eingebettetes RDP:** Die Desktop-App bringt einen eigenen RDP-Client mit (IronRDP, TLS mit
  CredSSP, Grafik-Pipeline, festes Format 1280x720). `rdp_session_start` startet eine Sitzung zu einer gelisteten
  RDP-Verbindung mit dem Passwort aus dem App-Keyring und gibt das Bild ueber einen WebSocket auf 127.0.0.1 mit
  Token an die Webview; die Phasen meldet das Event `rdp-session`, `rdp_session_stop` beendet sie. Ein Watchdog
  verbindet eine Sitzung neu, deren Eingabe kein Bild mehr beantwortet. Das Server-Zertifikat pinnt die App je
  Workspace und Ziel erst nach Bestaetigung (`rdp_trust_certificate`), `trust_cert` wirkt wie `/cert:ignore`.
  Noch ruft keine Oberflaeche die Befehle auf; RDP-Verbindungen oeffnet weiter der Client des Betriebssystems. Die
  Webview-CSP erlaubt dafuer zusaetzlich `ws://127.0.0.1:*`. Doku: Desktop-Entwicklerdoku (DE+EN).
