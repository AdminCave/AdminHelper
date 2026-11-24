<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-testdb-1 — Task-Ledger
Status: erledigt · Branch: feature/kern-testdb-1 · Review: pro Task
Spec: docs/features/kern-testdb-1.md (Roadmap R-0700)
Heavy: none — nur Testdateien und DEVELOPMENT.md; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Monitoring: gemeinsamer Fixture db_engine, client_db auf Postgres  [x]
Komponente: monitoring · Dateien: apps/monitoring/tests/conftest.py, apps/monitoring/tests/test_health.py, apps/monitoring/tests/test_response_shapes.py
Evidenz: run.sh[quick] monitoring: 4 passed, 0 failed, 14 skipped @25bf2b881 2026-11-24T13:15:54+01:00
Review: approve (.ah-out/review/kern-testdb-1/T1.verdict.json)
Änderung: R-0700. Neuer Fixture `db_engine`: mit einer Postgres-URL aus `DATABASE_URL`, sonst `AH_TEST_DB`, eine abgeleitete Datenbank `<db>_mon_unit` (anlegen, wenn sie fehlt; Schema einmal je Lauf über `Base.metadata.create_all`), nach jedem Test `TRUNCATE … RESTART IDENTITY CASCADE` über alle Tabellen; ohne Postgres-URL die bisherige SQLite-Engine. `client_db` baut darauf. Laufzeit der Suite vorher und nachher in `## Entscheidungen`.
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: → T6

### T2 — Monitoring: eigene Engines A (Alerter, Check-Engine, Status)  [x]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_alerter.py, apps/monitoring/tests/test_alerter_hub.py, apps/monitoring/tests/test_check_engine.py, apps/monitoring/tests/test_check_engine_context.py, apps/monitoring/tests/test_execute_check.py, apps/monitoring/tests/test_object_state.py, apps/monitoring/tests/test_status_log.py, apps/monitoring/tests/test_status_page_api.py, apps/monitoring/tests/test_status_info.py, apps/monitoring/tests/test_bell_catch_up.py, apps/monitoring/tests/test_bell_removed_checks.py, apps/monitoring/tests/conftest.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @cc8b63c02 2026-11-24T13:27:20+01:00
Review: approve (.ah-out/review/kern-testdb-1/T2.verdict.json)
Änderung: R-0700. Die eigenen SQLite-Engines dieser Dateien weichen `db_engine` (bzw. `client_db`). Elf Dateien statt acht: je Datei ein Engine-Block, gemeinsam getestet über die Alarm- und Statuskette. Ein Produktfehler, den Postgres zeigt, wird eine BUG-Zeile; die Datei behält dann ihre Engine (Spec, Risiken).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alerter.py tests/test_alerter_hub.py tests/test_check_engine.py tests/test_check_engine_context.py tests/test_execute_check.py tests/test_object_state.py tests/test_status_log.py tests/test_status_page_api.py tests/test_status_info.py tests/test_bell_catch_up.py tests/test_bell_removed_checks.py
Doku: → T6
Abhängt von: T1

### T3 — Monitoring: eigene Engines B (Agent, Router, Dienste)  [x]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_agent_report.py, apps/monitoring/tests/test_agent_ping_checker.py, apps/monitoring/tests/test_admin_router.py, apps/monitoring/tests/test_require_agent.py, apps/monitoring/tests/test_pagination.py, apps/monitoring/tests/test_checks_metrics.py, apps/monitoring/tests/test_checker_messages.py, apps/monitoring/tests/test_alert_secrets.py, apps/monitoring/tests/test_alert_bundle.py, apps/monitoring/tests/test_service_process_checker.py, apps/monitoring/tests/test_service_tables.py, apps/monitoring/tests/test_service_inventory.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @9762c4f9b 2026-11-24T13:34:13+01:00
Review: approve (.ah-out/review/kern-testdb-1/T3.verdict.json)
Änderung: R-0700, wie T2 für diese Dateien. Zwölf Dateien: je Datei ein Engine-Block.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_report.py tests/test_agent_ping_checker.py tests/test_admin_router.py tests/test_require_agent.py tests/test_pagination.py tests/test_checks_metrics.py tests/test_checker_messages.py tests/test_alert_secrets.py tests/test_alert_bundle.py tests/test_service_process_checker.py tests/test_service_tables.py tests/test_service_inventory.py
Doku: → T6
Abhängt von: T1

