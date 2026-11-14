# Tägliche Konfigurationstests (DNS, DHCP, VRRP, Proxy, fail2ban) — Task-Ledger
Status: geplant · Branch: feature/kern-monitoring-31 · Review: am Ende
Spec: docs/features/kern-monitoring-31.md (Roadmap R-1432)
Heavy: linux-full — neue Agent-Ansicht und Freigabeliste (apps/agent), Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Agent: Ansicht service_config und Freigabeliste  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/app_conftest.go, apps/agent/internal/probe/app_conftest_test.go, apps/agent/internal/probe/sensor_app.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: R-1432. Neue Ansicht `service_config` (unitKinds) nach dem Vorbild `webConfig`: je Unit ein Test (named-checkconf, unbound-checkconf, keepalived --config-test, squid -k parse, fail2ban-client --test, dnsmasq --test), nur `config_ok`, Exit≠0 ist ein Wert, fehlendes Binary und fremde Unit `ErrUnsupported`; Freigabeliste mit genau diesen Argumenten, Positiv- und Fallentests. Vor dem Bau die Schreibfreiheit jedes Aufrufs an der offiziellen Doku belegen (Zitat in `## Entscheidungen`); neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T3

### T2 — Katalog: Check config in sechs Modulen  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/bind.py, apps/monitoring/app/catalog/modules/unbound.py, apps/monitoring/app/catalog/modules/dnsmasq.py, apps/monitoring/app/catalog/modules/keepalived.py, apps/monitoring/app/catalog/modules/squid.py, apps/monitoring/app/catalog/modules/fail2ban.py, apps/monitoring/tests/test_catalog_dns.py, apps/monitoring/tests/test_catalog_netsec.py, apps/monitoring/tests/test_catalog_proxies.py
Änderung: R-1432. `service_config` in `APP_VIEW_FIELDS` ({config_ok}), `APP_VIEW_TARGETS` (_UNIT) und dem Literal; je Modul ein Check `config` (sensor app, view service_config, interval 86400, timeout_s 20, Regel config_ok eq False → warning) und `version` 2; Tests je Modul. Zehn Dateien: sechs Module mit je einer gleichförmigen Zeile, eine Task, weil ein Commit sie gemeinsam testet.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_dns.py tests/test_catalog_netsec.py tests/test_catalog_proxies.py tests/test_catalog.py tests/test_catalog_sensors.py
Doku: → T3
Abhängt von: T1

### T3 — Doku: Konfigurationstests DE+EN, CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-monitoring-31.md
Änderung: R-1432. Die sechs Modulzeilen nennen den täglichen Test und `warning`; bei Squid entfällt „Nicht abgedeckt: der Konfigurationstest“; die Ansicht `service_config` in der Liste des Fühlers `app`; CHANGELOG-Fragment unter `### Added`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende
Abhängt von: T2

## Entscheidungen
- 2026-11-14 Zugschnitt: R-1378 und R-1422 brauchen die vHost-Liste, die R-1231 nicht gebaut hat (R-1435, kern-monitoring-28) → dorthin; R-1423, R-1424, R-1434 tragen Fragen aus Kevins Bereich (Zugangsdaten- und Datenumfang, hostübergreifende Kennung) → kern-monitoring-35.
- `squid -k parse` statt der in der Zeile genannten `-k check` (siehe Spec).
