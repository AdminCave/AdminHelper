<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-testdb-1 — Task-Ledger
Status: aktiv · Branch: feature/kern-testdb-1 · Review: pro Task
Spec: docs/features/kern-testdb-1.md (Roadmap R-0700)
Heavy: none — nur Testdateien und DEVELOPMENT.md; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Monitoring: gemeinsamer Fixture db_engine, client_db auf Postgres  [ ]
Komponente: monitoring · Dateien: apps/monitoring/tests/conftest.py
Änderung: R-0700. Neuer Fixture `db_engine`: mit einer Postgres-URL aus `DATABASE_URL`, sonst `AH_TEST_DB`, eine abgeleitete Datenbank `<db>_mon_unit` (anlegen, wenn sie fehlt; Schema einmal je Lauf über `Base.metadata.create_all`), nach jedem Test `TRUNCATE … RESTART IDENTITY CASCADE` über alle Tabellen; ohne Postgres-URL die bisherige SQLite-Engine. `client_db` baut darauf. Laufzeit der Suite vorher und nachher in `## Entscheidungen`.
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: → T6

### T2 — Monitoring: eigene Engines A (Alerter, Check-Engine, Status)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_alerter.py, apps/monitoring/tests/test_alerter_hub.py, apps/monitoring/tests/test_check_engine.py, apps/monitoring/tests/test_check_engine_context.py, apps/monitoring/tests/test_execute_check.py, apps/monitoring/tests/test_object_state.py, apps/monitoring/tests/test_status_log.py, apps/monitoring/tests/test_status_page_api.py, apps/monitoring/tests/test_status_info.py, apps/monitoring/tests/test_bell_catch_up.py, apps/monitoring/tests/test_bell_removed_checks.py
Änderung: R-0700. Die eigenen SQLite-Engines dieser Dateien weichen `db_engine` (bzw. `client_db`). Elf Dateien statt acht: je Datei ein Engine-Block, gemeinsam getestet über die Alarm- und Statuskette. Ein Produktfehler, den Postgres zeigt, wird eine BUG-Zeile; die Datei behält dann ihre Engine (Spec, Risiken).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alerter.py tests/test_alerter_hub.py tests/test_check_engine.py tests/test_check_engine_context.py tests/test_execute_check.py tests/test_object_state.py tests/test_status_log.py tests/test_status_page_api.py tests/test_status_info.py tests/test_bell_catch_up.py tests/test_bell_removed_checks.py
Doku: → T6
Abhängt von: T1

### T3 — Monitoring: eigene Engines B (Agent, Router, Dienste)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_agent_report.py, apps/monitoring/tests/test_agent_ping_checker.py, apps/monitoring/tests/test_admin_router.py, apps/monitoring/tests/test_require_agent.py, apps/monitoring/tests/test_pagination.py, apps/monitoring/tests/test_checks_metrics.py, apps/monitoring/tests/test_checker_messages.py, apps/monitoring/tests/test_alert_secrets.py, apps/monitoring/tests/test_alert_bundle.py, apps/monitoring/tests/test_service_process_checker.py, apps/monitoring/tests/test_service_tables.py, apps/monitoring/tests/test_service_inventory.py
Änderung: R-0700, wie T2 für diese Dateien. Zwölf Dateien: je Datei ein Engine-Block.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_report.py tests/test_agent_ping_checker.py tests/test_admin_router.py tests/test_require_agent.py tests/test_pagination.py tests/test_checks_metrics.py tests/test_checker_messages.py tests/test_alert_secrets.py tests/test_alert_bundle.py tests/test_service_process_checker.py tests/test_service_tables.py tests/test_service_inventory.py
Doku: → T6
Abhängt von: T1

### T4 — Monitoring: eigene Engines C (Vorlagen, Module, Seed, Scheduler)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_templates_router.py, apps/monitoring/tests/test_template_sync.py, apps/monitoring/tests/test_template_overrides.py, apps/monitoring/tests/test_template_suggestions.py, apps/monitoring/tests/test_tag_sync.py, apps/monitoring/tests/test_module_tables.py, apps/monitoring/tests/test_module_sync.py, apps/monitoring/tests/test_discovery_match.py, apps/monitoring/tests/test_seed.py, apps/monitoring/tests/test_scheduler.py
Änderung: R-0700, wie T2 für diese Dateien. Zehn Dateien: je Datei ein Engine-Block.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_templates_router.py tests/test_template_sync.py tests/test_template_overrides.py tests/test_template_suggestions.py tests/test_tag_sync.py tests/test_module_tables.py tests/test_module_sync.py tests/test_discovery_match.py tests/test_seed.py tests/test_scheduler.py
Doku: → T6
Abhängt von: T1

### T5 — CA-Issuer: DB-Tests auf Postgres  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/tests/conftest.py, apps/ca-issuer/tests/test_db_token_store.py, apps/ca-issuer/tests/test_inventory.py, apps/ca-issuer/tests/test_enroll_renew.py, apps/ca-issuer/tests/test_cli.py
Änderung: R-0700. Fixture `db_engine` wie T1 (abgeleitete Datenbank `<db>_ca_unit`, `db.metadata.create_all`, `TRUNCATE` je Test, ohne Postgres-URL SQLite). Die SQLite-Engines in den vier Testdateien weichen ihm; Tests, die bewusst einen SQLite-Zweig prüfen, bleiben auf SQLite und sagen das im Namen.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_db_token_store.py tests/test_inventory.py tests/test_enroll_renew.py tests/test_cli.py
Doku: → T6

### T6 — Doku: welche Suite auf welcher Datenbank läuft  [ ]
Komponente: scripts · Dateien: DEVELOPMENT.md
Änderung: R-0700. Der Abschnitt „Postgres-gegattert“ und die lokalen Python-Tests nennen: Monitoring und CA-Issuer laufen auf Postgres, sobald `DATABASE_URL` oder `AH_TEST_DB` auf eines zeigt (eigene abgeleitete Datenbank), sonst auf SQLite.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
