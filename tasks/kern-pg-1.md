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

### T2 — Compose auf 18 mit neuem Volume, Migration in update.sh (R-1035)  [ ]
Komponente: scripts · Dateien: docker-compose.yml, scripts/update.sh, scripts/tests/update_test.sh, changelog.d/kern-pg-1.md
Änderung: `postgres:18-alpine` mit Index-Digest, Volume `postgres18-data:/var/lib/postgresql` (auch im auskommentierten Backup-Dienst das Image). `update.sh` migriert nach dem Pull wie in der Spec (Ablauf 1–5): nur bei altem Volume ohne neues, Platzprüfung, Dienste stoppen, `pg_dumpall` mit dem 18er-Image, frisches 18 + Einspielen; der Rollback entfernt ein in diesem Lauf angelegtes neues Volume, das alte bleibt. `update_test.sh`: neue Fälle für Migration, keine Migration, Platzmangel, Dump-/Einspiel-Fehler und den Rollback mit Volume-Entfernung (Docker-Stub). Release Notes 18 und die Upgrade-Doku wörtlich unter `## Entscheidungen`; Container-Probe 17 → 18 mit echten Images.
Verify: bash scripts/dev/verify.sh scripts --strict -- update_test
Doku: changelog.d/kern-pg-1.md · → T4

### T3 — install/restore/uninstall kennen das neue Volume (R-1035)  [ ]
Komponente: scripts · Dateien: scripts/install.sh, scripts/restore.sh, scripts/uninstall.sh, scripts/tests/install_test.sh, scripts/tests/restore_guard_test.sh
Änderung: `install.sh` erkennt eine bestehende Installation an `postgres18-data` und am alten `postgres-data` (Meldungen nennen das Volume, das es fand); `restore.sh` prüft `postgres18-data`; `uninstall.sh` nennt beide im Kopf (der Lauf löscht per Projekt-Label schon beide). Tests je Fall.
Verify: bash scripts/dev/verify.sh scripts --strict -- install_test restore_guard_test uninstall_test
Doku: → T4

### T4 — Doku PostgreSQL 18 und das alte Volume (R-1035)  [ ]
Komponente: docs · Dateien: README.md, DEVELOPMENT.md, docs/admin/index.html, docs/en/admin/index.html, docs/admin/betrieb.html, docs/en/admin/operations.html, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html, docs/developer/server.html, docs/en/developer/server.html, docs/developer/index.html, docs/en/developer/index.html
Änderung: Version 18 und Volume `postgres18-data`; im Update-Abschnitt: das erste Update auf diese Version migriert per Dump, das alte Volume `<projekt>_postgres-data` bleibt als Rollback und wird nach der Prüfung mit `docker volume rm` entfernt; Troubleshooting zum Installer-Fund beider Volumes. Zwölf Dateien: je Seite DE+EN.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: die genannten Dateien
Task-Review: am Ende

## Entscheidungen
