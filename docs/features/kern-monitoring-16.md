# Monitoring-Module: Nachlese zu Bindung, Grenzen, Erkennung und Zugangsdaten-Datei (kern-monitoring-16)

Roadmap: R-1254, R-1260, R-1262, R-1263, R-1295 (Kevin 2026-11-10/11 Triage). Nachlese aus den Prüfungen von
`arch-monitoring-module`. Einzelheiten der Sicherheitszeilen stehen nur in der privaten Roadmap. R-1264 (Folgearbeit
Katalog-Rollout, Grabsteine, Fühler-Erweiterungen) fährt nicht mit: Grabsteine brauchen eine Migration, das Ausrollen
geänderter Katalog-Definitionen ändert sichtbares Verhalten bestehender Checks; beides ist eine Frage an Kevin, die
Zeile wandert in einen eigenen Zug.

## Problem / Motivation
- **R-1295 / R-1263 (Agent, Zugangsdaten-Datei):** Unter Windows öffnet `readPrivate`
  (`apps/agent/internal/credentials/store_windows.go:33`) die Datei nur mit `FILE_SHARE_READ`. Ein gleichzeitiges
  `credentials.Set` ersetzt die Datei per Rename (`store.go:220`) und scheitert im Lesefenster mit „Access is
  denied“; `TestSetKeepsTheOtherSetsMadeAtTheSameTime` ist auf go-windows flaky. Unter Linux öffnet `readPrivate`
  (`store_linux.go:23`) eine FIFO am Pfad blockierend, bevor es den Dateityp prüft.
- **R-1263 (Nits):** `probe/fields.go` beschreibt Punkt-Schlüssel ungenau; `probe/sensor_sql.go:222` prüft eine
  Zeile redundant auf Zeilenumbruch; `apply_discovery` (`apps/monitoring/app/discovery.py`) ruft `commit`/`rollback`
  auf der übergebenen Session; die Spalte `MonitorDiscovery.credentials` wird ohne Formprüfung geschrieben; der
  Downgrade von `b8d0f2a4c6e8` verwirft `monitor_checks.silent`, ohne dass die Doku es sagt; eine Docstring-Zeile in
  `checkers/probe.py` ist 157 Zeichen lang.
- **R-1254:** Nachlese zur Bindung von `compose_project`-Modulen (`module_sync`): die Fund-Zusammenfassung nennt den
  gebundenen Container.
- **R-1260:** Nachlese an den Grenzen des Monitoring-Dienstes (Vorlagen-Sync, Push-Checks, Report-Endpunkt).
- **R-1262:** Ein Probe-Ziel `container`/`unit`/`process` mit leerem Namen bleibt dauerhaft `unknown`; die
  Ersatz-Instanz (`matched_by`) hängt am Unit-Zustand, ein gestoppter Dienst löst `changed` aus; `LogParams` nimmt
  Glob-Units und `match`-Felder an, die der Agent als `invalid` ablehnt; ein Teil-Scan setzt `next_scan_at` wie ein
  voller, ein Host mit stets ablaufendem Teil bekommt nie einen vollen Scan und nie `gone`.

## Ziel & Nicht-Ziele
- Gleichzeitiges Lesen und Ersetzen der Zugangsdaten-Datei klappt unter Windows; eine FIFO am Pfad blockiert nicht.
- Die Bindung eines Moduls ist im Fund sichtbar.
- Die Server-Grenzen (`LogParams`, Probe-Ziel) lehnen ab, was der Agent ablehnen würde.
- R-1260 nach der privaten Roadmap.
- Erkennung: kein `changed` durch einen bloß gestoppten Dienst, ein voller Scan kommt auch bei Teil-Scans.
- Nicht-Ziele: R-1264, neue Fühler, Änderungen am Wire-Format des Agent-Reports, Migrationen.

## Betroffene Komponenten & Dateien
- Agent: `apps/agent/internal/credentials/store_windows.go`, `store_linux.go`, Tests; `internal/probe/fields.go`,
  `internal/probe/sensor_sql.go`.
- Monitoring: `app/module_sync.py`, `app/template_sync.py`, `app/routers/agent.py`, `app/check_configs.py`,
  `app/catalog/sensors.py`, `app/discovery.py`, `app/checkers/probe.py`, Tests unter `apps/monitoring/tests/`.

## Datenmodell / API / Migrationen
Keine Migration. Die API lehnt einen leeren Zielnamen und Glob-Unit/`match` im Log-Fühler ab (422). Das
Report-Format bleibt.

## Externe Integrationen
Windows `CreateFileW` (`FILE_SHARE_DELETE`) und `MoveFileExW` (Go `os.Rename`), Microsoft-Doku, im Bau nachgelesen.

## Trade-offs & Alternativen
- **Windows-Rename:** `FILE_SHARE_DELETE` beim eigenen Lesen und ein begrenzter Wiederholversuch beim Rename (wie Go
  `cmd/internal/robustio`). Die eigenen Leser im Test laufen unter dem Lock; einen fremden Leser ohne Delete-Freigabe
  (Virenscanner) fängt nur der Wiederholversuch ab.
- R-1254 und R-1260: Varianten und Begründung in der privaten Roadmap; ohne Kevin-Entscheidung, weil das sichtbare
  Verhalten nur strenger wird und kein API-Vertrag bricht.

## Risiken & Rollback
- Strengere Grenzen können bestehende Checks mit leerem Zielnamen oder Glob-Units beim Bearbeiten ablehnen; sie
  liefen vorher nie. Rollback je Task-Commit.

## Doku-Impact
`docs/admin/monitoring.html` und EN (Bindung, Scan-Rhythmus), `docs/developer/monitoring.html` und EN
(Downgrade-Satz), `changelog.d/kern-monitoring-16.md` (neutral).

## Offene Fragen
Keine für diesen Zug. R-1264 als Frage an Kevin (eigener Zug).
