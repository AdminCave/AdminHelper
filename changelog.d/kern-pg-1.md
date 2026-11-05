### Changed

- **PostgreSQL 18:** Der Stack laeuft auf `postgres:18-alpine` mit dem neuen Volume `postgres18-data`. Das erste
  `update.sh` auf diese Version zieht die Daten selbst um: `pg_dumpall` aus dem laufenden PostgreSQL 17, Einspielen in
  ein frisches PostgreSQL 18. Vorher prueft es den freien Platz und bricht ohne Aenderung ab, wenn er nicht reicht;
  scheitert der Umzug oder der Start danach, rollt es auf die alte Version zurueck. Das alte Volume
  `<projekt>_postgres-data` bleibt unangetastet als Rueckweg stehen; nach der Pruefung entfernen mit
  `docker volume rm <projekt>_postgres-data`.