### T4 — Monitoring: eigene Engines C (Vorlagen, Module, Seed, Scheduler)  [x]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_templates_router.py, apps/monitoring/tests/test_template_sync.py, apps/monitoring/tests/test_template_overrides.py, apps/monitoring/tests/test_template_suggestions.py, apps/monitoring/tests/test_tag_sync.py, apps/monitoring/tests/test_module_tables.py, apps/monitoring/tests/test_module_sync.py, apps/monitoring/tests/test_discovery_match.py, apps/monitoring/tests/test_seed.py, apps/monitoring/tests/test_scheduler.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @e84af39ee 2026-11-24T13:41:52+01:00
Review: approve (.ah-out/review/kern-testdb-1/T4.verdict.json)
Änderung: R-0700, wie T2 für diese Dateien. Zehn Dateien: je Datei ein Engine-Block.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_templates_router.py tests/test_template_sync.py tests/test_template_overrides.py tests/test_template_suggestions.py tests/test_tag_sync.py tests/test_module_tables.py tests/test_module_sync.py tests/test_discovery_match.py tests/test_seed.py tests/test_scheduler.py
Doku: → T6
Abhängt von: T1

### T5 — CA-Issuer: DB-Tests auf Postgres  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/tests/conftest.py, apps/ca-issuer/tests/test_db_token_store.py, apps/ca-issuer/tests/test_inventory.py, apps/ca-issuer/tests/test_enroll_renew.py, apps/ca-issuer/tests/test_cli.py
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @a3448a5be 2026-11-24T13:45:43+01:00
Review: approve (.ah-out/review/kern-testdb-1/T5.verdict.json)
Änderung: R-0700. Fixture `db_engine` wie T1 (abgeleitete Datenbank `<db>_ca_unit`, `db.metadata.create_all`, `TRUNCATE` je Test, ohne Postgres-URL SQLite). Die SQLite-Engines in den vier Testdateien weichen ihm; Tests, die bewusst einen SQLite-Zweig prüfen, bleiben auf SQLite und sagen das im Namen.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_db_token_store.py tests/test_inventory.py tests/test_enroll_renew.py tests/test_cli.py
Doku: → T6

### T6 — Doku: welche Suite auf welcher Datenbank läuft  [x]
Komponente: scripts · Dateien: DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @4fd86443d 2026-11-24T13:56:52+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: R-0700. Der Abschnitt „Postgres-gegattert“ und die lokalen Python-Tests nennen: Monitoring und CA-Issuer laufen auf Postgres, sobald `DATABASE_URL` oder `AH_TEST_DB` auf eines zeigt (eigene abgeleitete Datenbank), sonst auf SQLite.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende

### T7 — Monitoring: abgeleitete Test-DB am Laufende droppen  [x]
Komponente: monitoring · Dateien: apps/monitoring/tests/conftest.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @5707b8ffc 2026-11-24T14:07:12+01:00
Review: approve (.ah-out/review/kern-testdb-1/T7.verdict.json)
Änderung: R-0700, Abschlussprüfung (wichtig): `_postgres_unit_engine` dropt `<db>_mon_unit` nach `dispose()` mit `DROP DATABASE IF EXISTS … WITH (FORCE)`, sonst bliebe sie nach `worktree-teardown.sh` je Worktree liegen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_tag_sync.py
Doku: keine (Test-Infrastruktur, DEVELOPMENT.md nennt nur die abgeleitete Datenbank)

### T8 — CA-Issuer: abgeleitete Test-DB am Laufende droppen  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/tests/conftest.py, DEVELOPMENT.md
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @07f8133c3 2026-11-24T14:08:20+01:00
Review: approve (.ah-out/review/kern-testdb-1/T8.verdict.json)
Änderung: R-0700, Abschlussprüfung (wichtig): wie T7 für `<db>_ca_unit`.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_db_token_store.py
Doku: DEVELOPMENT.md (anlegen je Lauf, löschen am Ende; Nit aus T7)

