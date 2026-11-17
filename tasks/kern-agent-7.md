# kern-agent-7 — FreeBSD rc.d-Dienste als Units — Task-Ledger
Status: erledigt · Branch: feature/kern-agent-7 · Review: am Ende
Spec: docs/features/kern-agent-7.md (Roadmap R-1448)
Heavy: linux-full — apps/agent (Discovery); der FreeBSD-Zweig selbst läuft nur mit Fake-service(8) und GOOS=freebsd vet
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Agent: Discovery meldet unter FreeBSD die eingeschalteten rc.d-Skripte als Units  [x]
Komponente: agent · Dateien: apps/agent/internal/discovery/discovery.go, apps/agent/internal/discovery/discovery_test.go, apps/agent/internal/probe/unit_rcd.go, apps/agent/internal/probe/unit_rcd_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @c067382d6 2026-11-17T07:26:31+01:00
Review: am Ende (Branch-Review)
Änderung: R-1448. probe bekommt `RCUnits` (`service -e` plus onestatus, exportiert). `collectUnits` liest unter FreeBSD die eingeschalteten Skripte und fragt jedes mit onestatus: active/running oder inactive/dead, bloßer Name. Ein Skript ohne lesbaren Status fehlt. Ein Aufruf ohne Antwort beendet die Liste als partial. Tests mit Fake-service(8).
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T2

### T2 — Monitoring: php_fpm bindet an das rc.d-Skript, Doku  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/discovery.py, apps/monitoring/app/catalog/modules/php_fpm.py, apps/monitoring/app/catalog/modules/haproxy.py, apps/monitoring/tests/test_discovery_match.py, apps/monitoring/tests/test_catalog_apps.py, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-agent-7.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @5af21de79 2026-11-17T07:34:53+01:00
Review: am Ende (Branch-Review)
Änderung: R-1448. `php_fpm` kommt in `_UNITS` des Moduls php_fpm (Version +1), der Kommentar von `_listed_unit_wanted` nennt FreeBSD. Test: Ein FreeBSD-Inventar mit den Units `haproxy` und `php_fpm` (active) bindet beide Module, die Instanz trägt den bloßen Namen. Doku-Absatz zu den Units des Inventars DE+EN, Changelog.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_discovery_match.py tests/test_catalog_apps.py tests/test_catalog_web.py tests/test_catalog_sensors.py tests/test_catalog_nextcloud.py tests/test_catalog.py
Doku: docs/admin/monitoring.html docs/en/admin/monitoring.html changelog.d/kern-agent-7.md
Abhängt von: T1

### T3 — Doku: Modultabelle haproxy und php_fpm nennen die rc.d-Skripte  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, tasks/kern-agent-7.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @4768ee47f 2026-11-17T07:45:16+01:00
Review: am Ende (Branch-Review)
Änderung: R-1448, Fund der Abschlussprüfung. Zeile `haproxy`: der Satz „bindet unter FreeBSD noch nicht“ fällt, statt dessen das rc.d-Skript `haproxy`. Zeile `php_fpm`: das rc.d-Skript `php_fpm` und das Pool-Verzeichnis `/usr/local/etc/php-fpm.d`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html
Task-Review: am Ende

## Entscheidungen
- T1: Der Parser von `service -e` bleibt in monitor (`parseRCEnabled`), probe bekommt eine eigene Liste (`RCUnits`). Ein Umzug hätte die Klasse `rcscript` der monitor-Allowlist (`argClasses`) mitziehen müssen, und monitors Ausgabe (enabled_inactive, stop_cmd-Regel) braucht die Dateipfade, die Discovery nicht. Die Doppelung ist ~15 Zeilen; die Namensregel ist in beiden dieselbe (`rcNamePattern` ↔ `reRCScriptName`). Statusaufruf: Exit > 0 ist eine Antwort, Timeout, Signal und Startfehler beenden die Liste (wie `answered` in monitor).
- T1 (Reparatur vor dem Push): Die Dateien-Zeile war mit Leerzeichen statt Kommas getrennt; task-close stagte nur den ersten Pfad. Der Commit wurde um probe/unit_rcd.go und die Tests ergänzt (amend, Verify erneut: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped).
- T1: Gestoppte Skripte melden `inactive`/`stopped` (nicht `dead` wie in der Spec), wie der Unit-Sensor unter Windows; der Server wertet `sub` nicht aus.
