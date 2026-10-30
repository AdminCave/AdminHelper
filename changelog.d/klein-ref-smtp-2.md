### Fixed

- **SMTP: unlesbare `SMTP_CA_FILE` nennt Variable und Pfad:** Fehlt die CA-Datei oder ist sie kein PEM, steht im
  Fehlertext des Hubs (Outbox `last_error`) und in der Logzeile des Monitorings jetzt `SMTP_CA_FILE` samt Pfad; die
  Meldung an den Empfaenger eines Alerts bleibt unveraendert.
- **Agent: Hinweis beim `--insecure`-Erstkontakt:** `provision --insecure` verwies auf einen im AdminHelper-Server
  angezeigten Fingerprint, den keine Oberflaeche zeigt. Der Hinweis nennt jetzt den Vergleich mit dem
  Server-Zertifikat (`openssl x509 -noout -fingerprint -sha256`) und `--ca-fp` als verifizierten Erstkontakt.
