<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-pg-1 — PostgreSQL 18 mit Upgrade-Pfad für bestehende Installationen

Zug `tasks/kern-pg-1.md` mit R-1035 (Kevin 2026-11-02: alles auf aktuelle LTS/Stable; Kevin 2026-11-03: Verfahren
dump/restore — `pg_dumpall`, neues Volume, altes Volume als Rollback).

## Problem / Motivation

Der Stack fährt `postgres:17-alpine` (`docker-compose.yml:13`, Volume `postgres-data:/var/lib/postgresql/data`,
`:20`). Aktuell ist PostgreSQL 18.6 (`postgres:18-alpine`, Index-Digest
`sha256:10a5c69a83035ab5239f5620d708520e8b28f5aa1f2b20143e6024532edadfb5` am 2026-11-05). Ein Major-Wechsel liest
das alte Datenverzeichnis nicht: ein bloßer Image-Tausch ließe jede bestehende Installation beim nächsten
`update.sh` mit einem Postgres zurück, das nicht startet.

Dazu hat das offizielle Image ab 18 ein anderes Layout: `PGDATA=/var/lib/postgresql/18/docker`, `VOLUME
/var/lib/postgresql` (geprüft am Image: `docker image inspect`, und die Image-Doku, s. u.). Der heutige Mount auf
`/var/lib/postgresql/data` passt dazu nicht mehr.

## Ziel & Nicht-Ziele

Ziel:
- Neue Installationen starten auf PostgreSQL 18 mit dem neuen Volume `postgres18-data` auf `/var/lib/postgresql`.
- `update.sh` hebt eine bestehende 17-Installation selbst: `pg_dumpall` aus dem laufenden 17, Einspielen in ein
  frisches 18 auf dem neuen Volume, dann der normale Start mit Healthcheck. Das alte Volume `postgres-data` bleibt
  unangetastet stehen; schlägt der Start fehl, rollt das Update wie bisher auf die alten Laufzeit-Dateien zurück,
  und die zeigen auf das alte Volume.
- `restore.sh` spielt Backups (auch alte aus 17, `pg_dump -Fc`) in den 18er-Stack ein; `install.sh` erkennt eine
  bestehende Installation an beiden Volumes; Doku nennt Version, Volume und wie man das alte Volume nach der
  Prüfung entfernt.
- Tests laufen gegen 18 (`conftest.py`, `test_db_roles.py`, `sse_push_e2e.sh`).

Nicht-Ziele:
- `pg_upgrade --link` (Kevin: dump/restore).
- Das alte Volume automatisch löschen: es ist der Rollback, der Admin entfernt es nach der Prüfung.
- `.github/workflows/ci.yml` (`postgres:17-alpine` als Service, sieben Stellen): `ci.yml` ändert der offene PR #387
  (`feature/ci-3`), Kevin merged Workflow-PRs. Eigene Zeile im Zug `ci-4`.

## Betroffene Komponenten & Dateien

- server-Tests: `apps/server/tests/conftest.py:372`, `apps/server/tests/test_db_roles.py:20`,
  `scripts/tests/sse_push_e2e.sh:62`, `DEVELOPMENT.md:220`.
- Compose + Update (Risikopfad): `docker-compose.yml:13,20,611,677`, `scripts/update.sh` (zwischen Image-Pull
  `:818` und `stack_up` `:835`; Rollback `rollback_after_deploy` `:752`), `scripts/tests/update_test.sh`.
- Install/Restore/Uninstall: `scripts/install.sh:14,443,581,593-599`, `scripts/restore.sh:310,368`,
  `scripts/uninstall.sh:9` (der Lauf selbst löscht per Projekt-Label `:137` schon beide Volumes), ihre Tests
  `scripts/tests/install_test.sh`, `restore_guard_test.sh`.
- Doku DE+EN: `README.md:161,246`, `DEVELOPMENT.md:891`, `docs/admin/index.html:141`, `docs/admin/betrieb.html:74`
  + EN `operations.html:41`, `docs/developer/server.html:198,215` + EN, `docs/developer/index.html:41` + EN,
  `docs/admin/troubleshooting.html:40` + EN, Update-Abschnitt in `betrieb.html`/`operations.html`;
  `changelog.d/kern-pg-1.md`.

## Datenmodell / API / Migrationen

Keine Schema-Änderung, kein API-Vertrag. Es ist eine **Datenmigration des Clusters** (Kevins Bereich, entschieden
2026-11-03): alle Datenbanken, Rollen und Rechte kommen per `pg_dumpall` in den neuen Cluster. `db-init` setzt beim
Start die Passwörter der Dienst-Rollen wie bisher neu; Alembic findet dieselbe Revision.

