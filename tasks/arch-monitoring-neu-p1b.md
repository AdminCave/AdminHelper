<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-monitoring-neu-p1b — Task-Ledger
Status: aktiv · Branch: feature/arch-monitoring-neu-p1b · Review: pro Task
Spec: docs/features/arch-monitoring-neu-p1b.md (Roadmap R-1636)
Heavy: linux-full — Server-Proxy (Präfix `exceptions`, Akteur-Header in `monitoring_proxy`) und eine Monitoring-Migration; kein Gateway-, PKI-, Agent-, FRP- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@201914265`. P1b der Monitoring-Neuordnung (ADR 0004 §7, §10; Kevins Schnitt 2026-11-19,
Entscheidungen 2026-11-25 in der Spec): Ausnahme-Modell mit der Wirkung „nicht melden“, Wartung als Fassade,
Akteur vom Proxy, per Einstellung ausgenommene Objekte in der Objekt-API. Unverändert bleiben `MonitorCheckOut`,
`MonitorStateOut`, der Vertrag von `/maintenance` (`MaintenanceInput`/`MaintenanceOut`), `_details` und Status der
Checker, die Check-Engine und VictoriaMetrics. Tests, die heute Wartungsfenster direkt in `monitor_maintenance`
anlegen, legen sie ab T2 über einen Helfer in `tests/_helpers.py` als Ausnahme in Wartungsform an; ihre Erwartungen
bleiben unverändert (gleichwertiger Ersatz, kein Test fällt weg; im Prüfauftrag nennen). Neue Quelldateien bekommen
den SPDX-Header (`reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later <datei>`). Postgres-Tests
(`tests/test_migrations_smoke.py`) laufen ohne Postgres in `DATABASE_URL` als test-skip; die Tasks mit Migration
fahren sie zusätzlich gegen die Test-DB des Worktrees und nennen die Summary-Zeile im Commit-Body, die PR-CI fährt
sie mit Postgres. Risikopfade (`alembic/versions/*`, `schemas.py`, `alerter.py`, `monitoring_proxy/*`): `security`
je Task dazu. Überschneidung mit P1d (R-1638, eigene arch-Session): `schemas.py`, Alembic-Kopf, Checker; vor jedem
Push `origin/main` hereinmergen und `scripts/dev/overlap.sh` fahren, wer zweiter merged, hängt seine Revision um.
Belegte Fehler außerhalb des Auftrags werden Roadmap-Zeilen (`roadmap.py add`).

### T1 — Ausnahme-Modell: Tabelle, Übernahme der Wartungsfenster, Auswerter (R-1636)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/models.py, apps/monitoring/alembic/versions/f4b6d8a0c2e4_exceptions.py, apps/monitoring/app/maintenance.py, apps/monitoring/app/exception_scope.py, apps/monitoring/tests/test_exception_scope.py, apps/monitoring/tests/test_migrations_smoke.py, apps/monitoring/tests/test_models_timestamps.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @28f6c5c13 2026-11-25T15:22:41+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1b/T1.verdict.json)
Änderung: Modell `MonitorException` (`monitor_exceptions`, Spalten wie Spec, `check_id` FK `ON DELETE CASCADE`, Indizes auf `server_id` und `check_id`, `to_dict` mit `iso_utc`) und Spalte `MonitorObjectState.excluded`; `MonitorMaintenance` (`models.py:537`) bleibt, bekommt `synonym` `duration_kind`/`reason`. Revision `f4b6d8a0c2e4` (SPDX) nach `e3a5c7e9f1b2`: Tabelle, Spalte, idempotente 1:1-Übernahme aus `monitor_maintenance` (gleiche ID, NULL-`enabled` → `false`, `origin = migration`); Downgrade schreibt die Ausnahmen in Wartungsform zurück und entfernt Spalte und Tabelle. `app/maintenance.py` (`maintenance_intervals` `:84`, `is_in_maintenance` `:119`) liest `duration_kind`/`reason`; neu `app/exception_scope.py` (SPDX): gilt, deckt, engste, Wartungsform, Laden der geltenden `no_notify`-Zeilen. Tests: Auswerter (Dauerarten, beendet, ausgeschaltet, Rangfolge Check > Check-Typ > Server > alle); Postgres-Äquivalenz alt ↔ neu über ein Zeitraster (einmalig, wöchentlich über Mitternacht, Sommerzeitwechsel, global, ausgeschaltet, NULL-`enabled`, ohne Zeitfelder), Spalten 1:1, Downgrade → Upgrade; `_EXPECTED` in `test_models_timestamps.py` um die Zeitfelder der Ausnahme.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_exception_scope.py tests/test_maintenance.py tests/test_migrations_smoke.py tests/test_models_timestamps.py tests/test_alembic_builtin.py
Doku: → T7

### T2 — Leser und Fassade `/maintenance` auf Ausnahmen (R-1636)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/alerter.py, apps/monitoring/app/alert_bundle.py, apps/monitoring/app/history.py, apps/monitoring/app/server_cleanup.py, apps/monitoring/app/routers/maintenance.py, apps/monitoring/app/schemas.py, apps/monitoring/tests/_helpers.py, apps/monitoring/tests/test_alerter.py, apps/monitoring/tests/test_alerter_sent_state.py, apps/monitoring/tests/test_alert_bundle.py, apps/monitoring/tests/test_status_history.py, apps/monitoring/tests/test_status_log.py, apps/monitoring/tests/test_bell_catch_up.py, apps/monitoring/tests/test_status_page_api.py, apps/monitoring/tests/test_response_shapes.py, apps/monitoring/tests/test_template_sync.py, apps/monitoring/tests/test_maintenance_router.py, apps/monitoring/tests/test_migrations_smoke.py, apps/monitoring/app/maintenance.py, apps/monitoring/app/exception_scope.py, apps/monitoring/alembic/versions/f4b6d8a0c2e4_exceptions.py, apps/monitoring/tests/test_exception_scope.py, apps/monitoring/tests/test_tag_sync.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @e6f62023d 2026-11-25T15:35:59+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1b/T2.verdict.json)
Änderung: `muted_reason`/`muted_reasons` (`alerter.py:371`, `:441`): stummer Check > engste geltende `no_notify`-Ausnahme (`"maintenance window"` in Wartungsform, sonst `"exception"`) > Host down, beide im Gleichlauf. `_awaits_check` (`alert_bundle.py:191`), `server_maintenance` (`history.py:274`, nur Wartungsform) und `known_server_ids`/`cleanup_server` (`server_cleanup.py:43`, `:104`, Ausnahmen des Servers hart löschen, Altzeilen wie bisher) lesen Ausnahmen. `/maintenance` wird Fassade: Liste = Ausnahmen in Wartungsform, Anlegen `origin = maintenance`, `PUT`/`DELETE` nur auf Wartungsform (sonst 404), `DELETE` beendet. Kommentar zu `mutedReason` (`schemas.py:365`). Die Tests mit direkt angelegten Fenstern wechseln auf den Helfer in `_helpers.py` (auch `_CapturingDb.query`), Erwartungen unverändert; `test_maintenance_router.py` bleibt in den bestehenden Tests unverändert (Beleg für den gleichen Vertrag) und bekommt Tests für „Beenden statt Löschen“, 404 auf Nicht-Wartungsform und `"exception"`; `test_migrations_smoke.py` prüft, dass `GET /maintenance` nach dem Upgrade dieselbe Liste liefert wie `to_dict()` der Altzeilen. 18 Dateien: Leser, Fassade und die Tests, die Fenster anlegen, müssen zusammen wechseln, sonst schaltet ein über `/maintenance` angelegtes Fenster einen Commit lang nichts stumm.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alerter.py tests/test_alerter_sent_state.py tests/test_alert_bundle.py tests/test_status_history.py tests/test_status_log.py tests/test_bell_catch_up.py tests/test_status_page_api.py tests/test_response_shapes.py tests/test_template_sync.py tests/test_maintenance_router.py tests/test_maintenance.py tests/test_migrations_smoke.py tests/test_openapi_snapshot.py tests/test_exception_scope.py tests/test_tag_sync.py
Doku: → T7
Abhängt von: T1

### T3 — `/exceptions`: Router, Schemas, Aufbewahrung, Proxy-Präfix (R-1636)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/exceptions.py, apps/monitoring/app/routers/__init__.py, apps/monitoring/app/schemas.py, apps/monitoring/app/scheduler.py, apps/monitoring/tests/test_exceptions_api.py, apps/monitoring/tests/openapi.snapshot.json, apps/server/app/modules/monitoring_proxy/router.py, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html
Änderung: Router `routers/exceptions.py` (SPDX, `require_internal`): `GET /exceptions` (`include_ended`, Filter `server_id`/`check_id`), `POST` (201), `PUT` (404/409), `DELETE` (204, beendet; 404/409). Schemas `ExceptionInput` (Zeitfelder-Validierung wie `MaintenanceInput` `schemas.py:225`; 422 für jede Kombination außer `no_notify` × `check`/`check_type`/`server`/`all`, unbekannten Check oder Check-Typ, `reason` über 500) und `ExceptionOut` (camelCase, Spec). Tagesjob `_run_history_cleanup` (`scheduler.py:216`) löscht seit über 90 Tagen beendete Ausnahmen. Präfix `exceptions` in `_ALLOWED_PATH_PREFIXES` (`monitoring_proxy/router.py:82`) samt den vier Präfix-Listen der Entwickler-Doku, die `test_monitoring_proxy_allowlist.py` gegen die Router liest. Tests: CRUD, jede 422-Kombination, Beenden und 409, Liste mit/ohne beendete, Filter, Aufbewahrung, die Ausnahme schaltet über `muted_reason` stumm; OpenAPI-Snapshot. 11 Dateien: Route, Freigabe und die vier Doku-Listen müssen in einem Commit landen.
Verify: bash scripts/dev/verify.sh monitoring server --strict
Doku: Präfix-Listen in docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html; übrige Abschnitte → T7
Abhängt von: T2

### T4 — Akteur: Proxy-Header und Spur an der Ausnahme (R-1636)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/core/actor.py, apps/monitoring/app/routers/exceptions.py, apps/monitoring/app/routers/maintenance.py, apps/monitoring/tests/test_actor.py, apps/monitoring/tests/test_exceptions_api.py, apps/monitoring/tests/test_maintenance_router.py, apps/server/app/modules/monitoring_proxy/router.py, apps/server/tests/test_monitoring_proxy_audit.py
Änderung: `proxy_to_monitoring` (`monitoring_proxy/router.py:189`, Header-Block `:227`) setzt `X-AH-Actor-Id` (`<actor_type>:<actor_id>`) und `X-AH-Actor-Name` (prozentkodiert) aus `actor_from_request` (`apps/server/app/core/request_context.py:41`); kein Client-Header wird durchgereicht. Neu `app/core/actor.py` (SPDX): dekodieren, Steuerzeichen entfernen, Name auf 64 kürzen, 400 über 1024 Zeichen, ohne Header leer. `/exceptions` und `/maintenance` schreiben `created_*`, `updated_*`, `ended_*`. Tests: Server — gefälschte Akteur-Header des Clients kommen upstream nicht an, Umlaut-Name kommt kodiert an, ohne Anmeldung kein Akteur; Monitoring — Dekodieren, Kappen, 400, Spur an Anlegen/Ändern/Beenden über beide Router.
Verify: bash scripts/dev/verify.sh monitoring server --strict
Doku: → T7
Abhängt von: T3

### T5 — Checker melden per Einstellung ausgenommene Objekte (R-1636)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/objects.py, apps/monitoring/app/checkers/plugins.py, apps/monitoring/app/checkers/smart.py, apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_object_state.py, apps/monitoring/tests/test_plugin_checkers.py, apps/monitoring/tests/test_smart_checker.py, apps/monitoring/tests/test_agent_resources_checker.py, apps/monitoring/tests/test_service_process_checker.py
Änderung: Helfer in `app/objects.py` für ein ausgenommenes Objekt (`not_collected`, Grund `Excluded by setting <name>`, `excluded = <name>`); `_entry` (`:111`) und `_apply_item` (`:237`) tragen `excluded` in den Objektzustand. Statt `continue` melden die Checker den Eintrag über den Helfer: `exclude_vmids` (`plugins.py:169`, `:188`), `ignore_containers` (`plugins.py:641`), `ignore_devices` (`smart.py:288`), `ignore_mounts` (`agent.py:580`), Dienst-Globs (`agent.py:981`, je getroffene Unit). Tests je Liste: das Objekt erscheint mit Marke und Grund, Status, Nachricht und `_details` des Checks bleiben gleich (bestehende Tests unverändert grün), ein Objekt, das die Liste verlässt, verliert die Marke. 9 Dateien: ein Helfer und seine fünf Aufrufer mit ihren Tests.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_object_state.py tests/test_plugin_checkers.py tests/test_smart_checker.py tests/test_agent_resources_checker.py tests/test_service_process_checker.py tests/test_check_configs.py tests/test_checker_forecast.py tests/test_check_engine_context.py
Doku: → T7
Abhängt von: T1

### T6 — Objekt-API: Ausgenommene zuletzt, Feld `exception` (R-1636)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/objects.py, apps/monitoring/app/schemas.py, apps/monitoring/tests/test_objects_api.py, apps/monitoring/tests/openapi.snapshot.json
Änderung: `list_objects` (`routers/objects.py:39`) sortiert `excluded` zuletzt, dann schlechteste zuerst (`_WORST_FIRST` `:27`), Name, Check, Schlüssel; Feld `exception` je Objekt: aus `excluded` `{source: setting, setting, effect: skip}`, sonst die engste geltende Ausnahme des Checks `{source: exception, id, scopeKind, effect, reason}`, eine Abfrage je Aufruf, Zuordnung nach dem Paging. `MonitorObjectOut` (`schemas.py:321`) um `exception`. Tests: Reihenfolge, beide Quellen, Einstellung schlägt Ausnahme, engste Ausnahme, `no_notify` sortiert nicht, Paging; OpenAPI-Snapshot.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_objects_api.py tests/test_openapi_snapshot.py tests/test_response_shapes.py
Doku: → T7
Abhängt von: T2, T5

### T7 — Doku DE+EN und CHANGELOG (R-1636)  [ ]
Komponente: scripts · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/arch-monitoring-neu-p1b.md
Änderung: Entwickler-Doku Monitoring: Ausnahme-Modell (Geltung, Wirkung, Dauer, Spur, Herkunft), Wartung als Fassade, Leser, Akteur-Header, ausgenommene Objekte, Aufbewahrung, Rückweg der Migration. API-Referenz: `/exceptions`, `exception` an `GET /objects`, `mutedReason` `exception`, `DELETE /maintenance/{id}` beendet. Admin-Doku Monitoring: Löschen eines Wartungsfensters beendet es (90 Tage nachvollziehbar), per Einstellung ausgenommene Objekte. Changelog-Fragment umlautfrei.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende
Abhängt von: T1, T2, T3, T4, T5, T6

## Entscheidungen
- 2026-11-25 T1: Bei gleicher Geltung gewinnt die Ausnahme in Wartungsform, dann die kleinere ID (`exception_scope.narrowest`) — `mutedReason` bleibt `"maintenance window"`, solange ein Fenster des Servers läuft, und das Ergebnis hängt nie von der Zeilenreihenfolge ab.
- 2026-11-25 T1: `app/maintenance.py` bekommt das öffentliche `duration_active` (einmalig/wöchentlich), das `is_in_maintenance` und `exception_scope.in_force` teilen — eine Zeitlogik für Fenster und Ausnahmen statt zwei Kopien.
- 2026-11-25 T1: Kaskade der Check-Ausnahmen prüft nur der Postgres-Migrationstest — die SQLite-Ausweichdatenbank der Unit-Tests setzt `ON DELETE CASCADE` ohne `foreign_keys`-Pragma nicht um.
- 2026-11-25 T2: `_awaits_check` (Glocke) fragt `exception_scope.narrowest` statt nur Fenster des Servers — eine Check- oder Check-Typ-Ausnahme hält die Glocke genauso an wie die Benachrichtigung, sonst meldete sie nach dem Ende, was die Regel stummgeschaltet hatte.
- 2026-11-25 T2: `maintenance.is_in_maintenance` bleibt, ohne Leser im Dienst — es ist die Semantik der eingefrorenen Zeilen, gegen die der Äquivalenztest der Migration und die `maintenance_intervals`-Tests vergleichen.
- 2026-11-25 T2: Die zwei Nits des `security`-Urteils zu T1 (Wartungsform verlangt bei Geltung `server` eine `server_id`; Downgrade schreibt nur solche zurück; Docstrings von `maintenance_intervals`/`is_in_maintenance`) behebt T2, weil es dieselben Zeilen anfasst.
- 2026-11-25 T2: `DELETE /maintenance/{id}` setzt nur `ended_at`, `PUT` nur `updated_at`; die Akteursfelder (`*_by`, `*_by_id`) füllt T4 über die Akteurs-Header.
- 2026-11-25 T2: `cleanup_server` löscht die Ausnahmen des Servers hart, auch beendete; `known_server_ids` zählt sie, damit der Tag-Sync (R-1697) auch einen Server aufräumt, von dem nur noch eine Ausnahme übrig ist (`test_tag_sync.py`, deshalb 23 Dateien).
- 2026-11-25 T2: `test_response_shapes` legt das sparsame Fenster mit `enabled=False` statt `NULL` an — die Spalte ist `NOT NULL`; dass `NULL` beim Übernehmen `false` wird, prüft `test_migrations_smoke` (gleichwertiger Ersatz).
