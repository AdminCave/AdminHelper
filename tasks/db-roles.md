<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Postgres: eine Rolle je Dienst statt des gemeinsamen Superusers — Task-Ledger
Status: erledigt · Branch: feature/db-roles · Review: pro Task
Spec: docs/features/db-roles.md
Heavy: linux-full — `docker-compose.yml`, Server-Entrypoint, alle Dienste mit Postgres; der Sammellauf fährt `integration_stack` und `upgrade_path_test.sh` (letztes Release mit Bestandsdaten → dieser Stand). `scenario --agents 1` vor dem Merge (Agent-Report über monitoring mit neuer Rolle; Kevin fragen). Kein `windows`. PR merged Kevin (Datenmigration, `update.sh`-Pfad über `init-secrets.sh`)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — `app.db_roles`: Rollen, Eigentum, CONNECT und die Rechte des ca-issuer  [x]
Komponente: server · Dateien: apps/server/app/db_roles.py, apps/server/docker-entrypoint.sh, apps/server/tests/test_db_roles.py, docs/features/db-roles.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @327631a7 2026-10-29T06:11:40+01:00
Review: approve (.ah-out/review/db-roles/T1.verdict.json)
Änderung: Neues Modul (SPDX) mit zwei Befehlen. `setup` (Superuser aus `PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`): legt `ah_server`, `ah_scheduler`, `ah_monitor`, `ah_ca` an bzw. setzt ihr Passwort aus `SERVER_DB_PASSWORD` … `CA_DB_PASSWORD` (`NOSUPERUSER NOCREATEDB NOCREATEROLE LOGIN`), legt `adminhelper_monitor` an, falls sie fehlt, lässt die Datenbanken beim Superuser und setzt die Eigentümer von Schema `public` und jeder Tabelle, Sequenz, Sicht und jedem Typ darin auf `ah_server` bzw. `ah_monitor`, entzieht `CONNECT`/`TEMPORARY` für `PUBLIC` (auch auf `postgres`) und gibt `CONNECT` den Rollen ihrer DB, verbindet als Superuser nur mit `search_path=pg_catalog`, `ALTER DEFAULT PRIVILEGES FOR ROLE ah_server` DML für `ah_scheduler`. `grant-ca` (als `ah_server` nach `alembic upgrade head` im Server-Entrypoint, `docker-entrypoint.sh:44`): je Tabelle genau, was `apps/ca-issuer/app/db.py` tut (`enrollment_tokens` SELECT/UPDATE, `device_lines` SELECT/INSERT/UPDATE, `issued_certificates` SELECT/INSERT, `revoked_identities` und `certificate_register_state` nur SELECT; + Sequenzen), sonst nichts. Beide idempotent; Bezeichner per `psycopg.sql.Identifier`, Passwörter nur als SCRAM-Verifier (`encrypt_password`), nie im Log. Rollennamen per Umgebung überschreibbar (Tests im geteilten Cluster). Tests in `tests/test_db_roles.py` (SPDX): die SQL-Erzeugung ohne DB, und gegen einen Wegwerf-`postgres:17-alpine`, den der Test per Docker startet: frische DB und Bestand (Tabellen als Superuser angelegt) → nach `setup` und `grant-ca` besitzt `ah_server` alles in `public`, keine Rolle ist Superuser, `ah_ca` liest `users` nicht und verbindet sich nicht mit `adminhelper_monitor`, `ah_monitor` nicht mit `adminhelper`, `ah_scheduler` darf `INSERT` auf eine später von `ah_server` angelegte Tabelle; zweiter Lauf ändert nichts. Zuerst rot: alles (Modul fehlt).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_db_roles.py
Doku: → T4

### T2 — Compose, Secrets und Monitoring auf die neuen Rollen  [x]
Komponente: scripts · Dateien: docker-compose.yml, scripts/init-secrets.sh, apps/monitoring/docker-entrypoint.sh, .env.example, scripts/tests/init-secrets_test.sh, apps/server/tests/test_env_parity.py, apps/server/tests/test_images_exec_only.py, apps/server/tests/test_db_roles.py, docker-compose.test.yml, scripts/tests/lib_e2e_stack.sh, scripts/tests/lib_e2e_stack_test.sh, scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh, Dockerfile, apps/ca-issuer/Dockerfile, apps/monitoring/Dockerfile
Evidenz: run.sh[quick] server scripts: 10 passed, 0 failed, 8 skipped @89f99088 2026-10-29T07:56:28+01:00
Review: approve (.ah-out/review/db-roles/T2.verdict.json)
Änderung: Neuer Dienst `db-init` (Server-Image, `command: python -m app.db_roles setup`, `restart: "no"`, Superuser-Variablen nur hier und in `postgres`); `server`, `scheduler`, `ca-issuer`, `monitoring` hängen mit `service_completed_successfully` an ihm und verbinden sich mit ihrer Rolle (`DATABASE_URL`, `PGUSER`); `monitoring` legt seine DB nicht mehr selbst an (Block `apps/monitoring/docker-entrypoint.sh:28-45` entfällt, `PGPASSWORD` des Superusers fällt weg). `init-secrets.sh` erzeugt die vier Passwörter, auch für eine bestehende `.env` (fehlt eins → ergänzen, gesetzt → bleibt). Tests: `init-secrets_test.sh` (frisch und Bestand: vier neue Werte, vorhandene unverändert); `test_env_parity.py` (jede neue Variable gesetzt, kein Dienst außer `postgres`/`db-init` bekommt `POSTGRES_PASSWORD`).
Verify: bash scripts/dev/verify.sh server scripts --strict
Doku: → T4
Abhängt von: T1
Test-Löschung: apps/server/tests/test_images_exec_only.py::test_the_entrypoint_of_monitoring_creates_its_database_once — das geprüfte Programm im Monitoring-Entrypoint entfällt (die Monitoring-DB legt `db-init` an); Ersatz: `test_db_roles.py::test_monitoring_owns_its_database_and_nothing_else` (Anlage) und `test_db_roles.py::test_a_failed_setup_names_no_password` (kein Passwort in der Ausgabe)

