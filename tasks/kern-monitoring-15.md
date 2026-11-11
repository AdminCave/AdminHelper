# Agent: Härtung der Werkzeugaufrufe, der Probe-Parameter und der Probe-Zugangsdaten — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-15 · Review: pro Task
Spec: docs/features/kern-monitoring-15.md (Roadmap R-1252, R-1259, R-1266, R-1261, R-1255, R-1256, R-1270)
Heavy: linux-full — apps/agent (Fühler, Erkennung, Freigabeliste)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1259: Gemeinsame Befehls-Freigabeliste für monitor, probe und discovery  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/allowlist.go, apps/agent/internal/monitor/allowlist_test.go, apps/agent/internal/probe/sensor_local.go, apps/agent/internal/probe/sensor_local_linux.go, apps/agent/internal/probe/sensor_log.go, apps/agent/internal/probe/sensor_sql.go, apps/agent/internal/discovery/discovery.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go, apps/agent/internal/probe/sensor_local_test.go, apps/agent/internal/probe/sensor_log_test.go, apps/agent/internal/probe/sensor_sql_test.go, apps/agent/internal/discovery/discovery_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @2d780983e 2026-11-11T05:57:25+01:00
Review: approve (.ah-out/review/kern-monitoring-15/T1.verdict.json)
Änderung:
- Die Freigabeliste (Klassen, Einträge, `commandAllowed`, der prüfende Start) zieht in ein eigenes Paket unter
  `apps/agent/internal/`. Neue Dateien bekommen einen SPDX-Header; der Pfad wird im Bau per `set-files` nachgetragen.
- `monitor`, `probe` und `discovery` starten Werkzeuge nur noch darüber.
- Neue Einträge für die heutigen Aufrufe von `probe` (journalctl, systemctl show, docker inspect, runuser/psql,
  mariadb/mysql) und `discovery` (systemctl list-units, docker ps/inspect, dpkg-query, rpm). Variable Teile laufen
  gegen Klassen, die nie mit `-` beginnen.
- Der AST-Test verbietet direkte Starts in allen drei Paketen. Je Paket gibt es eine Gegenprobe.
- Test: jeder heutige Aufruf der drei Pakete passiert die Liste, Fallen werden abgelehnt.
- Mehr als acht Dateien, weil jeder Aufrufer des Pakets umzieht.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/...
Doku: → T8

### T2 — R-1256: Collector-Stubs prüfen jeden Aufruf gegen die Freigabeliste  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/allowlist_test.go, apps/agent/internal/monitor/plugins_test.go, apps/agent/internal/monitor/smart_test.go, apps/agent/internal/monitor/system_linux_test.go, apps/agent/internal/monitor/updates_linux_test.go, apps/agent/internal/monitor/services_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @f20b7be95 2026-11-11T06:07:06+01:00
Review: approve (.ah-out/review/kern-monitoring-15/T2.verdict.json)
Änderung:
- Die Stubs der Collector-Tests (`stubPvesh`, `stubZpool` …) prüfen jeden aufgezeichneten Aufruf mit
  `commandAllowed`. Ein Aufruf außerhalb der Liste lässt den Test scheitern.
- Die handkopierte Tabelle bleibt nur, wo kein Stub den Aufruf zeigt.
- Gegenprobe: ein Stub-Aufruf außerhalb der Liste wird rot.
- Die Stub-Dateien werden im Bau per `set-files` nachgetragen.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/...
Doku: keine (nur Tests)
Abhängt von: T1

### T3 — R-1255: smartctl-Gerätetypen mit '/' belegen, ggf. zulassen  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/allowlist_test.go
Änderung:
- Zuerst belegen, ob `smartctl --scan` Typen mit `/` ausgibt (smartctl(8), Quelltext von smartmontools).
- Belegt: Die Klasse `devtype` nimmt `/` an genau den belegten Stellen, und ein Test zeigt `areca,N/E` vorher rot.
- Nicht belegt: `[~]` mit Quelle.
- Die Datei der Klasse aus T1 wird im Bau nachgetragen.
Beweis: kern-monitoring-6 Branch-Review 2026-11-09 · feature/kern-monitoring-6@073938ce allowlist.go argClasses devtype
Dedup-Key: bug:agent:allowlist.go:devtype
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/...
Doku: keine (Klassen-Detail, die Liste ist in agent.html nur als Prinzip beschrieben)
Abhängt von: T1

