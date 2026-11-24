### Changed

- **Konfiguration: ungueltige Werte brechen den Start ab:** Server, Monitoring und CA-Issuer starten nicht mehr mit
  einem ungueltigen Wert einer Umgebungsvariablen (etwa keine Zahl in `SMTP_PORT`, ein unbekannter `LOG_LEVEL`, ein
  Eintrag in `MONITOR_PUBLIC_RESOLVERS`, der keine IP ist). Die Meldung nennt Variable, Wert und Erwartung, bei
  Geheimnissen ohne den Wert. Bisher fielen manche Variablen still auf den Default zurueck.
- **Monitoring braucht `MONITOR_API_KEY`:** Ist der Schluessel leer, startet das Monitoring nicht mehr und erzeugt
  keinen eigenen in `DATA_DIR/.api_key`; der Server meldet beim Start einen ERROR und laeuft weiter.
  `scripts/init-secrets.sh` setzt den Schluessel. Eine vorhandene `DATA_DIR/.api_key` liest nichts mehr, sie kann
  geloescht werden.
- **Server: API-Doku nur auf Wunsch:** `/api/docs` und `/openapi.json` liefert der Server nur mit
  `SERVER_ENABLE_DOCS=1` aus, wie Monitoring und CA-Issuer mit ihren Schaltern.
- **CA-Issuer: `LOG_LEVEL`:** Der CA-Issuer liest `LOG_LEVEL` und loggt im Format von Server und Monitoring.
