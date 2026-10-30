### Fixed

- **CA-Issuer: Pruefung der Zwischenzertifikate beim Start:** Der Start prueft das aktuelle Zwischenzertifikat jedes
  Scopes so vollstaendig wie die abgeloesten (Name des Scopes, nur zum Signieren von Endzertifikaten) und bricht
  sonst mit Datei und Scope ab. Eine nicht lesbare `root.crt`, `<scope>.crt` oder `<scope>.key` bricht den Start mit
  einer Meldung ab, die Datei und Scope nennt, statt mit einem `ValueError` ohne Ort.
