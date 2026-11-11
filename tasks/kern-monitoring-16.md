# Monitoring-Module: Nachlese zu Bindung, Grenzen, Erkennung und Zugangsdaten-Datei — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-16 · Review: pro Task
Spec: docs/features/kern-monitoring-16.md (Roadmap R-1254, R-1260, R-1262, R-1263, R-1295)
Heavy: linux-full — apps/agent (Zugangsdaten-Datei) und apps/monitoring (Grenzen, Erkennung); Windows über die PR-CI (go-windows)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1295, R-1263: Zugangsdaten-Datei lesen, ohne Rename und FIFO zu blockieren  [ ]
Komponente: agent · Dateien: apps/agent/internal/credentials/store_windows.go, apps/agent/internal/credentials/store_linux.go, apps/agent/internal/credentials/store_test.go
Änderung:
- Windows: `readPrivate` öffnet mit `FILE_SHARE_READ|FILE_SHARE_DELETE` (`store_windows.go:34`), damit ein
  gleichzeitiges `os.Rename` (`store.go:220`, `MoveFileExW`) nicht mit „Access is denied“ scheitert. Verhalten vorher in
  der Microsoft-Doku zu `CreateFileW`/`MoveFileExW` nachlesen.
- Linux: `readPrivate` öffnet nicht blockierend (`store_linux.go:23`, `O_NONBLOCK`), eine FIFO am Pfad wird als
  „keine reguläre Datei“ abgewiesen statt zu hängen.
- Test: FIFO am Pfad (Linux) abgewiesen mit Zeitgrenze; `TestSetKeepsTheOtherSetsMadeAtTheSameTime` bleibt und zählt
  als Beweis auf go-windows (PR-CI).
Beweis: arch-monitoring-ui PR #450 CI 2026-11-10 · ci.yml run 42869749453, job Go Agent (test, Windows), store_test.go:234
Dedup-Key: bug:agent:apps/agent/internal/credentials/store.go:Set_windows_rename
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/credentials/...
Doku: keine (internes Dateiverhalten)

### T2 — R-1263: Agent-Nits in probe (fields.go, sensor_sql.go)  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/fields.go, apps/agent/internal/probe/sensor_sql.go
Änderung:
- Docstring von `release` (`fields.go:24`) zu Punkt-Schlüsseln genau fassen (wie der Code sucht).
- Redundantes `strings.Contains(row, "\n")` (`sensor_sql.go:222`) entfernen, wenn die Zeile schon vorher geteilt
  ist; sonst belegte Begründung unter `## Entscheidungen`.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/...
Doku: keine (Kommentar und toter Zweig)

### T3 — R-1263: Monitoring-Nits (apply_discovery, credentials-Spalte, probe.py)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/discovery.py, apps/monitoring/app/models.py, apps/monitoring/app/checkers/probe.py, apps/monitoring/tests/test_discovery_match.py
Änderung:
- `apply_discovery` (`discovery.py:480`) schreibt in einem `begin_nested`-Savepoint statt `commit`/`rollback` auf der
  übergebenen Session (`discovery.py:514/516`); der Aufrufer committet.
- `MonitorDiscovery.credentials` (`models.py:545`) wird nur über einen Helfer geschrieben, der die Form
  (`<module>/<instance>/<slot>` → bool) prüft.
- Docstring-Zeile `checkers/probe.py:15` umbrechen.
- Test: ein Fehler in `apply_discovery` lässt frühere Änderungen der Session stehen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_discovery_match.py
Doku: → T9

### T4 — R-1254: Bindung eines compose_project-Moduls im Fund  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/module_sync.py, apps/monitoring/tests/test_module_sync.py
Änderung:
- Nach der privaten Roadmap (`module_sync._target_name`, `module_sync.py:78`); die Fund-Zusammenfassung nennt den
  gebundenen Container.
- Test je Fall.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py
Doku: → T9

### T5 — R-1260: Nachlese Vorlagen-Sync  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/template_sync.py, apps/monitoring/tests/test_template_sync.py
Änderung:
- Nach der privaten Roadmap (`template_sync.py`, Aufrufe von `substitute_variables`).
- Test je Fall.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_template_sync.py
Doku: → T9

### T6 — R-1260: Nachlese Report-Endpunkt  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/agent.py, apps/monitoring/tests/test_agent_report.py, apps/monitoring/tests/test_agent_report_v4.py
Änderung:
- Nach der privaten Roadmap (`routers/agent.py`, `agent_report`).
- Test je Fall.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_report.py tests/test_agent_report_v4.py
Doku: → T9

### T7 — R-1262: Grenzen für Probe-Ziel und Log-Fühler  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/check_configs.py, apps/monitoring/app/catalog/sensors.py, apps/monitoring/tests/test_check_configs.py, apps/monitoring/tests/test_catalog.py
Änderung:
- `ProbeTarget.name` (`check_configs.py:182`) ist für `container`, `unit` und `process` Pflicht (nicht leer).
- `LogParams` (`catalog/sensors.py:145`) lehnt Glob-Units und `match`-Werte ab, die der Agent als `invalid` ablehnt
  (Regel im Agent-Code nachlesen, gleich fassen).
- Test: vorher rot (angenommen), nachher 422; gültige Werte bleiben.
Beweis: Prüfungen arch-monitoring-module 2026-11-09/10 · feature/arch-monitoring-module@4bcb9f4b0 check_configs.py ProbeTarget; catalog/sensors.py LogParams
Dedup-Key: bug:monitoring:discovery.py:nachlese-arch-monitoring-module
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_configs.py tests/test_catalog.py
Doku: → T9

### T8 — R-1262: Erkennung: Ersatz-Instanz und Scan-Rhythmus  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/discovery.py, apps/monitoring/tests/test_discovery_match.py
Änderung:
- Die Ersatz-Instanz (`matched_by`, `discovery.py:277`) hängt nicht am Unit-Zustand; ein gestoppter Dienst ergibt
  kein `changed`.
- Ein Teil-Scan setzt `next_scan_at` (`discovery.py:508`) nicht wie ein voller; ein voller Scan kommt auch bei Hosts,
  deren Teil-Scan stets abläuft, und `gone` wird erreichbar.
- Test je Fall: vorher rot, nachher grün.
Beweis: Prüfungen arch-monitoring-module 2026-11-09/10 · feature/arch-monitoring-module@4bcb9f4b0 discovery.py:277,508
Dedup-Key: bug:monitoring:discovery.py:nachlese-arch-monitoring-module
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_discovery_match.py
Doku: → T9
Abhängt von: T3

### T9 — Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-16.md
Änderung:
- Admin-Doku: Bindung im Fund, Pflicht-Zielname, Log-Fühler-Grenzen, Scan-Rhythmus.
- Entwickler-Doku: Downgrade von `b8d0f2a4c6e8` verwirft `monitor_checks.silent`.
- `changelog.d/kern-monitoring-16.md` neutral.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- Plan: R-1264 fährt nicht mit (Migration für Grabsteine, sichtbares Verhalten beim Katalog-Rollout: Frage an Kevin),
  eigener Zug.
