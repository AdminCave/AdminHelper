### Changed

- **Agent: Tunnel-Abbau ohne Antwort von systemd:** Kann der Agent frpc nicht ueber systemd stoppen, obwohl der
  Server keinen Tunnel mehr vorsieht, laedt er eine frpc-Konfiguration ohne Tunnel ueber die Admin-API des eigenen
  frpc; der Fehler bleibt gemeldet, der naechste Lauf stoppt frpc erneut ueber systemd.
- **Agent: Grenzen fuer die frpc-Konfiguration vom Server:** Der Agent nimmt je Tabelle hoechstens 4096 und
  insgesamt hoechstens 131072 Schluessel an (Tabellen, die ein gepunkteter Schluessel oeffnet, zaehlen mit) und
  kuerzt Schluessel in seinen Fehlermeldungen auf 64 Zeichen.
