<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Postgres: eine Rolle je Dienst statt des gemeinsamen Superusers

## Problem / Motivation

Alle Dienste verbinden sich mit dem Konto, das das Postgres-Image beim ersten Start als Superuser anlegt
(`POSTGRES_USER=adminhelper`, `docker-compose.yml:15`): `server` und `scheduler` (`:91`, `:169`), `ca-issuer`
(`:302`) mit der DB `adminhelper`, `monitoring` (`:476`) mit `adminhelper_monitor`, und `monitoring` legt seine DB
beim Start selbst an (`apps/monitoring/docker-entrypoint.sh:28-45`). Jeder Dienst hat damit alle Rechte auf beide
Datenbanken und auf den Cluster, obwohl er weit weniger braucht: `ca-issuer` liest und schreibt fünf Tabellen der
Server-DB (`apps/ca-issuer/app/db.py:54-120`), `monitoring` nur seine eigene DB. Least Privilege ist hier ein
Betriebs- und Architekturziel (Komponenten-Grenzen, `docs/developer/index.html`).

## Ziel & Nicht-Ziele

Ziel:
- Je Dienst eine Login-Rolle ohne `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION`, `BYPASSRLS`, mit eigenem
  Passwort aus `.env` (an Postgres geht nur der SCRAM-Verifier):
  - `ah_server`: besitzt das Schema `public` der DB `adminhelper` und alle Objekte darin (Alembic braucht DDL).
  - `ah_scheduler`: nur DML auf den Server-Tabellen, per `ALTER DEFAULT PRIVILEGES FOR ROLE ah_server` auch auf
    künftige (Offene Frage 1).
  - `ah_monitor`: besitzt das Schema `public` der DB `adminhelper_monitor` und alles darin.
  - `ah_ca`: `CONNECT` auf `adminhelper` und je Tabelle nur, was `ca-issuer` dort tut: `enrollment_tokens` lesen und
    ändern, `device_lines` lesen, anlegen, ändern, `issued_certificates` lesen und anlegen, `revoked_identities` und
    `certificate_register_state` nur lesen; dazu die Sequenzen dieser Tabellen.
  - Die Datenbanken selbst (auch `postgres`) bleiben beim Superuser: ein Eigentümer könnte seiner Datenbank
    Einstellungen anhängen (`ALTER DATABASE … SET`), unter denen jede spätere Superuser-Sitzung läuft. `db-init`
    verbindet sich zusätzlich nur mit `search_path=pg_catalog`.
  - `CONNECT` und `TEMPORARY` aller drei DBs für `PUBLIC` entzogen; jede Rolle kommt nur in ihre DB.
- Ein Einmal-Dienst `db-init` (Server-Image, `python -m app.db_roles setup`) richtet Rollen, Passwörter, die
  Monitoring-DB, Eigentümer und `CONNECT` bei jedem `up` idempotent ein und endet; die Dienste warten auf ihn
  (`depends_on: condition: service_completed_successfully`). Nur `postgres` und `db-init` sehen das
  Superuser-Passwort.
- Die Rechte von `ah_ca` auf die fünf Tabellen setzt der Server nach `alembic upgrade head` (als Eigentümer), damit
  eine Migration, die eine dieser Tabellen neu anlegt, sie nicht verliert.
- Bestand: Ein Update übernimmt eine bestehende Installation ohne Datenverlust: `init-secrets.sh` ergänzt die vier
  neuen Passwörter (läuft schon in `update.sh:563`), `db-init` überträgt die Objekte vom Superuser an die neuen
  Rollen. Belegt durch `upgrade_path_test.sh` (letztes Release → dieser Stand) im Sammellauf.

Nicht-Ziele:
- Kein Wechsel des Postgres-Images oder seiner UID (host-uid-guard), keine zweite Postgres-Instanz.
- Keine Netzwerk-Trennung `postgres` ↔ `pki` (eigene Zeile, falls gewünscht); die Doku wird korrigiert.
- Das Backup bleibt beim Superuser (`docker compose exec postgres`). Der Restore (`restore.sh`) lässt erst `db-init`
  laufen und spielt dann jede Datenbank als ihre Rolle ein (`ah_server`, `ah_monitor`; `--no-owner --no-privileges`);
  auch ein alter Dump mit Eigentümer `adminhelper` gehört danach der Rolle. Die Passwörter gehen über die Umgebung in
  den Container, nie über argv; fehlt eines in `.env`, bricht `restore.sh` vor dem Stopp des Stacks ab und nennt
  `scripts/init-secrets.sh`.

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | server | `apps/server/app/db_roles.py` (neu), `apps/server/docker-entrypoint.sh`, `apps/server/tests/test_db_roles.py` (neu) |
| T2 | scripts | `docker-compose.yml`, `scripts/init-secrets.sh`, `apps/monitoring/docker-entrypoint.sh`, `.env.example`, `scripts/tests/init-secrets_test.sh`, `apps/server/tests/test_env_parity.py` |
| T3 | scripts | `scripts/tests/integration_stack_test.sh` |
| T4 | — (Doku) | `docs/developer/index.html`, `docs/en/developer/index.html`, `docs/admin/installation.html`, `docs/en/admin/installation.html`, `docs/admin/betrieb.html`, `docs/en/admin/operations.html`, `DEVELOPMENT.md`, `CHANGELOG.md` |
| T5 | scripts | `scripts/restore.sh`, `scripts/tests/restore_guard_test.sh`, `docs/features/db-roles.md` |
| T6 | scripts | `scripts/pg-restore.sh` (Frage an Kevin) |

