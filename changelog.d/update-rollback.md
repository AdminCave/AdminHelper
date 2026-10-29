### Fixed

- **Gateway: Healthcheck ueber /healthz auf 127.0.0.1:** Das Gateway hat einen Healthcheck ueber einen Listener nur auf
  127.0.0.1 (`/healthz`); `docker compose ps` zeigt `healthy` oder `unhealthy` statt nur `running`.
- **Compose: Healthchecks fuer victoria und monitoring ueber HTTP:** victoria hat einen Healthcheck auf `/health`;
  monitoring fragt `/health` per HTTP statt nur einen TCP-Connect zu pruefen, ein haengender Prozess wird so
  `unhealthy`.
- **update.sh: Neustart wartet auf die Healthchecks aller Dienste:** `update.sh` startet den Stack mit
  `docker compose up --wait` und rollt zurueck, wenn ein Dienst mit Healthcheck nicht gesund wird, statt nur den Server
  zu pruefen; "zurueckgerollt" meldet es erst, wenn der alte Stand wieder gesund laeuft, sonst "unvollstaendig".
  `update.sh` braucht dafuer Docker Compose v2.17 oder neuer und bricht mit aelterem ab, bevor es etwas aendert.
- **update.sh: Abbruch beim Ziehen der Images laesst kein halbes Update zurueck:** Die Image-Pins kommen erst nach dem
  Ziehen aller Images in die `.env`; ein Abbruch per Strg-C, `kill` oder eine getrennte SSH-Sitzung rollt zurueck.
  Zuvor konnte die `.env` danach auf der neuen Version stehen, mit den alten Containern, und `update.sh --check`
  meldete das Update als installiert. Nach einer getrennten Sitzung steht die Ausgabe in `backups/update-<zeit>.log`.
