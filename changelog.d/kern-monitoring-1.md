### Fixed

- **Monitoring HTTP-Check: Content-Encoding-Schichten begrenzt:** Ein Check liest hoechstens fuenf gzip- oder
  deflate-Schichten, wie urllib3; mehr meldet er als `unknown` ("Too many content encodings (>5)").
- **Monitoring HTTP-Check: Redirect ohne Location:** Ein 3xx ohne `Location`-Header meldet `critical`
  "Redirect without Location header" statt "Too many redirects (>5)".
- **Monitoring-Alerts: Maske beim Anlegen:** `POST /alerts` mit `smtp_password` `"***"` antwortet mit 422,
  statt die Maske als Passwort zu speichern.
- **Monitoring-Templates: Steuerzeichen in Variablen:** Steuerzeichen (C0, DEL) in Hostname und Servername einer
  Zuweisung werden beim Einsetzen in Check-Namen, Konfiguration und Alert-Regeln zu Leerzeichen.