### T3 — Stack-Test: die Rollen im echten Stack  [x]
Komponente: scripts · Dateien: scripts/tests/integration_stack_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @cb174de2 2026-10-29T08:29:51+01:00
Review: approve (.ah-out/review/db-roles/T3.verdict.json)
Änderung: Nach dem Hochfahren prüft der Stack-Test über `docker compose exec postgres`: keine Login-Rolle außer dem Bootstrap-Konto ist Superuser; `server` und `ca-issuer` verbinden sich mit `ah_server` bzw. `ah_ca` (`pg_stat_activity`); `ah_ca` bekommt auf `SELECT … FROM users` einen Rechtefehler. Läuft im Stack-Job (main/Dispatch) und im Sammellauf; den echten Lauf fährt die Session per Dispatch des Stack-Jobs auf dem Branch (wie compose-hardening T13), seine Summary-Zeile kommt in den PR-Text.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: → T4
Abhängt von: T2

### T4 — Doku: Datenbank-Rollen, neue Passwörter, Korrektur pki-Netz  [x]
Komponente: scripts · Dateien: docs/developer/index.html, docs/en/developer/index.html, docs/admin/installation.html, docs/en/admin/installation.html, docs/admin/betrieb.html, docs/en/admin/operations.html, DEVELOPMENT.md, CHANGELOG.md, README.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @0324085a 2026-10-29T09:22:53+01:00
Review: approve (.ah-out/review/db-roles/T4.verdict.json)
Änderung: Entwickler-Index (Komponenten): Rollen je Dienst, `db-init`; Korrektur der Aussage, nur das Gateway erreiche den `ca-issuer` (auch `postgres` hängt im pki-Netz). Installation/Betrieb: die vier `.env`-Passwörter, `db-init` beim Start, Backup als Superuser, `restore.sh` als die Dienst-Rollen nach `db-init` (T5), `pg-restore.sh` als Superuser, Rollback-Hinweis; `update.sh --redeploy` und ein Restore aus einem Backup von vor diesem Stand brauchen vorher `scripts/init-secrets.sh` (die `.env` hat die vier Schlüssel sonst nicht, und kein Dienst startet). `DEVELOPMENT.md`: `tests/test_db_roles.py` braucht Docker. CHANGELOG (Changed, umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Dateien dieser Task

### T5 — restore.sh: Restore mit den Dienst-Rollen  [x]
Komponente: scripts · Dateien: scripts/restore.sh, scripts/tests/restore_guard_test.sh, docs/features/db-roles.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @dc20c7af 2026-10-29T09:07:53+01:00
Review: approve (.ah-out/review/db-roles/T5.verdict.json)
Änderung: `restore.sh` lässt nach `up -d postgres` einmal `db-init` laufen (Rollen, Monitoring-DB, Eigentum) und spielt dann `adminhelper` als `ah_server` und `adminhelper_monitor` als `ah_monitor` ein (`pg_restore --clean --if-exists --no-owner --no-privileges`, Passwort aus `.env` per Umgebung in den Container, nicht über argv); das Übergangs-UPDATE des Zertifikats-Registers läuft ebenso als `ah_server`. Der `createdb`-Block als Superuser entfällt. Fehlt in `.env` ein Passwort der Rollen, bricht `restore.sh` vor dem Stopp des Stacks mit dem Hinweis auf `scripts/init-secrets.sh` ab. Spec: Abschnitt Backup/Restore und Risiken nachziehen. Test in `restore_guard_test.sh` (docker-Stub): `db-init` läuft vor dem ersten `pg_restore`, kein Restore-Aufruf als `adminhelper`, die Rollen-Passwörter stehen in keinem argv.
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test
Doku: → T4
Abhängt von: T2

### T6 — pg-restore.sh: Restore mit der Dienst-Rolle  [~] (Kevin 2026-10-29: Restore bleibt mit Superuser)
Komponente: scripts · Dateien: scripts/pg-restore.sh, scripts/tests/restore_guard_test.sh, docker-compose.yml
Änderung: `pg-restore.sh` (im auskommentierten `pg-backup`-Dienst) nimmt `PGUSER`/`PGPASSWORD` der Dienst-Rolle der Ziel-DB und bricht ab, wenn die Sitzung Superuser ist (Katalogabfrage mit `search_path=pg_catalog`); Aufrufbeispiel und Kommentar in `docker-compose.yml` nachziehen. Test: Abbruch bei Superuser-Sitzung (psql-Stub), Restore-Aufruf ohne Superuser.
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test
Doku: → T4
Abhängt von: T5

### T7 — Upgrade-Test: das Release mit seiner eigenen Compose-Datei  [x]
Komponente: scripts · Dateien: scripts/tests/upgrade_path_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d703a564 2026-10-29T10:11:05+01:00
Review: approve (.ah-out/review/db-roles/T7.verdict.json)
Änderung: Fund der Abschlussprüfung (blocker): Phase 2 startete das Release mit der `docker-compose.yml` dieses Stands; deren `db-init` braucht `app.db_roles`, das die Release-Images nicht haben, und die Dienste meldeten sich mit Rollen an, die das Release nie anlegt. Phase 2 lädt jetzt die `docker-compose.yml` des Release-Tags (raw.githubusercontent, sonst `git show <tag>:docker-compose.yml`, sonst SKIP 75) und startet sie mit `--project-directory` des Checkouts und dem bisherigen Overlay; erst Phase 3 (`e2e_up` auf HEAD) fährt `db-init` und die Rollen über den Daten des Releases. Beweis: echter Lauf von `upgrade_path_test.sh` lokal (Docker), Summary ins Commit.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Testdatei)