## Entscheidungen
- 2026-11-24 (T1): Laufzeit der Monitoring-Suite auf der Dev-Box: SQLite 225 s (`pytest -q`, ohne Postgres-URL), Postgres 253 s (195 s + 58 s der zweiten Stufe von `run.sh`), etwa +12 %. Der 15-Minuten-Deckel des CI-Jobs bleibt weit entfernt.
- 2026-11-24 (T1): `test_health` und `test_response_shapes` legen Alarm-Log-Zeilen in derselben Session wie ihre Regeln an; ohne ORM-Beziehung ordnet SQLAlchemy die Regel nicht zuerst ein, Postgres prüft den Fremdschlüssel. Die Tests flushen die Regeln vorher (Test-Annahme, kein Produktfehler).
- 2026-11-24 (T2): Tests, die einen echten Pool brauchen (`engine.pool.checkedout()`, eine Verbindung je Session: R-0615-Pooltests, Glocken-Dispatch), laufen auf dem neuen Fixture `pooled_engine`: auf Postgres eine eigene Engine auf derselben Datenbank (eine von einem anderen Test offen gelassene Session zählt so nicht mit), ohne Postgres die bisherige Datei-SQLite mit QueuePool; die `StaticPool`-Rückfallebene zählt nichts.
- 2026-11-24 (T2): Die Cooldown-Tests in `test_alerter` schrieben Log-Zeilen ohne die Check- und Regel-Zeilen, für die `make_check()`/`make_rule()` stehen; das Fixture legt sie jetzt an (Regel deaktiviert, damit `process_alert` nur die Regeln des Tests sieht). Sessions, die Tests offen ließen (`_HostDownDb`, Cooldown-Fixture, `test_only_enabled_rules…`), werden geschlossen, sonst wartet das `TRUNCATE` des nächsten Tests auf ihre Sperre. Kein Produktfehler.
- 2026-11-24 (T3): `test_failed_host_facts_store_is_only_logged` erzwang den fehlschlagenden Flush mit einem SQLite-Trigger (`RAISE(ABORT)`). Auf Postgres legt der Helfer `_refusing_host_facts` eine Trigger-Funktion mit SQLSTATE 23000 an (dieselbe `IntegrityError`) und entfernt Trigger und Funktion danach wieder, weil `TRUNCATE` sie auf der geteilten Datenbank nicht abräumt; zwei Läufe nacheinander grün. Der R-0615-Pooltest in `test_checks_metrics` läuft auf `pooled_engine`.
- 2026-11-24 (T4): `test_template_overrides` schaltete die Fremdschlüssel per `connect`-Listener ein; auf `db_engine` ist die Verbindung des SQLite-Rückfalls schon offen, also setzt das Fixture das Pragma direkt auf ihr (Postgres prüft ohnehin). `test_alert_log_cleanup_removes_only_old_entries` legt die Check- und Regel-Zeilen an, auf die die Log-Zeilen zeigen. `test_binding_for_deleted_template_is_skipped` stellt die verwaiste Bindung über ein gepatchtes `db.get` her (auf Postgres kaskadiert das Löschen der Vorlage die Bindung weg) und verlangt keinen Log-Eintrag; Gegenprobe ohne den `template is None`-Zweig rot.
- 2026-11-24 (T5): Der CA-Fixture liest die Postgres-URL einmal beim Import: viele CLI-Tests setzen `DATABASE_URL` per monkeypatch auf einen unerreichbaren Host. `pg_engine` (TOCTOU, Zeilensperre) nimmt eine eigene Engine auf `<db>_ca_unit` statt `create_all`/`drop_all` auf der geteilten Test-DB. Bewusst SQLite bleiben nur die Fälle ohne Tabellen (`_sqlite_without_tables` in `test_inventory`, der parametrisierte Fall in `test_cli`). Vor dem TRUNCATE hebt der Fixture `statement_timeout` per `SET LOCAL` auf 30 s: `db.make_engine` begrenzt jede Anweisung auf 5 s, Sperrwartezeit eingeschlossen, sonst wäre der `lock_timeout` wirkungslos (Prüfer T5, Runde 1).
