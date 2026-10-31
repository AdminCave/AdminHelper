### Added

- **Web: Seite "Zertifikate" mit Ablauf-Alarm:** Das Web-Admin-Panel zeigt unter *Zertifikate* (nur Admins), wann die
  Zertifikate der Infrastruktur (Root, Zwischenzertifikate, Gateway, frps) und der Agenten ablaufen — mit Resttagen und
  Ampel: gelb unter 30, rot unter 7 Tagen. Der `ca-issuer` schreibt die Infrastruktur-Zertifikate bei jedem Start in
  die Datenbank. Einmal am Tag meldet der `scheduler` jedes Zertifikat, das gelb oder rot wird, den Admins ueber den
  Notification-Hub (Glocke und, je nach Abo, E-Mail), je Stufe einmal. Neuer Endpunkt
  `GET /api/enrollment/certificates`. Doku: Betrieb, Web-UI, API-Referenz (DE+EN).
