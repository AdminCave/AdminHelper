<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-16 — Task-Ledger
Status: erledigt · Branch: feature/klein-nachlese-16 · Review: pro Task
Spec: docs/features/klein-nachlese-16.md (Roadmap R-1657, R-1661)
Heavy: none — Kommentar, Monitoring-Unit-Tests, Spec-Text
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1657: Kommentar an ensureAllSubscription  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/lib/live.js
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped @380eaee1e 2026-11-20T01:19:48+01:00
Review: approve (.ah-out/review/klein-nachlese-16/T1.verdict.json)
Beweis: reviewer kern-gateway-1 branch, 2026-11-19
Semantik: keine Stelle in docs/ — der Kommentar selbst ist der Fund
Änderung: Der Kommentar sagt, dass `ensureAllSubscription` über das Gateway (`-k`) läuft, und nennt `injectEvent` nicht mehr als Vorbild, denn der geht per `compose exec` in den Server-Container.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Kommentar)

### T2 — R-1661: _resolve_alias unter Windows, Tests für reason und stopped_at  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_service_process_checker.py, apps/monitoring/tests/test_template_overrides.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @c2c41d97f 2026-11-20T01:22:13+01:00
Review: approve (.ah-out/review/klein-nachlese-16/T2.verdict.json)
Beweis: reviewer kern-monitoring-51 branch, 2026-11-19
Semantik: keine Stelle in docs/ — Windows vergleicht Dienstnamen ohne Groß-/Kleinschreibung (Spec kern-monitoring-51)
Änderung: `_resolve_alias` nimmt die Schlüsselfunktion von `_evaluate_list` und findet das Alias-Ziel auch unter Windows, wenn `alias_of` die Schreibweise des Inventars nicht trifft (Test erst rot). Neuer Test: ein Dienst, der über einen Alias als down gilt, trägt den `reason` seines Ziels in `watched` und Meldung. `test_template_overrides` hält den Aufruf der Hydration fest und prüft, dass `stopped_at` der späteste `MonitorState.last_check` ist.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_service_process_checker.py tests/test_template_overrides.py tests/test_agent_ping_checker.py
Doku: keine (interne Korrektur, Windows kennt keine Alias-Einträge im Bericht)

### T3 — R-1661: Spec kern-monitoring-51 auf den Stillstand-Abzug  [x]
Komponente: monitoring · Dateien: docs/features/kern-monitoring-51.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @ddd9a7cef 2026-11-20T01:22:39+01:00
Review: am Ende (nur Doku, Branch-Review)
Beweis: reviewer kern-monitoring-51 branch, 2026-11-19
Semantik: keine Stelle in docs/ — die Spec selbst ist der Fund
Änderung: Die Abschnitte Problem, Ziel, Trade-offs und Risiken beschreiben für `agent_ping` den Abzug der Stillstandszeit (Zeit zwischen letztem Check und Start, ab dem Zeitstempel) statt der Kappung auf den Dienststart.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_ping_checker.py
Doku: docs/features/kern-monitoring-51.md
Task-Review: am Ende
