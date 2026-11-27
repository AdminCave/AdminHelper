<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->
# kern-monitoring-56 — Task-Ledger
Status: bereit · Branch: feature/kern-monitoring-56 · Review: pro Task
Spec: docs/features/kern-monitoring-56.md (Roadmap R-1690, R-1696, R-1792, R-1827, R-1828)
Heavy: none — nur Monitoring-Logik und Schemas, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1690: eine Recovery startet den Regel-Cooldown nicht neu  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/alerter.py, apps/monitoring/tests/test_alerter_cooldown.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @dfcd36211 2026-11-27T21:02:57+01:00
Review: approve (.ah-out/review/kern-monitoring-56/T1.verdict.json)
Änderung: `_is_in_cooldown` zählt nur gesendete Zeilen, deren `new_status` kein `ok` ist; ein Ausfall kurz nach der Entwarnung geht wieder raus. Test erst rot.
Beweis: main@6895f8eaf apps/monitoring/app/alerter.py:669-690 · Dedup-Key: bug:monitoring:alerter.py:recovery-restarts-cooldown
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alerter_cooldown.py tests/test_alerter.py
Doku: → T5

### T2 — R-1696: der Scheduler hält die Phase eines Checks  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/scheduler.py, apps/monitoring/tests/test_scheduler.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @ec8c7d31f 2026-11-27T21:09:10+01:00
Review: approve (.ah-out/review/kern-monitoring-56/T2.verdict.json)
Änderung: `add_check` lässt einen Job mit unverändertem Intervall stehen; `load_all_checks` setzt die Phase aus `MonitorState.last_check` + Intervall, Überfälliges läuft in der ersten Minute an zufälliger Stelle. Test erst rot.
Beweis: main@6895f8eaf apps/monitoring/app/scheduler.py:61-79,105-112,152 · Dedup-Key: bug:monitoring:scheduler.py:add-check-resets-interval-phase
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_scheduler.py tests/test_scheduler_after_commit.py
Doku: → T5

### T3 — R-1792, R-1827: Internal-Key auf jeder Route, Längengrenzen  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/schemas.py, apps/monitoring/tests/test_internal_key_routes.py, apps/monitoring/tests/test_schema_limits.py, apps/monitoring/tests/openapi.snapshot.json
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @12b26bd90 2026-11-27T21:15:02+01:00
Review: approve (.ah-out/review/kern-monitoring-56/T3.verdict.json)
Änderung: Ein Test ruft jede Route der App (außer `/health` und `/health/detail`) ohne Key und erwartet 401. `server_id`/`match_server_id` bekommen `max_length` 255, Texte in Regelwerten 1024, Regel-Listen `MAX_FIELDS`. Neue Tests mit SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_internal_key_routes.py tests/test_schema_limits.py tests/test_openapi_snapshot.py
Doku: keine (Admin-API hinter dem Internal-Key, Grenze nur für unrealistische Werte); changelog.d/kern-monitoring-56.md → T5

### T4 — R-1827, R-1828: record_rule_layers friert ein statt abzubrechen; sync_catalog-Ausnahme nur für probe  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/module_sync.py, apps/monitoring/tests/test_module_sync.py, apps/monitoring/tests/test_rule_layer_db.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @f141f7a23 2026-11-27T21:19:25+01:00
Review: approve (.ah-out/review/kern-monitoring-56/T4.verdict.json)
Änderung: Wirft `store_layer` bei einer Zeile `ValueError`, bleibt sie eingefroren (Warnung), der Durchgang läuft weiter. `sync_catalog` überspringt eine markierte Zeile ohne Schicht nur bei `check_type == "probe"`; zentrale Modul-Checks bekommen Hash und Update-Angebot. Tests erst rot.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py tests/test_rule_layer_db.py
Doku: → T5

### T5 — Doku und Changelog  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-56.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d24fd5ddc 2026-11-27T21:24:27+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Cooldown-Absatz (eine Entwarnung startet ihn nicht), Phase eines Checks nach Neustart und Ändern, Changelog-Fragment (umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende

### T6 — R-1792: Grenze auch für scope_value einer Ausnahme (Abschlussprüfung)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/schemas.py, apps/monitoring/tests/test_schema_limits.py, apps/monitoring/tests/openapi.snapshot.json, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/features/kern-monitoring-56.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @4fb7cf524 2026-11-27T21:33:35+01:00
Review: approve (.ah-out/review/kern-monitoring-56/T6.verdict.json)
Änderung: `ExceptionInput.scope_value` (Check-ID, Check-Typ oder Server-ID) höchstens 255 Zeichen, Test mit Rücklesen aus dem Schema, Snapshot nachgezogen. Dazu die Nits: die Doku nennt die Streuung jedes überfälligen Checks über die erste Minute, die Spec 1024 für Regeltexte.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_schema_limits.py tests/test_openapi_snapshot.py
Doku: diese Task

## Entscheidungen
- Kevin 2026-11-27: R-1690 Variante (a), R-1828 Ausnahme nur für probe.
- Grenze 255 für Server-IDs: Server-IDs sind heute UUIDs (36), 255 lässt Importe mit eigener ID zu.
- Texte in Regelwerten 1024 statt 255: ein Regelwert vergleicht auch mit Pfaden, und `catalog.model._ABS_PATH` lässt 1024 Zeichen zu (T3).
- Agent-Routen erwarten ohne Key ebenfalls 401 (`require_agent`); offen bleibt nur `/health/detail`, das weder Gateway noch Server weiterreichen (T3).
