<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-pg-1 — Task-Ledger
Status: aktiv · Branch: feature/kern-pg-1 · Review: pro Task
Spec: docs/features/kern-pg-1.md (Roadmap R-1035)
Heavy: linux-full — `docker-compose.yml` und der Upgrade-Pfad: `upgrade_path_test.sh` (letztes Release mit 17 → HEAD) und `backup_restore_test.sh` laufen im Sammellauf; kein multibox-Flag deckt update.sh
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Tests gegen PostgreSQL 18 (R-1035)  [ ]
Komponente: server · Dateien: apps/server/tests/conftest.py, apps/server/tests/test_db_roles.py, scripts/tests/sse_push_e2e.sh, DEVELOPMENT.md
Änderung: Testcontainer, Wegwerf-Container in `test_db_roles.py` und das SSE-E2E-Skript auf `postgres:18-alpine`; `DEVELOPMENT.md:220` nennt 18. Baut erst nach dem Merge von `feature/kern-laufzeit-2` (`sse_push_e2e.sh`).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_db_roles.py tests/test_migrations_smoke.py
Doku: DEVELOPMENT.md

### T2 — Compose auf 18 mit neuem Volume, Migration in update.sh (R-1035)  [x]
Komponente: scripts · Dateien: docker-compose.yml, scripts/update.sh, scripts/tests/update_test.sh, changelog.d/kern-pg-1.md, scripts/tests/upgrade_path_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @7d54722d 2026-11-05T08:10:43+01:00
Review: approve (.ah-out/review/kern-pg-1/T2.verdict.json)
Änderung: `postgres:18-alpine` mit Index-Digest, Volume `postgres18-data:/var/lib/postgresql` (auch im auskommentierten Backup-Dienst das Image). `update.sh` migriert nach dem Pull wie in der Spec (Ablauf 1–5): nur bei altem Volume ohne neues, Platzprüfung, Dienste stoppen, `pg_dumpall` mit dem 18er-Image, frisches 18 + Einspielen; der Rollback entfernt ein in diesem Lauf angelegtes neues Volume, das alte bleibt. `update_test.sh`: neue Fälle für Migration, keine Migration, Platzmangel, Dump-/Einspiel-Fehler und den Rollback mit Volume-Entfernung (Docker-Stub). Release Notes 18 und die Upgrade-Doku wörtlich unter `## Entscheidungen`; Container-Probe 17 → 18 mit echten Images.
Verify: bash scripts/dev/verify.sh scripts --strict -- update_test
Doku: changelog.d/kern-pg-1.md · → T4

### T3 — install/restore/uninstall kennen das neue Volume (R-1035)  [x]
Komponente: scripts · Dateien: scripts/install.sh, scripts/restore.sh, scripts/uninstall.sh, scripts/tests/install_test.sh, scripts/tests/restore_guard_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @0ed0cf1c 2026-11-05T07:14:27+01:00
Review: approve (.ah-out/review/kern-pg-1/T3.verdict.json)
Änderung: `install.sh` erkennt eine bestehende Installation an `postgres18-data` und am alten `postgres-data` (Meldungen nennen das Volume, das es fand); `restore.sh` prüft `postgres18-data`; `uninstall.sh` nennt beide im Kopf (der Lauf löscht per Projekt-Label schon beide). Tests je Fall.
Verify: bash scripts/dev/verify.sh scripts --strict -- install_test restore_guard_test uninstall_test
Doku: → T4

### T4 — Doku PostgreSQL 18 und das alte Volume (R-1035)  [x]
Komponente: scripts · Dateien: README.md, DEVELOPMENT.md, docs/admin/index.html, docs/en/admin/index.html, docs/admin/betrieb.html, docs/en/admin/operations.html, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html, docs/developer/server.html, docs/en/developer/server.html, docs/developer/index.html, docs/en/developer/index.html, docs/admin/installation.html, docs/en/admin/installation.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b0a67a57 2026-11-05T08:50:03+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Version 18 und Volume `postgres18-data`; im Update-Abschnitt: das erste Update auf diese Version migriert per Dump, das alte Volume `<projekt>_postgres-data` bleibt als Rollback und wird nach der Prüfung mit `docker volume rm` entfernt; Troubleshooting zum Installer-Fund beider Volumes. Zwölf Dateien: je Seite DE+EN.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: die genannten Dateien
Task-Review: am Ende

