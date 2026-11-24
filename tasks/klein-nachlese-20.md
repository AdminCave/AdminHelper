<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-20 — Nachlese kern-agent-20 bis kern-testdb-1 — Task-Ledger
Status: aktiv · Branch: feature/klein-nachlese-20 · Review: pro Task
Spec: docs/features/klein-nachlese-20.md (Roadmap R-1730, R-1731, R-1733, R-1735, R-1736, R-1746, R-1749)
Heavy: none — Test-, Kommentar- und Doku-Nits; die Port-Prüfung greift beim Dienststart und ist per Unit-Test belegt
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@fae494411`.

### T1 — Agent: Report-Structs, Kommentare (R-1730)  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/scquery.go, apps/agent/internal/monitor/systemstate.go, apps/agent/internal/monitor/systemstate_test.go, apps/agent/internal/monitor/servicelogs_windows_test.go, apps/agent/internal/monitor/plugins.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @880a49007 2026-11-24T15:03:21+01:00
Review: approve (.ah-out/review/klein-nachlese-20/T1.verdict.json)
Änderung: `parseScQuery` bei 0 Diensten: Wire prüfen (`all_services` fehlt statt `null`) und die Absicht kommentieren, Test festhalten. `empty()` per Reflect-Test je Feld absichern (jedes Feld einzeln gesetzt ⇒ nicht leer). Doppelten Doc-Kommentar vor `failedLogs` entfernen; `parseZpoolList`-Kommentar auf `[]ZPool`.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (Kommentare und Tests)

### T2 — Server-Tests und Docstring (R-1731, R-1733, R-1735)  [x]
Komponente: server · Dateien: apps/server/tests/test_bootstrap.py, apps/server/tests/test_scheduler_schema_gate.py, apps/server/tests/test_cli.py, apps/server/tests/test_monitoring_client.py, apps/server/app/core/monitoring_client.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @4f703fdb8 2026-11-24T15:05:59+01:00
Review: approve (.ah-out/review/klein-nachlese-20/T2.verdict.json)
Änderung: toten `fire_event`-Patch entfernen; `threading.Event`-Patch auf den Scheduler-Namensraum begrenzen; Test für `UsernameTaken` in `create_admin` (Vorabprüfung umgehen, Exit 1, kein Event); Docstring nennt die Proxy-Ausnahme; doppelte Notify-Barriere raus; Tag-Sync-Test prüft die URL ausdrücklich.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_bootstrap.py tests/test_scheduler_schema_gate.py tests/test_cli.py tests/test_monitoring_client.py
Doku: keine (Tests, Docstring)

### T3 — env_int mit Obergrenze für Ports (R-1746)  [ ]
Komponente: server · Dateien: apps/pycommon/ah_common/env.py, apps/server/app/core/config.py, apps/monitoring/app/core/config.py, apps/server/tests/test_config_env.py
Änderung: Erst Test rot (Port 70000 ⇒ `ConfigError`). Dann `maximum` in `parse_int`/`env_int` (Meldung `a whole number between a and b`), `maximum=65535` für `FRP_BIND_PORT`, `VISITOR_PORT_START/END`, `ENROLL_PORT`, `REPO_PORT`, `SMTP_PORT` (Server und Monitoring). Konfig-Doku per `grep` auf genannte Wertebereiche prüfen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_config_env.py tests/test_env_parity.py
Doku: → T5

### T4 — Monitoring-Tests: SQLite-Docstrings (R-1749)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_status_log.py, test_status_info.py, test_object_state.py, test_alerter.py, test_nul.py, test_alert_bundle.py, test_agent_report.py
Änderung: Docstrings und Kommentare nennen Postgres statt SQLite (Zeilen aus der Roadmap-Zeile, frisch greppen); `test_agent_report.py` Trigger-Funktion: räumt der Test sie auf, sonst Aufräumen ergänzen oder Kommentar korrigieren. Keine Logikänderung der Tests.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_status_log.py tests/test_status_info.py tests/test_object_state.py tests/test_alerter.py tests/test_nul.py tests/test_alert_bundle.py tests/test_agent_report.py
Doku: keine (Kommentare)

### T5 — Doku: Hooks-Shutdown, Changelog-Form  [ ]
Komponente: scripts · Dateien: docs/developer/hooks.html, docs/en/developer/hooks.html, changelog.d/kern-server-13.md, changelog.d/klein-nachlese-20.md
Änderung: Shutdown-Absatz DE+EN: 10 s Wartezeit auf nicht beendete Events, nicht gestartete verfallen, ein gestarteter Hook läuft bis zu seinem Timeout weiter. Fragment `kern-server-13.md` in die Form `- **Server: Titel:** Text`. Neues Fragment für T3 (umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/hooks.html, docs/en/developer/hooks.html, changelog.d
Task-Review: am Ende
