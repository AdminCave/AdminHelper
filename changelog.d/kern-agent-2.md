### Changed

- **Agent: Tunnel-Abbau ohne Antwort von systemd:** Kann der Agent frpc nicht ueber systemd stoppen, obwohl der
  Server keinen Tunnel mehr vorsieht, laedt er eine frpc-Konfiguration ohne Tunnel ueber die Admin-API des eigenen
  frpc; der Fehler bleibt gemeldet, der naechste Lauf stoppt frpc erneut ueber systemd.
- **Agent: Grenzen fuer die frpc-Konfiguration vom Server:** Der Agent nimmt je Tabelle hoechstens 4096 und
  insgesamt hoechstens 131072 Schluessel an (Tabellen, die ein gepunkteter Schluessel oeffnet, zaehlen mit) und
  kuerzt Schluessel in seinen Fehlermeldungen auf 64 Zeichen.
- **Agent: `provision --token-stdin` am Terminal:** Ist stdin ein Terminal, fragt der Agent den Token ohne Echo ab
  (Eingabeaufforderung auf stderr); aus einer Pipe oder Datei liest er wie bisher die erste Zeile.
- **Agent: `monitor init --api-key-stdin`:** Der API-Key fuer `monitor init` laesst sich wie der Provisionierungs-Token
  ueber stdin uebergeben (am Terminal ohne Echo); Paket-Hinweis, README, Doku und der Hinweis zum Neu-Provisionieren
  zeigen die stdin-Formen.
- **Agent: Reste unterbrochener Identitaets-Schreibvorgaenge:** Provisionierung und Zertifikats-Erneuerung raeumen
  unter der Identitaets-Sperre liegengebliebene Temp-Dateien (`agent.key`, `agent.crt`, `ca.crt` mit Suffix
  `.<Zahl>.tmp`) aus dem Identitaetsverzeichnis; andere Dateien bleiben.
