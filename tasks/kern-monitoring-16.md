# Monitoring-Module: Nachlese zu Bindung, Grenzen, Erkennung und Zugangsdaten-Datei — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-16 · Review: pro Task
Spec: docs/features/kern-monitoring-16.md (Roadmap R-1254, R-1260, R-1262, R-1263, R-1295)
Heavy: linux-full — apps/agent (Zugangsdaten-Datei) und apps/monitoring (Grenzen, Erkennung); Windows über die PR-CI (go-windows)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1295, R-1263: Zugangsdaten-Datei lesen, ohne Rename und FIFO zu blockieren  [x]
Komponente: agent · Dateien: apps/agent/internal/credentials/store_windows.go, apps/agent/internal/credentials/store_linux.go, apps/agent/internal/credentials/store_test.go, apps/agent/internal/credentials/store.go, apps/agent/internal/credentials/store_linux_test.go, apps/agent/internal/credentials/store_windows_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @44d2400e8 2026-11-11T07:08:54+01:00
Review: approve (.ah-out/review/kern-monitoring-16/T1.verdict.json)
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

### T2 — R-1263: Agent-Nits in probe (fields.go, sensor_sql.go)  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/fields.go, apps/agent/internal/probe/sensor_sql.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @c6e858954 2026-11-11T07:11:53+01:00
Review: approve (.ah-out/review/kern-monitoring-16/T2.verdict.json)
Änderung:
- Docstring von `release` (`fields.go:24`) zu Punkt-Schlüsseln genau fassen (wie der Code sucht).
- Redundantes `strings.Contains(row, "\n")` (`sensor_sql.go:222`) entfernen, wenn die Zeile schon vorher geteilt
  ist; sonst belegte Begründung unter `## Entscheidungen`.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/...
Doku: keine (Kommentar und toter Zweig)

### T3 — R-1263: Monitoring-Nits (apply_discovery, credentials-Spalte, probe.py)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/discovery.py, apps/monitoring/app/models.py, apps/monitoring/app/checkers/probe.py, apps/monitoring/tests/test_discovery_match.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @ca9461773 2026-11-11T07:15:17+01:00
Review: approve (.ah-out/review/kern-monitoring-16/T3.verdict.json)
Änderung:
- `apply_discovery` (`discovery.py:480`) schreibt in einem `begin_nested`-Savepoint statt `commit`/`rollback` auf der
  übergebenen Session (`discovery.py:514/516`); der Aufrufer committet.
- `MonitorDiscovery.credentials` (`models.py:545`) wird nur über einen Helfer geschrieben, der die Form
  (`<module>/<instance>/<slot>` → bool) prüft.
- Docstring-Zeile `checkers/probe.py:15` umbrechen.
- Test: ein Fehler in `apply_discovery` lässt frühere Änderungen der Session stehen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_discovery_match.py
Doku: → T9

### T4 — R-1254: Bindung eines compose_project-Moduls im Fund  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/module_sync.py, apps/monitoring/tests/test_module_sync.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @b3d35135a 2026-11-11T07:18:48+01:00
Review: approve (.ah-out/review/kern-monitoring-16/T4.verdict.json)
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
- T1: Neben `FILE_SHARE_DELETE` beim Lesen bekommt der Rename unter Windows einen Wiederholversuch (bis 2 s, nur bei
  `ERROR_ACCESS_DENIED`/`ERROR_SHARING_VIOLATION`, wie Go `cmd/internal/robustio`). Grund: im Test laufen alle Leser
  unter dem Sperr-Lock (`update` → `enroll.LockFile`), der eigene Leser kann den Rename dort also nicht stören; den
  Flake erklärt ein fremder Leser ohne Delete-Freigabe (Virenscanner, Indexer), den nur ein Wiederholversuch abfängt.
  `FILE_SHARE_DELETE` bleibt für den Agent-Dienst, der `Load` ohne Lock liest, während `monitor credential set` schreibt.
- T2: `strings.Contains(row, "\n")` in `askPostgres` bleibt. `TrimRight` entfernt nur Zeilenenden am Schluss, eine
  zweite Antwortzeile steht danach noch im Text und liefe in die letzte Zelle; die Prüfungen je Abfrage fingen das nur
  zufällig ab (Zellenzahl, Zahlformat). Ein Kommentar sagt jetzt das Warum.
- T3: `apply_discovery` und `apply_credentials` (gleiches Muster, gleiche Datei) schreiben in einem Savepoint und
  committen erst danach selbst; der Report-Endpunkt verlässt sich auf diesen Commit (die gemeinsame Auswertung
  committet nur bei Agent-Checks), ihn zum Aufrufer zu verschieben hieße `routers/agent.py` ändern (T6). Ein Fehler
  im Block nimmt nur den Savepoint zurück, ein Fehler beim Commit geht an `_store_discovery`, das zurückrollt und
  loggt. Die Formprüfung der Spalte `credentials` sitzt als `@validates` am Modell statt in einem Schreib-Helfer:
  sie greift so bei jedem Schreiben.
- T4: Mehrere passende Container eines compose-Dienstes binden keinen Check; der Grund (`skippedChecks`) nennt die
  Kandidaten. Die Fund-Zusammenfassung selbst bleibt ohne Containernamen: jede Änderung an ihr macht einen Fund
  `changed` (`discovery.py`, `_seen_again`), nach dem Update kippte so jeder compose-Fund; das wäre sichtbares
  Verhalten außerhalb dieser Task; der Rest steht als Folgezeile R-1301 zur Triage. Die Fixture verliert die zweite Replika, deren Bindung an den ersten Namen genau
  das alte Verhalten prüfte; der neue Test deckt den Fall mit dem neuen Ergebnis ab.
