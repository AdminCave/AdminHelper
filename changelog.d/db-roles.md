### Changed

- **Compose: eine Postgres-Rolle je Dienst:** server, scheduler, monitoring und ca-issuer verbinden sich mit eigenen
  Rollen ohne Superuser-Rechte; der Einmal-Dienst `db-init` legt sie bei jedem Start an. Neue `.env`-Werte
  `SERVER_DB_PASSWORD`, `SCHEDULER_DB_PASSWORD`, `MONITOR_DB_PASSWORD`, `CA_DB_PASSWORD` (install/update erzeugen sie;
  vor `update.sh --redeploy` `scripts/init-secrets.sh`). `restore.sh` laesst vorher `db-init` laufen und spielt jede
  Datenbank als ihre Rolle ein; fehlt ein Rollen-Passwort in der `.env`, bricht es vor dem Stopp des Stacks mit dem
  Hinweis auf `init-secrets.sh` ab. Doku: Installation, Betrieb, Entwickler-Index (DE+EN), DEVELOPMENT.