## Externe Integrationen

- **postgres-Image** (github.com/docker-library/docs, `postgres/README.md`): „the `PGDATA` environment variable of
  the image was changed to be version specific in PostgreSQL 18 and above“; „The defined `VOLUME` was changed in 18
  and above to `/var/lib/postgresql`.“ Am Image: `PGDATA=/var/lib/postgresql/18/docker`, `Volumes
  {"/var/lib/postgresql":{}}`, `postgres --version` 18.6.
- **PostgreSQL-Doku „Upgrading a PostgreSQL Cluster“** (postgresql.org/docs/18/upgrading.html): Dump mit dem
  `pg_dumpall` der *neuen* Version empfohlen; beim Bau wörtlich nachlesen und im Ledger zitieren. Daraus folgt:
  `pg_dumpall` läuft im 18er-Image gegen den laufenden 17er-Container.
- Release Notes 18 (Inkompatibilitäten, u. a. Daten-Prüfsummen per Default bei `initdb`, MD5-Passwörter
  veraltet): beim Bau gegen unsere Nutzung prüfen (SCRAM, keine Extensions außer den Standard).

## Ablauf in `update.sh` (T2)

Nach dem Image-Pull, vor `stack_up`, nur wenn das alte Volume `<projekt>_postgres-data` existiert und das neue
`<projekt>_postgres18-data` nicht:
1. Platz prüfen (freier Platz im Docker-Root ≥ 2 × Clustergröße aus `pg_database_size`), sonst Rollback vor dem
   Deploy mit klarer Meldung.
2. Alle Dienste außer `postgres` stoppen (keine Schreiber mehr).
3. `pg_dumpall` mit dem 18er-Image gegen den laufenden 17er-Container in eine Datei im Update-Temp-Verzeichnis.
4. `docker compose up -d --wait postgres` mit den neuen Dateien: neues Volume, frisches 18 (Init mit
   `POSTGRES_PASSWORD` aus `.env`), Dump einspielen (`psql -v ON_ERROR_STOP=1`).
5. Weiter mit `stack_up` wie bisher.

Schlägt 1–4 oder `stack_up` fehl: Rollback wie heute, dazu entfernt er das in diesem Lauf angelegte neue Volume,
damit der nächste Versuch wieder migriert. Das alte Volume rührt kein Pfad an. Ein Rollback nach erfolgreichem
Start verliert, was seit der Migration in 18 geschrieben wurde (nur bis `--wait` endet; danach rollt `update.sh`
nicht mehr zurück).

## Trade-offs & Alternativen

- **Neuer Volume-Name statt Umhängen auf `/var/lib/postgresql`:** das alte Volume bleibt bitgleich als Rollback,
  und die Erkennung „noch nicht migriert“ ist ein Volume-Name statt eines Markers im Datenverzeichnis.
  Alternative: dasselbe Volume mit Unterverzeichnis `18/docker` — spart Platz, mischt aber altes und neues
  Cluster in einem Volume, ein Rollback hinge an dessen Zustand.
- **`pg_dumpall` statt je DB `pg_dump`:** nimmt Rollen und Rechte mit; die Dienst-Rollen setzt `db-init` ohnehin.
- **Dienste stoppen statt Lesesperre:** ein kurzer Ausfall während des Updates (das Update startet die Dienste
  ohnehin neu) gegen einen konsistenten Dump.

## Risiken & Rollback

- Datenpfad: der Beweis ist `upgrade_path_test.sh` (letztes Release mit 17 → dieser Stand) im Sammellauf
  (`Heavy: linux-full`); `backup_restore_test.sh` im selben Lauf deckt Restore in 18. Hermetisch deckt
  `update_test.sh` die Abzweige (migrieren/nicht migrieren, Platzmangel, Fehler in Dump/Einspielen, Rollback
  entfernt das neue Volume).
- Plattenplatz: Dump + neuer Cluster; Prüfung vor dem Stoppen.
- Der PR ändert `scripts/install.sh` und `scripts/update.sh`: Kevin merged ihn (CLAUDE.md §2).

## Doku-Impact

Version und Volume in README, DEVELOPMENT, Admin-Übersicht, Betrieb/Operations (Volume-Tabelle, Update-Abschnitt
mit dem alten Volume und `docker volume rm <projekt>_postgres-data` nach der Prüfung), Troubleshooting, Entwickler-
Doku Server DE+EN; `changelog.d/kern-pg-1.md` (`### Changed`, Hinweis auf das alte Volume).

## Offene Fragen

Keine aus Kevins Bereich (Verfahren: Kevin 2026-11-03). Die Merge-Hoheit liegt bei Kevin (install/update).
