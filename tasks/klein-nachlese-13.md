# klein-nachlese-13 — Nachlese kern-monitoring-42/-43 — Task-Ledger
Status: aktiv · Branch: feature/klein-nachlese-13 · Review: am Ende
Spec: docs/features/klein-nachlese-13.md (Roadmap R-1530, R-1547)
Heavy: none — nur Tests und ein Kommentar
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Agent-Tests: Fristkommentar, Budget-Test trifft das Container-Budget  [x]
Komponente: agent · Dateien: apps/agent/internal/execx/execx_unix_test.go, apps/agent/internal/probe/web_vhosts_container_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @c75ab4613 2026-11-18T13:11:47+01:00
Review: am Ende (Branch-Review)
Änderung: R-1530. Der 200-ms-Fall in execx_unix_test.go bekommt den Kommentar, dass er die Frist selbst prüft (testing.md). Der Budget-Test baut acht Dateien unter 1 MiB (Summe ueber `maxContainerConfBytes`), damit er das Container-Budget trifft statt `maxApacheFileBytes`.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (Tests)

### T2 — Monitoring-Test: web_domain v2 ueber adopt() mit dem echten Modul  [ ]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_module_sync.py
Änderung: R-1547. Neuer Test: ein vhost-Fund fuer `web_domain` (Katalog `load_catalog()`, Port 8443) wird mit `adopt()` uebernommen; es entstehen die vier Checks, `dns` und `outside` als `central` mit ihrer Konfig (host, params, Port nur bei `outside`), die Agent-Checks als `probe`; der Plan des Agenten traegt nur dessen Probes.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py tests/test_catalog_web.py
Doku: keine (Test)
