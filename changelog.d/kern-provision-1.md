### Added

- **Provisionieren-Fenster im Desktop:** *Provisionieren ...* im Tab Provisionierung baut je Plattform (Linux,
  Windows, FreeBSD, OPNsense) die Befehle fuer Installieren, Aktualisieren, Neu registrieren und Entfernen, zeigt
  unterstuetzte Systeme und ausgehende Ports und verfolgt den Fortschritt (Token eingeloest, Zertifikat ausgestellt,
  erster Bericht, Tunnel verbunden) mit Hinweisen, wenn es haengt. Neue Routen `GET /api/provisioning/platforms`
  (Katalog) und `GET /api/servers/{server_id}/provision/progress`. Doku Agent-Rollout, Abschnitt Provisionieren im
  Desktop.

### Changed

- **Plattform statt Betriebssystem-Freitext:** `os_type` eines Servers nimmt nur noch `linux`, `windows`, `freebsd`,
  `opnsense`, `other` oder leer an (sonst 422); der Desktop zeigt ein Auswahlfeld. Die Migration ordnet die
  gespeicherten Texte einmal zu, der Freitext geht dabei verloren — vor dem Update die Datenbank sichern, wer ihn
  braucht. Weicht die vom Agent gemeldete Plattform ab, zeigt die Server-Ansicht einen Hinweis.
