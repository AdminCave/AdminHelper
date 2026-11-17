# kern-agent-7 — FreeBSD rc.d-Dienste als Units — Task-Ledger
Status: geplant · Branch: feature/kern-agent-7 · Review: am Ende
Spec: docs/features/kern-agent-7.md (Roadmap R-1448)
Heavy: linux-full — apps/agent (Discovery); der FreeBSD-Zweig selbst läuft nur mit Fake-service(8) und GOOS=freebsd vet
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Agent: Discovery meldet unter FreeBSD die eingeschalteten rc.d-Skripte als Units  [ ]
Komponente: agent · Dateien: apps/agent/internal/discovery/discovery.go apps/agent/internal/discovery/discovery_other.go apps/agent/internal/discovery/discovery_test.go apps/agent/internal/probe/unit_rcd.go apps/agent/internal/probe/unit_rcd_test.go apps/agent/internal/monitor/rcservice.go apps/agent/internal/monitor/rcservice_test.go
Änderung: R-1448. Der Parser von `service -e` zieht von monitor nach probe (exportiert), und monitor ruft ihn dort auf. `collectUnits` liest unter FreeBSD die eingeschalteten Skripte und fragt jedes mit onestatus: active/running oder inactive/dead, bloßer Name. Ein Skript ohne lesbaren Status fehlt. Ein Aufruf ohne Antwort beendet die Liste als partial. Tests mit Fake-service(8).
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T2

### T2 — Monitoring: php_fpm bindet an das rc.d-Skript, Doku  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/discovery.py apps/monitoring/app/catalog/modules/php_fpm.py apps/monitoring/tests/test_discovery_match.py docs/admin/monitoring.html docs/en/admin/monitoring.html changelog.d/kern-agent-7.md
Änderung: R-1448. `php_fpm` kommt in `_UNITS` des Moduls php_fpm (Version +1), der Kommentar von `_listed_unit_wanted` nennt FreeBSD. Test: Ein FreeBSD-Inventar mit den Units `haproxy` und `php_fpm` (active) bindet beide Module, die Instanz trägt den bloßen Namen. Doku-Absatz zu den Units des Inventars DE+EN, Changelog.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_discovery_match.py
Doku: docs/admin/monitoring.html docs/en/admin/monitoring.html changelog.d/kern-agent-7.md
Abhängt von: T1

## Entscheidungen