## Datenmodell / API / Migrationen

Keine Alembic-Migration und keine API-Änderung. Die Datenmigration ist eine Eigentümer- und Rechte-Übertragung im
Cluster, idempotent bei jedem Start (`db-init`). Neue `.env`-Variablen: `SERVER_DB_PASSWORD`, `SCHEDULER_DB_PASSWORD`,
`MONITOR_DB_PASSWORD`, `CA_DB_PASSWORD` (je 32 Bytes hex). Rollennamen fest, per Umgebung überschreibbar.

## Externe Integrationen

PostgreSQL 17: `ALTER … OWNER TO`, `REASSIGN OWNED` (für den Bootstrap-Superuser nicht nutzbar, er besitzt
Systemobjekte; deshalb Objekt für Objekt im Schema `public`), `ALTER DEFAULT PRIVILEGES`, `GRANT CONNECT`. Doku vor
dem Bau nachlesen: https://www.postgresql.org/docs/17/sql-alterdefaultprivileges.html,
https://www.postgresql.org/docs/17/sql-reassign-owned.html. Docker Compose `service_completed_successfully`.

## Trade-offs & Alternativen

1. **Einmal-Dienst `db-init`** statt `docker-entrypoint-initdb.d`: die Init-Skripte des Images laufen nur auf einem
   leeren Volume, also nie für den Bestand; und `docker-compose.yml` bleibt ohne Bind-Mounts aus dem Repo.
2. **Schema-Eigentum statt reiner GRANTs für `ah_server`, aber nicht das der Datenbank**: Alembic legt Tabellen an und ändert sie; ein Nicht-Eigentümer
   könnte das nicht.
3. **Rechte von `ah_ca` im Server-Entrypoint** statt in `db-init`: `db-init` läuft vor den Migrationen; eine
   Migration, die eine ca-Tabelle neu anlegt, entzöge sonst bis zum nächsten Start die Rechte.
4. **Rollen-Test mit eigenem Postgres-Container** (`apps/server/tests/test_db_roles.py`): die Test-DB der Entwickler
   hat keine `CREATEROLE`-Rechte; ein Wegwerf-Container läuft lokal (Docker) und in den Server-Jobs der CI.

## Risiken & Rollback

- Ein Update, dessen `db-init` scheitert, startet keinen Dienst (Abhängigkeit); der Log nennt den Schritt. Die Daten
  bleiben unberührt (nur Eigentümer/Rechte).
- Rollback: ein älterer Compose-Stand verbindet sich wieder als Superuser; der umgeht alle Rechte, der Bestand
  bleibt nutzbar. Die neuen Rollen bleiben ohne Wirkung im Cluster.
- `restore.sh` spielt als Dienst-Rolle ein: was die Rolle nicht anlegen darf (etwa eine Erweiterung), scheitert dort
  laut statt still. Heute legen weder Server noch Monitoring eine Erweiterung an. Die Rechte des `ca-issuer` setzt
  `grant-ca` beim nächsten Start des Servers, die des Schedulers die Default-Privilegien von `ah_server`.

## Doku-Impact

`docs/developer/index.html` (Komponenten: Datenbank-Rollen; Korrektur: `postgres` hängt auch im pki-Netz, nicht nur
das Gateway erreicht den ca-issuer), `docs/admin/installation.html` und `betrieb.html` (neue `.env`-Passwörter,
`db-init`, Backup/Restore), DE+EN; `DEVELOPMENT.md` (`tests/test_db_roles.py` braucht Docker); CHANGELOG (Changed, Security
neutral: „eine Rolle je Dienst“).

## Offene Fragen

1. **Scheduler: eigene Rolle mit DML oder die Rolle des Servers?** Empfehlung: eigene Rolle `ah_scheduler` mit DML
   über Default-Privilegien — der Scheduler legt keine Tabellen an. Trade-off: eine Variable und ein Default-Privileg
   mehr; eine Migration, die nur Rechte anderer Rollen ändert, muss den Scheduler mitdenken.
2. **Plan-Freigabe (Kevin 2026-10-22/29):** gebaut wird erst nach Kevins Ja zu diesem Plan; die PR merged Kevin
   (`update.sh`-Pfad, Datenmigration).