## Entscheidungen
- T3: Die Compose-Datei nennt das alte Volume `postgres-data` nach T2 nicht mehr (ein nur deklariertes Volume könnte Compose bei Neuinstallationen leer anlegen und die Migrationserkennung in `update.sh` täuschen; nicht verifiziert, darum vermieden). Deshalb hängt `install.sh` es an `project_volumes` an und entfernt es bei `--reset` nach `down -v` mit `docker volume rm`; `restore.sh` wertet es als bestehende Installation (die `.env` des Backups zählt dann nicht), prüft aber das Passwort am neuen Volume, weil Postgres 18 nur dieses öffnet. `uninstall.sh` löscht per Projekt-Label schon beide, nur der Kopf nennt das alte. Gegenprobe: neue Tests gegen den Stand vor T3 in einem Probe-Worktree, install_test 127 passed, 6 failed; restore_guard_test 76 passed, 1 failed.
- T2: Die Migration steht als markierter Block (`# >>> pg18-migration` … `# <<< pg18-migration`) in `update.sh`, kein eigenes Skript: die Dateiliste des Runtime-Bundles ist in `release.yml` fest kodiert, ein neues Skript bräuchte eine Workflow-Änderung. `upgrade_path_test.sh` lädt genau diesen Block und fährt ihn mit `docker compose` auf den Teststack gerichtet (Phase 3), der Block nutzt darum nur `docker`, `log` und `say`.
- T2: Erkennung vor dem Backup (eine Ablehnung ändert nichts) und nur, wenn die Ziel-Compose `postgres18-data` nennt (bestehende Fixtures von `update_test.sh` nennen es nicht, ihre Fälle bleiben unberührt). Fälle: altes Volume fehlt → kein Umzug; alt da, neu nicht, 17 läuft darauf → Umzug; alt da, neu nicht, 17 läuft nicht → Abbruch („start the installed stack“, der Dump braucht den laufenden Cluster); beide da und der Container auf dem alten → Abbruch mit `docker volume rm <neu>`; beide da sonst → gilt als umgezogen. Grenze: `kill -9` oder Stromausfall mitten im Einspielen lässt ein halb gefülltes neues Volume, das ohne laufendes 17 als umgezogen gilt; Signale rollen zurück (`rollback_signals`).
- T2: Platz: Docker-Root ≥ 2 × Clustergröße (`pg_database_size`), Install-Verzeichnis ≥ 1 × für den Dump (`backups/`, `mktemp`, 0600); liegen beide auf einem Dateisystem, zählt die Summe. Was nicht messbar ist (Größe, `df`), ist eine WARN, kein Abbruch: das alte Volume bleibt der Rückweg.
- T2: Einspielen: das frische 18 hat Rolle und Datenbank aus `POSTGRES_USER`/`POSTGRES_DB` schon, der Dump legt beide neu an. Also `DROP DATABASE adminhelper`, dann der Dump ohne die eine Zeile `CREATE ROLE adminhelper;` vor dem ersten `\connect`; `ALTER ROLE` trägt das Passwort (SCRAM) mit. Dump ohne Passwort über `--network container:<17>` und `-h 127.0.0.1` (pg_hba des Images: trust für 127.0.0.1).
- T2: `--no-rollback` behält keinen unfertigen Umzug (ein halb gefülltes neues Volume zählte beim nächsten Lauf als umgezogen) und meldet das; ein fertiger Umzug mit gescheitertem Start bleibt bei `--no-rollback` wie bisher stehen. Der Rollback nach einem Umzug entfernt Container und neues Volume (`pg18_undo`) und überspringt den Alembic-Vergleich: die neuen Images liefen nur auf dem neuen Volume, das alte trägt den Stand vor dem Update. `--redeploy` verweigert eine 18er-Compose, deren Daten noch im alten Volume liegen (leeres 18), und nennt `--ref v<installiert>`.
- T2: Doku-Zitate. postgresql.org/docs/18/upgrading.html: „It is recommended that you use the pg_dump and pg_dumpall programs from the _newer_ version of PostgreSQL … Current releases of the dump programs can read data from any server version back to 9.2.“ Image-Doku (docker-library/docs, postgres/README.md): „the `PGDATA` environment variable of the image was changed to be version specific in PostgreSQL 18 and above“; „The defined `VOLUME` was changed in 18 and above to `/var/lib/postgresql`.“ Release Notes 18, Inkompatibilitäten gegen unsere Nutzung: Daten-Prüfsummen per `initdb`-Default (betrifft nur `pg_upgrade`, wir dumpen); MD5-Passwörter veraltet (wir nutzen SCRAM, Probe: `rolpassword LIKE 'SCRAM%'`); COPY CSV und `\.`, unlogged partitionierte Tabellen, Rolle von AFTER-Triggern, FTS-Collation, PK/FK-Collations: nutzen wir nicht bzw. ändern nichts am Dump.
- T2: Proben mit echten Images (17.10 → 18.6): `pg_dumpall` aus 18 gegen 17 rc 0; plain restore scheitert an „role adminhelper already exists“, mit DROP + Filter rc 0; danach Revision, Zeilen, Grants, Monitor-DB und Rollen da. Der Block selbst aus `update.sh` gegen ein Compose-Projekt (17 auf `postgres-data` → Compose mit 18 auf `postgres18-data`): erkannt, Platz ok, übrige Dienste gestoppt, Dump weg, Revision/500 Zeilen/Grant/18.6, Mount `postgres18-data /var/lib/postgresql`, altes Volume da; `pg18_undo` entfernt das neue Volume, 17 startet wieder mit 500 Zeilen. Gegenprobe: die neuen Fälle von `update_test.sh` gegen `update.sh` von HEAD (ohne Umzug) in einem Probe-Worktree: 351 passed, 16 failed; grün bleiben nur „kein altes Volume“, „schon umgezogen“ und „--redeploy nach dem Umzug“.
- T2 (Review-Runde 1): Ein Update mit `--no-rollback`, das vor dem Deploy scheitert, lässt die Compose-Datei auf 18 und die Daten im alten Volume; ein Rollback des nächsten Laufs legte diese Datei zurück und startete sie auf einem leeren neuen Volume. `update.sh` verweigert darum bei fälligem Umzug eine installierte Compose, die `postgres18-data` schon nennt, vor dem Backup, mit dem Rückweg `--ref <Release davor>` (Prüfung an der Aufrufstelle, nicht im Block: `upgrade_path_test.sh` fährt den Block ohne installierte Compose). Gegenprobe ohne die Prüfung: update_test 367 passed, 1 failed (der neue Fall).
