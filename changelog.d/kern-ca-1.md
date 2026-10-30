### Fixed

- **CA-Issuer: Pruefung der Zwischenzertifikate beim Start:** Der Start prueft das aktuelle Zwischenzertifikat jedes
  Scopes so vollstaendig wie die abgeloesten (Name des Scopes, nur zum Signieren von Endzertifikaten) und bricht
  sonst mit Datei und Scope ab. Eine nicht lesbare `root.crt`, `<scope>.crt` oder `<scope>.key` bricht den Start mit
  einer Meldung ab, die Datei und Scope nennt, statt mit einem `ValueError` ohne Ort.
- **CA-Issuer: geaenderte `DOMAIN` oder `EXTRA_SANS` wirken beim naechsten Start:** Nennt das vorhandene Server-Zertifikat
  des Gateways oder von frps andere Namen oder Adressen als konfiguriert (`DOMAIN` und `EXTRA_SANS`; fuer frps
  `CA_FRPS_SERVER_ADDR`, ersatzweise `DOMAIN`, und `CA_FRPS_EXTRA_SANS`), stellt der `ca-issuer` es beim naechsten
  Start neu aus; bisher erst nach der halben Laufzeit oder mit `down -v`. Das Gateway liest sein Zertifikat nur beim
  eigenen Start (danach `docker compose restart gateway`); frps uebernimmt das neue Zertifikat selbst.
  Reihenfolge und Leerzeichen in `EXTRA_SANS` loesen keine Neuausstellung aus. Doku: Agent-Deployment (DE+EN).
- **CA-Issuer: Browser-Zertifikate behalten ihre Laufzeit bei der Erneuerung:** Ein Browser-Zertifikat, das vor dem
  Ende seines Zwischenzertifikats gekuerzt ausgestellt wurde, erneuerte der `ca-issuer` bisher nur mit der kurzen
  Laufzeit der Desktop- und Agent-Zertifikate. Die Laufzeit richtet sich jetzt nach der Art des Geraets im
  Zertifikats-Register; nur ein dort nicht erfasstes Zertifikat wird weiter nach seiner Laufzeit eingeordnet.
