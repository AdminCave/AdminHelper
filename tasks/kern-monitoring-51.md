# Monitoring-Nachlese: Dienstnamen unter Windows, agent_ping nach Stillstand, Cleanup, Lastschonung — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-51 · Review: pro Task
Spec: docs/features/kern-monitoring-51.md (Roadmap R-0436, R-1607, R-1622, R-1616)
Heavy: none — nur Bewertung und eine Admin-Route im Monitoring-Dienst, kein Stack-, Gateway-, PKI-, Agent- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-0436: service_process list vergleicht Windows-Dienstnamen ohne Groß-/Kleinschreibung  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_service_process_checker.py, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-51.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @6e4c4da17 2026-11-19T20:19:19+01:00
Review: approve (.ah-out/review/kern-monitoring-51/T1.verdict.json)
Beweis: Beobachtung monitoring-services T5 (2026-10-16), Code-Lesung `_evaluate_list` (Schlüssel `_unit_name(name)` wörtlich); Test zeigt `w32time` gegen Inventar `W32Time` = nodata
Dedup-Key: bug:monitoring:checkers/agent.py:service_name_case
Änderung: Trägt der Bericht `host.os == "windows"`, bildet `_evaluate_list` die Schlüssel aller Quellen (Watch-Liste, Inventar samt Alias-Ziel, prev_details) und der erwarteten Namen klein (`casefold`); die Ausgabe nennt den Namen wie eingetragen. Erst der rote Test.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_service_process_checker.py
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html (Modus list), changelog.d/kern-monitoring-51.md

### T2 — R-1607: agent_ping zählt die Stillstandszeit des Dienstes nicht mit  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_agent_ping_checker.py, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-51.md, apps/monitoring/app/main.py, apps/monitoring/tests/test_template_overrides.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @63e13fe38 2026-11-19T20:32:52+01:00
Review: approve (.ah-out/review/kern-monitoring-51/T2.verdict.json)
Beweis: arch-monitoring-neu-p0 T10 Experiment 2026-11-18 (20 min Stillstand, Push 2 s nach dem ersten Lauf → critical „unreachable for 25 min“)
Dedup-Key: bug:monitoring:agent.py:agent-ping-counts-monitoring-downtime
Änderung: `hydrate_agent_liveness` bekommt aus dem Lifespan (`main.py`) den letzten Check-Lauf vor dem Stopp (`max(MonitorState.last_check)`) und merkt sich mit dem Start den Stillstand; ein Zeitstempel ohne monotonen Partner verliert in `AgentPingChecker.run` den Teil des Stillstands nach dem Stempel. Roter Test mit dem Ablauf aus dem Beweis, dazu ein schon vor dem Stopp toter Agent bleibt critical.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_ping_checker.py tests/test_template_overrides.py
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html (agent_ping), changelog.d/kern-monitoring-51.md

### T3 — R-1622: Cleanup schickt die Entwarnungen nach der Antwort  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/server_cleanup.py, apps/monitoring/app/routers/admin.py, apps/monitoring/tests/test_bell_removed_checks.py, changelog.d/kern-monitoring-51.md
Beweis: reviewer-Nit kern-monitoring-49 2026-11-19 (`send_all_clears` synchron in `cleanup_server`)
Änderung: `cleanup_server` nimmt einen Absender für die Entwarnungen; die Route übergibt `background_tasks.add_task`, damit die Hub-Aufrufe nach der Antwort laufen. Test: die Route antwortet, bevor eine Entwarnung gesendet ist, und sendet sie danach.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_bell_removed_checks.py tests/test_openapi_snapshot.py
Doku: changelog.d/kern-monitoring-51.md

### T4 — R-1616: since in der Zukunft gilt als jetzt  [~] (verschoben in kern-monitoring-52: Kappung auf now wirkt nicht, since wird je Push neu gelesen (Test since-ahead hält schon); echter Fix braucht serverseitig gemerkten Beginn, Frage an Kevin)
Komponente: monitoring · Dateien: apps/monitoring/app/routers/agent.py, apps/monitoring/tests/test_agent_load_shed.py
Beweis: km41 Abschlussprüfung 2026-11-18, PR #577 (Nit `routers/agent.py` `now - shed_since`)
Dedup-Key: ref:monitoring:agent.py:since-future
Änderung: Der Push-Pfad kappt `shed_since` auf `now`; ein Test mit `since` eine Stunde in der Zukunft: nach 15 min Lastschonung gilt der Check als nicht gemessen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_load_shed.py
Doku: keine (Randfall einer fehlerhaften Agent-Uhr, Verhalten wie dokumentiert)

## Entscheidungen
- T2: Stillstand statt Kappung auf den Start (Prüfer-Fund T2: die Kappung machte einen schon vor dem Stopp toten Agent nach jedem Neustart stale_minutes lang ok); Stoppzeitpunkt = max(MonitorState.last_check), ohne neue Spalte.
