### Added

- **Desktop: Optionen je Verbindung:** Der Verbindungs-Editor hat fuer SSH den Reiter *Optionen* (Jump-Host, auch
  mehrere Hops; Weiterleitungen `-L`/`-R`/`-D`; Agent-Forwarding, Kompression, Keepalive; Anmeldeart im Reiter
  *Anmeldung*) und fuer RDP den Reiter *Anzeige* (Skalierung, Fenstermodus, Groesse, Leistungsprofil, Laufwerke,
  Audio, Drucker, RD-Gateway, NLA). Gesetzte Werte ueberschreiben die globalen Einstellungen nur fuer diese
  Verbindung; der Server speichert sie im neuen Feld `options` (Alembic-Revision), Export, Import und Sync tragen sie
  mit. Ein aelterer Desktop-Client zeigt die Optionen nicht und verwirft sie in einem lokalen Workspace beim Speichern.
- **Sitzungsverlauf je Verbindung:** Der Inspector zeigt *Letzte Sitzungen* (Beginn, Dauer, Geraet); RDP traegt das
  Ende ein, SSH und Web nur den Beginn. Im Server-Workspace fuehrt der Server den Verlauf (neue Tabelle
  `connection_sessions`, `POST /api/connections/{id}/touch` beginnt eine Sitzung und nimmt optional `device`,
  `POST /api/connections/{id}/sessions/{sessionId}/end`, `GET /api/connections/{id}/sessions`), 90 Tage; Lokal und
  Sync speichern ihn auf dem Geraet, 90 Tage und hoechstens 50 je Verbindung.
