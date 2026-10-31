### Fixed

- **Install: kein zweiter Lauf ueber eine bestehende Installation:** `install.sh` bricht ab, ohne etwas zu aendern,
  wenn der Zielordner schon eine `.env` oder `docker-compose.yml` enthaelt oder das Compose-Projekt schon Container
  oder ein Volume `postgres-data` bzw. `ca-pki` hat, und nennt `./scripts/update.sh`. Bisher schrieb es `DOMAIN` und
  die Image-Pins neu und startete den Stack, der die Datenbank ohne Backup migrierte.
