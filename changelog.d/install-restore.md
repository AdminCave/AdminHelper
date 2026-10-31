### Fixed

- **Install: kein zweiter Lauf ueber eine bestehende Installation:** `install.sh` bricht ab, ohne etwas zu aendern,
  wenn der Zielordner schon eine `.env` oder `docker-compose.yml` enthaelt oder das Compose-Projekt schon Container
  oder ein Volume `postgres-data` bzw. `ca-pki` hat, und nennt `./scripts/update.sh`. Bisher schrieb es `DOMAIN` und
  die Image-Pins neu und startete den Stack, der die Datenbank ohne Backup migrierte.
- **Install: ohne `--domain` bleibt die `DOMAIN` der `.env`:** ein erneuter Lauf (etwa nach `--reset`) nimmt die
  `DOMAIN` der vorhandenen `.env` als Vorgabe, auch in der Abfrage; bisher setzte er sie ohne `--domain` auf
  `localhost`. `--domain` hat Vorrang.
- **Install: Start mit `docker compose up --wait`:** `install.sh` wartet auf die Healthchecks aller Dienste
  (`AH_WAIT_TIMEOUT`, Standard 600 s) statt nur auf den Server-Port und nennt bei einem Fehlschlag
  `docker compose ps` und `docker compose logs <dienst>`. Ohne `up --wait` (Compose vor v2.17) bricht es ab, bevor
  es etwas aendert.
- **Restore: Projektname und Hilfs-Image von Compose:** `restore.sh` nimmt den Projektnamen (das Praefix der
  Volumes), den Compose nutzt, auch `COMPOSE_PROJECT_NAME` aus der `.env`, und fuer seine Hilfs-Container das
  gepinnte postgres-Image ohne Netz statt `alpine`. Scheitert `docker compose config`, bricht es ab, bevor es etwas
  aendert.

### Changed

- **Install: `--reset` nur nach getipptem Projektnamen:** `install.sh --reset` nennt die Volumes des Compose-Projekts
  und loescht Container und Volumes erst, wenn am Terminal der Projektname eingetippt wurde, auch mit `--yes`; ohne
  Terminal bricht es ab, ebenso, wenn die Container des Projekts zu einem anderen Verzeichnis gehoeren. Bleibt nach `docker compose down -v` etwas stehen, startet es den Stack nicht.
