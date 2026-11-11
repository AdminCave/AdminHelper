# Agent: Härtung der Werkzeugaufrufe, der Probe-Parameter und der Probe-Zugangsdaten (kern-monitoring-15)

Roadmap: R-1252, R-1259, R-1266, R-1261, R-1255, R-1256, R-1270 (Kevin 2026-11-10 Triage, R-1252/R-1259/R-1266
vor dem Release 0.47.0, R-1110). Nachlese aus den Prüfungen von `arch-monitoring-module` und `kern-monitoring-6`.
Einzelheiten der Sicherheitszeilen stehen nur in der privaten Roadmap.

## Problem / Motivation
- **R-1259:** Die Befehls-Freigabeliste (`commandAllowlist`, `apps/agent/internal/monitor/allowlist.go`) und ihr
  AST-Test gelten nur im Paket `internal/monitor`. Die Pakete `internal/probe` und `internal/discovery` starten
  Werkzeuge über `execx.Run` (`runTool`, `sensor_local.go:54`, `discovery.go:74`) ohne diese Prüfung. Das Konzept
  verlangt die feste Liste für jeden Werkzeugaufruf des Agenten.
- **R-1252:** Härtung der Probe-Parameter.
- **R-1266:** Härtung der Probe-Zugangsdaten (`monitor credential set`).
- **R-1261:** Nachlese zur Ziel-Zuordnung: `Cgroups.Holds` (`apps/agent/internal/probe/target.go:287`), die
  Zuordnung veröffentlichter Ports in `collectSockets` (`apps/agent/internal/discovery/discovery.go:375`), der
  Prozess-Abgleich bei Socket-Aktivierung.
- **R-1255:** Die Argumentklasse `devtype` lehnt smartctl-Gerätetypen mit `/` ab (`areca,N/E`, `hpt,L/M/N`). Erst
  belegen, ob `smartctl --scan` solche Typen ausgibt (nicht verifiziert).
- **R-1256:** Die Collector-Stubs der Tests (`stubPvesh`, `stubZpool` …) zeichnen Aufrufe auf. Geprüft wird die
  Liste aber nur gegen eine handkopierte Tabelle in `allowlist_test.go`.
- **R-1270:** `cleanPath` (`checkMarkers`, `apps/agent/internal/discovery/discovery.go`) lässt Backslash und `:` zu.
  Heute ist das unerreichbar, weil die Marker-Prüfung nur unter Linux läuft.

## Ziel & Nicht-Ziele
- Jeder Werkzeugaufruf von `monitor`, `probe` und `discovery` läuft durch eine gemeinsame Freigabeliste. Ein
  AST-Test über alle drei Pakete verbietet direkte Starts.
- Die Collector-Stubs prüfen jeden aufgezeichneten Aufruf gegen die Liste.
- `devtype` nimmt `/` nur, wenn smartctl solche Typen belegt ausgibt.
- Die Ziel-Zuordnung (cgroups, veröffentlichte Ports) ist eindeutig.
- `cleanPath` lehnt Backslash und `:` ab.
- R-1252 und R-1266 nach Kevins Entscheidung der Variante (Tasks `[?]`).
- Nicht-Ziele: neue Fühler, neue Werkzeuge, Änderungen am Wire-Format des Reports.

## Betroffene Komponenten & Dateien
- `apps/agent/internal/monitor/allowlist.go`, `allowlist_test.go` und die Collector-Tests mit Stubs.
- Ein neues Paket für die gemeinsame Freigabeliste unter `apps/agent/internal/` (Name im Bau, SPDX-Header).
- `apps/agent/internal/probe/`: `sensor_local.go`, `sensor_local_linux.go`, `sensor_log.go`, `sensor_sql.go`,
  `target.go`, `guard.go`, `probe.go`, `sensor_unixsocket.go`.
- `apps/agent/internal/discovery/discovery.go`.
- `apps/agent/internal/credentials/` und `apps/agent/cmd/adminhelper-agent/main.go` (R-1266, je nach Variante).
- `apps/monitoring/app/check_configs.py` (R-1252, je nach Variante).

## Datenmodell / API / Migrationen
Keine Migration. Report-Format unverändert. R-1266 kann je nach Variante die Datei `credentials.json`
(`fileVersion`) und die CLI `monitor credential set` erweitern. Das entscheidet Kevin (`[?]`).

## Externe Integrationen
smartmontools: `smartctl --scan` und Gerätetypen (`-d`), Quelle: smartctl(8) und der Quelltext von smartmontools
(R-1255, im Bau nachgelesen).

## Trade-offs & Alternativen
- **Gemeinsame Freigabeliste:** Die Liste kommt in ein eigenes Paket, das `monitor`, `probe` und `discovery`
  importieren. `probe` kann `monitor` nicht importieren, ohne einen Zyklus zu bilden. Die Alternative, je Paket eine
  eigene Liste, verdoppelt Klassen und Test. Empfehlung: gemeinsames Paket.
- **R-1252, R-1266:** Varianten und Empfehlung stehen in der privaten Roadmap; Kevin wählt (Tasks `[?]`).

## Risiken & Rollback
- Eine zu enge Freigabeliste lässt einen Fühler scheitern (Status `error` mit „not on the command allowlist“). Der
  Test jedes heutigen Aufrufs fängt das ab. Rollback je Task-Commit.
- R-1266 kann je nach Variante bestehende Probes bis zum Neusetzen der Zugangsdaten stoppen.

## Doku-Impact
`docs/developer/agent.html` und `docs/en/developer/agent.html` (Befehls-Freigabeliste, Zugangsdaten), bei R-1266
auch `docs/admin/monitoring.html` und die EN-Fassung (Bedienung `credential set`); dazu `changelog.d/kern-monitoring-15.md`.

## Offene Fragen
1. R-1252 und R-1266: Variante nach Kevins Wahl (private Roadmap) → T6, T7 `[?]`
