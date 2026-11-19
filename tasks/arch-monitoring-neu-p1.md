<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-monitoring-neu-p1 — Task-Ledger
Status: aktiv · Branch: feature/arch-monitoring-neu-p1 · Review: pro Task
Spec: docs/features/arch-monitoring-neu-p1.md (Roadmap R-1559, R-0805)
Heavy: linux-full — Server-Proxy-Freigabeliste (`monitoring_proxy`) und zwei Monitoring-Migrationen; kein Gateway-, PKI-, Agent-, FRP- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@39a08c2a7`. P1a der Monitoring-Neuordnung (ADR 0004, Kevins Schnitt 2026-11-19): Statuswechsel-Log,
Objektzustand, typisierte Objekte, Objekt-API. Unverändert bleiben `_details`, `MonitorStateOut`, `MonitorCheckOut`,
die Antwort von `GET /status/server/{id}/history`, Alerting und VictoriaMetrics; jede Checker-Task hält die
bestehenden `_details`-Tests unverändert grün. „Nicht erhoben“ (`not_collected`) nur in der Objekt-API. Neue
Quelldateien bekommen den SPDX-Header (`reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later
<datei>`). Postgres-Tests (`tests/test_migrations_smoke.py`, `tests/test_check_engine_concurrency.py`) laufen ohne
Postgres in `DATABASE_URL` als test-skip; die Tasks mit Migration oder Sperre fahren sie zusätzlich gegen die
Test-DB des Worktrees und nennen die Summary-Zeile im Commit-Body, die PR-CI fährt sie mit Postgres. Risikopfade
(`check_engine.py`, `routers/agent.py`, `schemas.py`, `alembic/versions/*`, `monitoring_proxy/*`): `security` je Task
dazu. Belegte Fehler außerhalb des Auftrags werden Roadmap-Zeilen (`roadmap.py add`).

### T1 — `execute_check` und `HttpChecker.run` in benannte Schritte zerlegen (R-0805)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/check_engine.py, apps/monitoring/app/checkers/http.py
Evidenz: run.sh[quick] monitoring: 4 passed, 0 failed, 14 skipped @7e98c031a 2026-11-19T14:53:51+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1/T1.verdict.json)
Änderung: Reines Refactoring ohne Verhaltensänderung: `execute_check` (`check_engine.py:459`) in Laden, Ausführen (samt `RunSkipped`), Metriken schreiben, Zustand sperren und anwenden, Melden; `HttpChecker.run` (`checkers/http.py:31`) in Anfrage, Bewertung, Ergebnis. Die Monitoring-Suite ist vorher und nachher grün (Summary-Zeile vorher im Commit-Body).
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: keine (interne Zerlegung, Verhalten unverändert)

### T2 — Statuswechsel-Log: Tabelle, Übernahme aus dem Alarm-Log, Schreiben, Aufbewahrung (R-1559)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/models.py, apps/monitoring/alembic/versions/d2f4a6c8e0b1_status_change_log.py, apps/monitoring/app/check_engine.py, apps/monitoring/app/scheduler.py, apps/monitoring/app/main.py, apps/monitoring/tests/test_status_log.py, apps/monitoring/tests/test_migrations_smoke.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @2cb20485d 2026-11-19T15:01:18+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1/T2.verdict.json)
Änderung: Modell `MonitorStatusChange` (`monitor_status_log`: `check_id` FK `ON DELETE CASCADE`, `object_key` NULL, `old_status`, `new_status`, `at`, `origin`; Indizes `(check_id, at)`, `(at)`) und Revision nach `a7c9e1f3b5d7`, die jede `monitor_alert_log`-Zeile als `origin = alert_log` übernimmt (Downgrade löscht nur die neue Tabelle). `apply_result` schreibt eine Check-Zeile, wenn der gedämpfte Status wechselt — damit beide Wege (Scheduler, Push). Tagesjob `system:history-cleanup` löscht Zeilen älter als 90 Tage. Tests: Zeile bei Wechsel auf beiden Wegen, keine ohne Wechsel und keine bei übersprungenem Lauf, Wechsel ohne Alarmregel und in der Wartung, Aufbewahrung, Upgrade mit Übernahme und Downgrade (Postgres).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_status_log.py tests/test_migrations_smoke.py tests/test_alembic_builtin.py tests/test_models_timestamps.py tests/test_execute_check.py tests/test_agent_report.py tests/test_scheduler.py tests/test_retention.py
Doku: → T9
Abhängt von: T1

### T3 — Verlaufsmarken aus dem Statuswechsel-Log (R-1559)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/history.py, apps/monitoring/tests/test_status_history.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @cf486269e 2026-11-19T15:05:38+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1/T3.verdict.json)
Änderung: `server_events` (`history.py:230`) liest die Check-Zeilen (`object_key IS NULL`) von `monitor_status_log` statt `MonitorAlertLog`; Antwortform, `EVENT_LIMIT` und `_SAME_EVENT` bleiben, ein Erstergebnis `ok`/`info` aus `pending` ist kein Ereignis. Die Ereignis-Tests legen ihre Zeilen künftig im Log an (Quelle gewechselt, Erwartungen gleich); neu: ein Wechsel ohne Alarmregel und einer in der Wartung erscheinen, übernommene Alarm-Log-Zeilen mehrerer Regeln zählen einmal.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_status_history.py tests/test_status_log.py
Doku: → T9
Abhängt von: T2

### T4 — Objektzustand: Tabelle, Objektergebnis, `apply_objects`, Rückfall-Objekt, Verschwundenes (R-1559)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/models.py, apps/monitoring/alembic/versions/e3a5c7e9f1b2_object_state.py, apps/monitoring/app/objects.py, apps/monitoring/app/check_engine.py, apps/monitoring/app/routers/agent.py, apps/monitoring/app/scheduler.py, apps/monitoring/tests/test_object_state.py, apps/monitoring/tests/test_migrations_smoke.py, apps/monitoring/tests/test_check_engine_concurrency.py
Änderung: Modell `MonitorObjectState` (`monitor_object_state`, Spalten nach Spec) und Revision nach T2. Neues Modul `app/objects.py` (SPDX): liest und kappt `_objects` (`{"complete", "items"}`), bildet `<server>/<kind>/<id>` (zentral ohne Server, über 200 Zeichen Hash-Suffix), `apply_objects` nach Variante C (ein Lesezugriff, nur geänderte Zeilen), Dämpfung je Objekt mit `next_fail_count`/`effective_status` (`fail_count` gedeckelt, `not_collected` gesund), `since`, `bad_since`, `gone_at` nur bei vollständigem Ergebnis, Log-Zeile je Objektwechsel; ohne `_objects` ein Rückfall-Objekt `<server>/check/<check_id>` mit dem gedämpften Check-Status (ohne eigene Log-Zeile). Aufruf in `apply_result`; Scheduler und Push-Weg (`routers/agent.py`) nehmen `_objects` wie `_details` aus den Metriken, nie zu VictoriaMetrics. Der Tagesjob aus T2 löscht verschwundene Objekte nach 30 Tagen. Neun Dateien: Migration, Engine, beide Aufrufer und Aufräumen sind ein Lebenszyklus und nur gemeinsam prüfbar. Tests: Schreiben nur bei Änderung, Dämpfung, `bad_since` über warning↔critical, verschwunden und zurück, unvollständiges Ergebnis, Rückfall-Objekt, übersprungener Lauf, `MonitorStateOut` nie `not_collected`, Aufräumen, Upgrade/Downgrade und parallele Ergebnisse desselben Checks (Postgres).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_object_state.py tests/test_status_log.py tests/test_migrations_smoke.py tests/test_alembic_builtin.py tests/test_models_timestamps.py tests/test_check_engine.py tests/test_check_engine_concurrency.py tests/test_execute_check.py tests/test_agent_report.py tests/test_victoria.py
Doku: → T9
Abhängt von: T2

### T5 — Speicher-Objekte: `disk` aus smart_health, `pool` aus zfs_health (R-1559)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/smart.py, apps/monitoring/app/checkers/plugins.py, apps/monitoring/tests/test_smart_checker.py, apps/monitoring/tests/test_plugin_checkers.py
Änderung: `SmartHealthChecker.evaluate` (`smart.py:255`) liefert je Platte ein Objekt `disk` (Schlüssel Modell + Seriennummer, ohne Seriennummer der Gerätepfad mit `stable = false`; WWN, sobald der Agent sie sendet), Status aus der Kategorie, Grund aus dem ersten Befund; vollständig. Eine schlafende Platte meldet weder Modell noch Seriennummer (R-1569): mit früherer Messung fehlt sie im Ergebnis, das dann unvollständig ist (ihr Objekt behält den letzten Stand wie `_details`), ohne frühere Messung ist sie `not_collected` unter dem Gerätepfad (`stable = false`). `ZfsHealthChecker.evaluate` (`plugins.py:281`) je Pool ein Objekt `pool`; vollständig. Ohne Datenblock unvollständig und leer. `_details` bleibt unverändert (bestehende Tests), neue Tests je Zustand.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_smart_checker.py tests/test_plugin_checkers.py
Doku: → T9
Abhängt von: T4

### T6 — Container- und Backup-Objekte: docker_health, proxmox_backup (R-1559, Objekt-Teil von R-1534)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/plugins.py, apps/monitoring/tests/test_plugin_checkers.py
Änderung: `DockerHealthChecker.evaluate` (`plugins.py:499`) je Container ein Objekt `container` (Schlüssel Compose-Projekt/Dienst/Nummer, solange der Agent keine Nummer sendet der Containername mit `stable = false`); vollständig. `ProxmoxBackupChecker.evaluate` (`plugins.py:106`) je VM ein Objekt `guest-backup` (VMID, `stable = false` bis zur Cluster-ID, R-0519); eine gestoppte VM unter `exclude_stopped` erscheint als `not_collected` mit Grund statt zu fehlen, `exclude_vmids` bleibt außen vor (P1b); vollständig. `_details` unverändert.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_plugin_checkers.py
Doku: → T9
Abhängt von: T5

### T7 — Host-Objekte: cpu, memory, mount, sensor aus agent_resources; reboot, updates, clock aus system_state (R-1559)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/agent.py, apps/monitoring/app/checkers/system.py, apps/monitoring/tests/test_agent_resources_checker.py, apps/monitoring/tests/test_system_state_checker.py
Änderung: `AgentResourcesChecker.evaluate` (`agent.py:620`) liefert `cpu`, `memory`, je Mount `mount` (Pfad, `ignore_mounts` außen vor) und je Sensor `sensor` (Chip/Label) mit dem Status aus dem `_Grader`; vollständig. `SystemStateChecker.evaluate` (`system.py:100`) liefert `reboot`, `updates`, `clock`; ohne Systemzustand im Report unvollständig und leer. `_details` unverändert.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_resources_checker.py tests/test_system_state_checker.py
Doku: → T9
Abhängt von: T4

### T8 — Dienst-Objekte aus service_process (R-1559)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_service_process_checker.py
Änderung: `ServiceProcessChecker.evaluate` (`agent.py:685`) je Dienst ein Objekt `service` (voller Unit-Name; Windows kleingeschrieben, FreeBSD rc-Name); im Auto-Modus kennt der Report nur die fehlgeschlagenen Units, das Ergebnis ist unvollständig, im Listen-Modus vollständig; `ignore` bleibt außen vor (P1b). `_details` unverändert.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_service_process_checker.py
Doku: → T9
Abhängt von: T7

### T9 — Objekt-API `GET /objects`, Proxy-Präfix `objects`, Doku DE+EN (R-1559)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/objects.py, apps/monitoring/app/routers/__init__.py, apps/monitoring/app/schemas.py, apps/monitoring/tests/test_objects_api.py, apps/monitoring/tests/openapi.snapshot.json, apps/server/app/modules/monitoring_proxy/router.py, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/arch-monitoring-neu-p1.md
Änderung: Neuer Router `routers/objects.py` (SPDX) mit `GET /objects` (Filter `server_id`, `check_id`, `kind`, `include_gone`; `limit`/`offset`, `X-Total-Count`; schlechteste zuerst, dann Name; `lastCheck` aus `MonitorState`), Schema `MonitorObjectOut`, Eintrag in `all_routers`, OpenAPI-Snapshot. Das Präfix `objects` kommt in `_ALLOWED_PATH_PREFIXES` (`monitoring_proxy/router.py:78`): der Server-Test `test_monitoring_proxy_allowlist.py` liest die Monitoring-Router und die vier Präfix-Listen der Entwickler-Doku, deshalb landen Route, Freigabe und Doku in einem Commit, und das Verify fährt beide Suiten. Dazu die übrige Doku: Statuswechsel-Log, Objektzustand und Objektergebnis, Tagesjob und Quelle der Verlaufsmarken (developer/monitoring DE+EN), `GET /objects` (api-reference DE+EN), Verlaufsmarken (admin/monitoring DE+EN), Changelog-Fragment. 13 Dateien: Route und Freigabe müssen zusammen landen, die Doku nennt beide.
Verify: bash scripts/dev/verify.sh monitoring server --strict
Doku: docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/arch-monitoring-neu-p1.md
Abhängt von: T3, T4

## Entscheidungen
- 2026-11-19 Plan: Schnitt P1a „Verlauf + Objekte“, P1b–P1e eigene Zeilen, vier Punkte nach P2, „nicht erhoben“ nur in der Objekt-API, verschwundene Objekte 30 Tage — Kevin 2026-11-19 (AskUserQuestion).
- 2026-11-19 Plan: die Log-Revision übernimmt `monitor_alert_log` einmal (`origin = alert_log`) — sonst wäre der Verlauf nach dem Update bis zu 90 Tage lückenhaft (ADR §13: jede Phase besser als vorher).
- 2026-11-19 Plan: „schlecht“ für `bad_since` = `warning`, `critical`, `unknown`; `not_collected` dämpft wie `ok` — ADR §3, „nicht erhoben“ ist kein Fehler.
- 2026-11-19 Plan: Objektschlüssel über 200 Zeichen werden mit Hash-Suffix gekürzt — die PK-Spalte ist `String(200)` (ADR §5), ein Abschneiden ohne Hash ließe zwei Objekte kollidieren.
- 2026-11-19 Plan: Route, Proxy-Präfix und Doku in einer Task (T9) — `test_monitoring_proxy_allowlist.py` liest Monitoring-Router und Präfixlisten der Doku, jede Teilmenge allein ist rot.
- 2026-11-19 Plan: Aufbewahrung als Konstanten (90 Tage Log, 30 Tage verschwunden), keine neuen Umgebungsvariablen — YAGNI, ADR §5.
