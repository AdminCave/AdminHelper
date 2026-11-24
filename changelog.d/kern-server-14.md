### Added

- **Server: `GET /api/health`:** Die Route antwortet `{"status": "ok"}`, ohne Anmeldung und ohne Datenbankabfrage, wie
  es die Installations-Doku schon nannte.
- **Hooks: Notiz bei Fehlschlag:** Scheitert ein geplanter oder ein Event-Hook, auch weil das Hook-Limit erreicht ist,
  bekommen die Admins eine Notiz in der Glocke, je Hook hoechstens eine in 12 Stunden; bisher stand der Fehler nur im
  Log.

### Changed

- **Compose: Healthcheck des Servers:** Er fragt `/api/health` per HTTP ab statt nur den Port zu verbinden und erkennt
  so auch einen haengenden Prozess. Jede HTTP-Antwort zaehlt als gesund, auch ein 403 durch `ALLOWED_IPS`.

### Fixed

- **Monitoring: Reste geloeschter Server:** Scheiterte nach dem Loeschen eines Servers der Aufraeum-Aufruf an das
  Monitoring, blieben dessen Checks, Zuweisungen, Regeln und Liveness stehen. Der Tag-Abgleich raeumt sie jetzt ab,
  aber nur bei einem erfolgreich geholten, nicht leeren Inventar.
- **Benachrichtigungen: E-Mail-Digest:** Ein fehlgeschlagener Digest wartet vor dem naechsten Versuch wie der normale
  Versand (5, 10, 15, 20 Minuten); ein Relay-Ausfall von rund 20 Minuten verwarf ihn bisher endgueltig.
