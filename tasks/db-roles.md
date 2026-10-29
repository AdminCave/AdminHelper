<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Postgres: eine Rolle je Dienst statt des gemeinsamen Superusers — Task-Ledger
Status: aktiv · Branch: feature/db-roles · Review: pro Task
Spec: docs/features/db-roles.md
Heavy: linux-full — `docker-compose.yml`, Server-Entrypoint, alle Dienste mit Postgres; der Sammellauf fährt `integration_stack` und `upgrade_path_test.sh` (letztes Release mit Bestandsdaten → dieser Stand). `scenario --agents 1` vor dem Merge (Agent-Report über monitoring mit neuer Rolle; Kevin fragen). Kein `windows`. PR merged Kevin (Datenmigration, `update.sh`-Pfad über `init-secrets.sh`)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — `app.db_roles`: Rollen, Eigentum, CONNECT und die Rechte des ca-issuer  [ ]
Komponente: server · Dateien: apps/server/app/db_roles.py, apps/server/docker-entrypoint.sh, apps/server/tests/test_db_roles_sql.py, scripts/tests/db_roles_test.sh
Änderung: Neues Modul (SPDX) mit zwei Befehlen. `setup` (Superuser aus `PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`): legt `ah_server`, `ah_scheduler`, `ah_monitor`, `ah_ca` an bzw. setzt ihr Passwort aus `SERVER_DB_PASSWORD` … `CA_DB_PASSWORD` (`NOSUPERUSER NOCREATEDB NOCREATEROLE LOGIN`), legt `adminhelper_monitor` an, falls sie fehlt, setzt die Eigentümer (DB, Schema `public`, jede Tabelle, Sequenz, Sicht und jeden Typ in `public`) auf `ah_server` bzw. `ah_monitor`, entzieht `CONNECT` für `PUBLIC` und gibt es den Rollen ihrer DB, `ALTER DEFAULT PRIVILEGES FOR ROLE ah_server` DML für `ah_scheduler`. `grant-ca` (als `ah_server` nach `alembic upgrade head` im Server-Entrypoint, `docker-entrypoint.sh:44`): `SELECT/INSERT/UPDATE` wie `apps/ca-issuer/app/db.py` sie braucht auf `enrollment_tokens`, `revoked_identities`, `device_lines`, `issued_certificates`, `certificate_register_state` (+ Sequenzen), sonst nichts. Beide idempotent; Bezeichner per `psycopg.sql.Identifier`, Passwörter als Parameter, nie im Log. Rollennamen per Umgebung überschreibbar (Tests im geteilten Cluster). Tests: `test_db_roles_sql.py` (SQL-Erzeugung, ohne DB); `scripts/tests/db_roles_test.sh` (Wegwerf-`postgres:17-alpine`, Server-Venv): frische DB und Bestand (Tabellen als Superuser angelegt) → nach `setup` und `grant-ca` besitzt `ah_server` alles in `public`, keine Rolle ist Superuser, `ah_ca` liest `users` nicht und verbindet sich nicht mit `adminhelper_monitor`, `ah_monitor` nicht mit `adminhelper`, `ah_scheduler` darf `INSERT` auf eine später von `ah_server` angelegte Tabelle; zweiter Lauf ändert nichts. Zuerst rot: alles (Modul fehlt).
Verify: bash scripts/dev/verify.sh server scripts --strict
Doku: → T4

### T2 — Compose, Secrets und Monitoring auf die neuen Rollen  [ ]
Komponente: scripts · Dateien: docker-compose.yml, scripts/init-secrets.sh, apps/monitoring/docker-entrypoint.sh, .env.example, scripts/tests/init-secrets_test.sh, apps/server/tests/test_env_parity.py
Änderung: Neuer Dienst `db-init` (Server-Image, `command: python -m app.db_roles setup`, `restart: "no"`, Superuser-Variablen nur hier und in `postgres`); `server`, `scheduler`, `ca-issuer`, `monitoring` hängen mit `service_completed_successfully` an ihm und verbinden sich mit ihrer Rolle (`DATABASE_URL`, `PGUSER`); `monitoring` legt seine DB nicht mehr selbst an (Block `apps/monitoring/docker-entrypoint.sh:28-45` entfällt, `PGPASSWORD` des Superusers fällt weg). `init-secrets.sh` erzeugt die vier Passwörter, auch für eine bestehende `.env` (fehlt eins → ergänzen, gesetzt → bleibt). Tests: `init-secrets_test.sh` (frisch und Bestand: vier neue Werte, vorhandene unverändert); `test_env_parity.py` (jede neue Variable gesetzt, kein Dienst außer `postgres`/`db-init` bekommt `POSTGRES_PASSWORD`).
Verify: bash scripts/dev/verify.sh server scripts --strict
Doku: → T4
Abhängt von: T1

### T3 — Stack-Test: die Rollen im echten Stack  [ ]
Komponente: scripts · Dateien: scripts/tests/integration_stack_test.sh
Änderung: Nach dem Hochfahren prüft der Stack-Test über `docker compose exec postgres`: keine Login-Rolle außer dem Bootstrap-Konto ist Superuser; `server` und `ca-issuer` verbinden sich mit `ah_server` bzw. `ah_ca` (`pg_stat_activity`); `ah_ca` bekommt auf `SELECT … FROM users` einen Rechtefehler. Läuft im Stack-Job (main/Dispatch) und im Sammellauf.
Verify: bash scripts/dev/verify.sh scripts --strict -- integration_stack_test
Doku: → T4
Abhängt von: T2

### T4 — Doku: Datenbank-Rollen, neue Passwörter, Korrektur pki-Netz  [ ]
Komponente: scripts · Dateien: docs/developer/index.html, docs/en/developer/index.html, docs/admin/installation.html, docs/en/admin/installation.html, docs/admin/betrieb.html, docs/en/admin/operations.html, DEVELOPMENT.md, CHANGELOG.md
Änderung: Entwickler-Index (Komponenten): Rollen je Dienst, `db-init`; Korrektur der Aussage, nur das Gateway erreiche den `ca-issuer` (auch `postgres` hängt im pki-Netz). Installation/Betrieb: die vier `.env`-Passwörter, `db-init` beim Start, Backup/Restore als Superuser, Rollback-Hinweis. `DEVELOPMENT.md`: `db_roles_test.sh` braucht Docker. CHANGELOG (Changed, umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Dateien dieser Task

## Entscheidungen
- 2026-10-29 Kevin: Plan freigegeben; der Scheduler bekommt eine eigene Rolle mit nur DML (Offene Frage 1).
