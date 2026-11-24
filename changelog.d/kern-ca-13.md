### Fixed

- **CA-Issuer: LOG_LEVEL:** Nur DEBUG, INFO, WARNING, ERROR und CRITICAL starten den Dienst. Ein unter uvicorn
  registrierter Name wie TRACE bricht den Start jetzt ab, wie die Betriebsdoku es beschreibt.
