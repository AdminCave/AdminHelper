<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-7 — Task-Ledger
Status: bereit · Branch: feature/klein-nachlese-7 · Review: am Ende
Spec: docs/features/klein-nachlese-7.md (Roadmap R-1403, R-1405)
Heavy: none — nur Monitoring-Service (Checker, Katalog), Doku
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1403: erst filtern, dann auf N begrenzen (Top-Prozesse, OOM-Liste)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/agent.py, apps/monitoring/app/checkers/system.py, apps/monitoring/tests/test_agent_resources_checker.py, apps/monitoring/tests/test_system_state_checker.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @9c63e49d1 2026-11-14T21:19:49+01:00
Review: am Ende (Branch-Review)
Beweis: reviewer klein-nachlese-3 T3 2026-11-12 · Dedup-Key: REF:monitoring:checkers/agent.py:_top_processes
Änderung: `_top_processes` und `_oom_processes` nehmen die ersten N *brauchbaren* Einträge (pid ≥ 1, Name) statt der ersten N Objekte; Tests: unbrauchbare Einträge vor den brauchbaren verdrängen keinen Platz (erst rot).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_resources_checker.py tests/test_system_state_checker.py
Doku: keine (Details-Ansicht, kein dokumentiertes Verhalten)

### T2 — R-1405 (1)(3): jicofo-Regel `sub_state exited`, onlyoffice-Docstring  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/jitsi_jicofo.py, apps/monitoring/app/catalog/modules/onlyoffice.py, apps/monitoring/tests/test_catalog_jitsi.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @5120effb1 2026-11-14T21:20:31+01:00
Review: am Ende (Branch-Review)
Beweis: arch-monitoring-apps-1 Task-Prüfer 2026-11-12 · Dedup-Key: ref:monitoring:catalog:nachlese-apps-1
Änderung: Check `service` von jitsi-jicofo bekommt die Regel `sub_state eq exited -> critical`, `version` 2 (Docstring nennt den Grund); der Docstring von `onlyoffice.py` nennt `onlyoffice/documentserver-ie` unter „Not covered“. Test: `active`/`exited` ist critical, `active`/`running` ok (erst rot). Gilt nur für jicofo, nicht für die Videobridge.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_jitsi.py tests/test_catalog_onlyoffice.py tests/test_catalog.py
Doku: → T3

### T3 — R-1405 (2)(4): Doku Rocket.Chat/jicofo (DE+EN), Ledger-Dateiname, Changelog  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, tasks/arch-monitoring-apps-1.md, changelog.d/klein-nachlese-7.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b624ac330 2026-11-14T21:25:06+01:00
Review: am Ende (Branch-Review)
Task-Review: am Ende
Änderung: Zeile jitsi-jicofo: die Unit ist `critical`, wenn sie `exited` ist (statt „bleibt active“); Zeile rocketchat: eine Antwort ohne die `checks`-Felder ist `unknown`; `modules/jitsi.py` in T7 von arch-monitoring-apps-1 wird `jitsi_videobridge.py, …/jitsi_jicofo.py`; Fragment `changelog.d/klein-nachlese-7.md`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/klein-nachlese-7.md
