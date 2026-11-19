### Changed

- **Windows-Provisionierung fuer Automatisierung ohne Token in der Prozessliste:** Der Befehl, den das
  Provisionieren-Fenster des Desktops im Automationsmodus fuer Windows baut, reicht den Token per Pipe ueber die
  Standardeingabe an `provision --token-stdin` weiter statt als `--token`. Der Katalog
  (`GET /api/provisioning/platforms`) nennt dafuer den neuen Wertetyp `tokenStdin`; aeltere Desktop-Versionen zeigen
  fuer Windows im Automationsmodus dann keinen Befehl. Doku Agent-Rollout, Abschnitt Provisionieren im Desktop.

### Fixed

- **Provisionieren-Fenster:** Unbekannte Katalogwerte eines neueren Servers (Hinweis, Portzweck) erscheinen als
  benannter Ersatztext statt als Uebersetzungsschluessel. Der Befehlsbau prueft Kopf und Werte strenger.
- **Provisionierungs-Fortschritt:** Das Zertifikat einer widerrufenen Linie zaehlt nicht mehr als ausgestellt.
