# Monitoring-Nachlese: Objektzeilen unter Sperre, stabile Schlüssel, Verlauf, Hub im Hintergrund — Task-Ledger
Status: bereit · Branch: feature/kern-monitoring-53 · Review: pro Task
Spec: docs/features/kern-monitoring-53.md (Roadmap R-1651, R-1653, R-1650, R-1642, R-1660)
Heavy: none — nur Bewertung, Sperren und Routen im Monitoring-Dienst, kein Stack-, Gateway-, PKI-, Agent- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1651: Erstergebnis eines Checks unter Sperre schreiben  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/check_engine.py, apps/monitoring/app/routers/agent.py, apps/monitoring/tests/test_check_engine_concurrency.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @ab002f04d 2026-11-20T08:44:32+01:00
Review: approve (.ah-out/review/kern-monitoring-53/T1.verdict.json)
Änderung: Ohne `MonitorState` sperren Pull (`check_engine`) und Push (`routers/agent.py`) die `MonitorCheck`-Zeile `FOR UPDATE` und lesen den Zustand danach neu. Der Postgres-Test lässt zwei Erstergebnisse gleichzeitig laufen: Erst schlägt er fehl, mit der Sperre ist er grün. Lokal läuft er zusätzlich mit Postgres, der Beleg kommt in den Commit-Body.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_engine_concurrency.py tests/test_object_state.py tests/test_agent_report.py
Doku: keine (internes Sperrverhalten ohne dokumentierten Einfluss)

### T2 — R-1653: Cleanup verschwundener Objekte unter der Sperre des Checks  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/scheduler.py, apps/monitoring/tests/test_check_engine_concurrency.py, apps/monitoring/tests/test_object_state.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @8c0f3fadd 2026-11-20T08:49:25+01:00
Review: approve (.ah-out/review/kern-monitoring-53/T2.verdict.json)
Änderung: `_run_history_cleanup` ermittelt die Checks mit verschwundenen Objekten älter als 30 Tage. Es sperrt je Check dessen `MonitorState` `FOR UPDATE`, in Check-ID-Reihenfolge, und löscht dann. Ein Postgres-Test zeigt, dass das Cleanup wartet, bis ein laufendes `apply_objects` fertig ist.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_engine_concurrency.py tests/test_object_state.py
Doku: keine (internes Sperrverhalten)
Abhängt von: T1

### T3 — R-1650: Verlauf faltet nur Alert-Log-Zeilen, not_collected als ok an VictoriaMetrics  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/history.py, apps/monitoring/app/core/victoria.py, apps/monitoring/tests/test_status_history.py, apps/monitoring/tests/test_victoria.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @dea3eebe1 2026-11-20T08:52:29+01:00
Review: approve (.ah-out/review/kern-monitoring-53/T3.verdict.json)
Änderung: Die 60-s-Faltung in `server_events` greift nur noch für `origin == 'alert_log'`. `build_check_result_lines` schreibt `not_collected` als 0. Ein Test je Punkt schlägt zuerst fehl.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_status_history.py tests/test_victoria.py
Doku: → T6

### T4 — R-1642: Container und Gast-Backups stabil schlüsseln  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/plugins.py, apps/monitoring/tests/test_plugin_checkers.py, apps/monitoring/tests/test_objects_api.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @65369be00 2026-11-20T08:55:08+01:00
Review: approve (.ah-out/review/kern-monitoring-53/T4.verdict.json)
Änderung: Container mit Compose-Projekt, Dienst und Nummer bekommen die id `<projekt>/<dienst>/<nummer>`, Gast-Backups mit `cluster_name` die id `<cluster>/<vmid>`, beide `stable: true`. Ohne diese Felder gilt der heutige Rückfall (Name bzw. VMID, `stable: false`). Tests decken beide Wege ab.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_plugin_checkers.py tests/test_objects_api.py
Doku: → T6

### T5 — R-1660: Hub-Entwarnung bei toggle/delete im Hintergrund  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_alerter_hub.py, apps/monitoring/tests/test_bell_removed_checks.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @a465abd11 2026-11-20T08:57:46+01:00
Review: approve (.ah-out/review/kern-monitoring-53/T5.verdict.json)
Änderung: `toggle_check` und `delete_check` geben die Entwarnung an `BackgroundTasks` ab. Bei einem Fehlschlag gibt der Hintergrund-Job den Slot über eine eigene Sitzung frei (`release_hub_slot`). Antwort und Schema bleiben gleich. Ein Test zeigt, dass die Antwort nicht auf einen hängenden Hub wartet, ein weiterer, dass ein Fehlschlag den Slot freigibt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alerter_hub.py tests/test_bell_removed_checks.py tests/test_openapi_snapshot.py
Doku: → T6

### T6 — Doku und Changelog  [x]
Komponente: monitoring · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/adr/0004-monitoring-neuordnung.md, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-53.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @41fcbafb7 2026-11-20T08:59:24+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Die Schlüsseltabelle bekommt die Einträge container und guest-backup, mit Rückfall. Das ADR vermerkt den Host im Gast-Backup-Schlüssel. Die Entwickler-Doku erhält einen Satz zur Faltung im Verlauf, die Admin-Doku einen zur Neuanlage. Dazu das Changelog-Fragment.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_objects_api.py
Doku: docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-53.md
Task-Review: am Ende
Abhängt von: T3, T4, T5

## Entscheidungen