### T8 — Doku: die Monitoring-Datenbank legt `db-init` an, CHANGELOG-Eintrag als Fragment  [x]
Komponente: scripts · Dateien: DEVELOPMENT.md, CHANGELOG.md, changelog.d/db-roles.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @6944f135 2026-10-29T16:18:34+01:00
Review: approve (.ah-out/review/db-roles/T8.verdict.json)
Änderung: Funde der Abschlussprüfung (wichtig): `DEVELOPMENT.md` sagt noch, nur der Entrypoint des Monitoring-Containers lege `adminhelper_monitor` an; das tut jetzt `db-init` (`python -m app.db_roles setup`). Der Eintrag „Compose: eine Postgres-Rolle je Dienst“ wandert unverändert aus `CHANGELOG.md` nach `changelog.d/db-roles.md` (`### Changed`), wie seit dem Basis-Merge vorgeschrieben.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Dateien dieser Task

## Entscheidungen
- 2026-10-29 Übergabe: Entwurf der T4-Doku liegt als `.ah-out/t4-draft.patch` im Worktree (vor T5 geschrieben; die Sätze zu Backup/Restore „als Superuser“ nach T5 auf die Dienst-Rollen umstellen). Nächste Task: T5.
- 2026-10-29 T5 (advisor): Restore meldet sich mit den Dienst-Rollen an statt als Superuser mit `SET ROLE`; `db-init` läuft vorher. `pg-restore.sh` ändert dabei seine Zugangsdaten (sichtbares Verhalten) → eigene Task T6 mit Frage an Kevin. Begründung privat.
- 2026-10-29 T3: Schritt 14 (Grenzen je Dienst) prüfte jeden Dienst als laufend; der Einmal-Dienst `db-init` aus T2 ist beendet und machte den Stack-Test rot. T3 prüft ihn am beendeten Container (Exit 0, `no-new-privileges`, pids-Limit aus der Compose-Konfiguration). Lokaler Stack-Lauf: `integration_stack_test: 83 passed, 0 failed` (ein früherer Lauf scheiterte flaky am Enroll mit 502, eigene Zeile).
- 2026-10-29 T2 (Prüfung): gekoppelte Dateien kamen dazu — Test-Overlay (`db-init` auf dem lokal gebauten Server-Image), die `.env` der Test-Stacks (`lib_e2e_stack.sh`), die Maskierung im Diagnose-Bundle (`scripts/diagnostics.sh`) und drei Dockerfile-Kommentare; darum mehr als acht Dateien.
- 2026-10-29 T1 (Prüfung): die Datenbanken bleiben beim Superuser, die Rollen besitzen nur das Schema `public`; `db-init` verbindet mit `search_path=pg_catalog`; `ah_ca` bekommt Rechte je Tabelle; Passwörter gehen als SCRAM-Verifier; neue Task T5 für die Restore-Skripte.
- 2026-10-29 T1: der Rollen-Test ist ein pytest der Server-Suite mit eigenem Postgres-Container statt `scripts/tests/db_roles_test.sh`: der CI-Job der Skript-Tests hat kein psycopg (nachrüsten wäre eine Workflow-Änderung), die Server-Jobs haben Docker und psycopg.
- 2026-10-29 Kevin: Plan freigegeben; der Scheduler bekommt eine eigene Rolle mit nur DML (Offene Frage 1).
