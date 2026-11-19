<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-49 — Glocke: Entwarnung gelöschter Checks, Schweregrad im Nachholjob — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-49 · Review: am Ende
Spec: docs/features/kern-monitoring-49.md (Roadmap R-1601, R-1619)
Heavy: none — nur apps/monitoring-Logik, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Tasks

### T1 — R-1619: Nachholjob wertet nur die Richtung, nicht den Schweregrad  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/bell_catch_up.py, apps/monitoring/tests/test_bell_catch_up.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @69362e19f 2026-11-19T04:47:57+01:00
Review: am Ende (Branch-Review)
Beweis: branch-review kern-monitoring-47 2026-11-18, feature/kern-monitoring-47@049adff44 bell_catch_up.py:61 · Dedup-Key: bug:monitoring:bell_catch_up.py:lag_target-severity
Änderung: `lag_target` eines eingeschalteten Checks: Rückstand nur, wenn `hub_status` Problem/ok anders zeigt als
`notified_status`, oder `hub_status` critical und `notified_status` warning ist (Kevin 2026-11-19, A). Erst rote
Tests: Schweregrad angehoben (critical gemeldet, Glocke warning) und gesenkt (Glocke critical, Schweregrad warning)
senden nichts; eine Herabstufung critical→warning wird weiter nachgeholt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_bell_catch_up.py
Doku: → T3

### T2 — R-1601: Entwarnung für Checks, die Template, Zuweisung, Sync oder Server-Löschen entfernt  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/bell_catch_up.py, apps/monitoring/app/routers/templates.py, apps/monitoring/app/template_sync.py, apps/monitoring/app/server_cleanup.py, apps/monitoring/tests/test_bell_removed_checks.py
Beweis: kern-monitoring-45 T9 2026-11-18, Code-Lesung routers/templates.py delete_template, module_sync.py gone · Dedup-Key: bug:monitoring:templates.py:delete-leaves-incident
Änderung: Ein Helfer nimmt vor dem Löschen je Check mit Problem in der Glocke, was die Entwarnung braucht (wie
`delete_check`), und sendet sie nach dem Commit; `delete_template`, `remove_template`, der Wegfall im
Template-Sync und `cleanup_server` nutzen ihn. Neue Testdatei (SPDX): erst rot je Weg, dazu „gone“ → der Nachholjob
sendet die Entwarnung.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_bell_removed_checks.py tests/test_bell_catch_up.py tests/test_template_sync.py tests/test_templates_router.py
Doku: → T3

### T3 — Doku und Changelog  [ ]
Komponente: monitoring · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-49.md
Änderung: Admin: Löschen über Template, Zuweisung, Sync und Server schließt den Vorfall; Schweregrad-Wechsel bei
offenem Alarm ändert die Glocke nicht. Entwickler: Nachhol-Regel (Richtung) und die Lösch-Wege.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_bell_catch_up.py
Doku: diese Task
Task-Review: am Ende
Abhängt von: T1, T2

## Entscheidungen

- 2026-11-19 Kevin: R-1619 Variante A (nur Richtung, keine Spalte); R-1601 alle Lösch-Wege mitnehmen.