### T4 — R-1261: Ziel-Zuordnung nachschärfen (cgroups, veröffentlichte Ports, Prozess-Abgleich)  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/target.go, apps/agent/internal/probe/target_test.go, apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/discovery/discovery.go, apps/agent/internal/discovery/discovery_test.go
Änderung:
- `Cgroups.Holds` entscheidet je Hierarchie eindeutig, statt mit einem Treffer in irgendeiner auszukommen.
- `collectSockets` schlüsselt veröffentlichte Ports nach Adresse und Port.
- Den Prozess-Abgleich bei Socket-Aktivierung prüfen; je Befund ein Fix mit Test, oder eine
  belegte Begründung unter `## Entscheidungen`.
- Test je Fall: vorher rot, nachher grün.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/... ./internal/discovery/...
Doku: keine (interne Zuordnung, Verhalten wie dokumentiert)

### T5 — R-1270: cleanPath lehnt Backslash und ':' ab  [ ]
Komponente: agent · Dateien: apps/agent/internal/discovery/discovery.go, apps/agent/internal/discovery/discovery_test.go
Änderung:
- `cleanPath` lehnt Pfade mit `\` oder `:` ab, unabhängig vom Betriebssystem.
- Test: beide Fälle abgelehnt, ein gültiger Pfad bleibt.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/discovery/...
Doku: keine (unerreichbarer Pfad, kein dokumentiertes Verhalten)

### T6 — R-1252: Probe-Parameter härten  [?] (Variante: siehe private Roadmap)
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/probe/sensor_unixsocket.go, apps/agent/internal/probe/sensor_log.go
Änderung:
- Umsetzung nach Kevins Wahl der Variante (Spec, Trade-offs).
- Test: ein nicht freigegebener Parameter wird abgelehnt, die Katalog-Module laufen weiter.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/...
Doku: → T8

### T7 — R-1266: Probe-Zugangsdaten härten  [?] (Variante: siehe private Roadmap)
Komponente: agent · Dateien: apps/agent/internal/credentials/store.go, apps/agent/internal/credentials/store_test.go, apps/agent/internal/probe/probe.go, apps/agent/internal/probe/probe_test.go, apps/agent/cmd/adminhelper-agent/main.go
Änderung:
- Umsetzung nach Kevins Wahl der Variante (Spec, Trade-offs).
- Test: nach der gewählten Variante.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/credentials/... ./internal/probe/... ./cmd/...
Doku: → T8

### T8 — Doku: Freigabeliste und Zugangsdaten DE+EN, CHANGELOG-Fragment  [ ]
Komponente: scripts · Dateien: docs/developer/agent.html, docs/en/developer/agent.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-15.md
Änderung:
- `agent.html` DE+EN: Die Freigabeliste gilt für `monitor`, `probe` und `discovery`, mit dem AST-Test über alle
  drei Pakete. Dazu der Abschnitt Zugangsdaten nach T7.
- `monitoring.html` DE+EN: Bedienung von `credential set` nach T7.
- `changelog.d/kern-monitoring-15.md`: neutral, unter `### Security` und `### Fixed`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: (diese Task)
Task-Review: am Ende

## Entscheidungen
- T1: Neues Paket `internal/allowlist` (Tabelle, Klassen, `Run`/`RunEnv`); `monitor/allowlist.go` bleibt als dünne
  Hülle, damit die Collector-Aufrufer und ihre Tests unverändert bleiben. `execTimed` bleibt für die Timeout-Tests.
- T1: Klasse `unitarg` (`-.slice`, `-.mount` oder ein Unit-Name) nur direkt nach `--` oder hinter einer Option im
  selben Argument; der probe-Fühler nahm Wurzel-Units schon vorher an, ein Test erzwingt die Stellung.
- T1: Die SQL-Abfragen stehen als Literale in der Tabelle; ein probe-Test fährt jede Abfrage beider Engines durch
  einen Stub, der `allowlist.Allowed` prüft. So fällt eine Drift auf, ohne dass `allowlist` `probe` importiert.
- T1: Die Stubs von probe und discovery prüfen jeden Aufruf mit `allowlist.Allowed`; der Kappungstest bekam echte
  64-stellige Container-IDs statt Zählnummern.
- T2: Die Tabelle in `TestAllowlistTakesEveryCollectorCall` behält nur, was kein Stub zeigt: smartctl über einen
  absoluten Pfad der Plattform, die `sc`-Aufrufe (Windows) und Formen variabler Teile, die die Stub-Antworten nicht
  tragen. Der smartctl-Stub prüft den Basisnamen, weil `/usr/sbin/smartctl` unter Windows kein absoluter Pfad ist.
