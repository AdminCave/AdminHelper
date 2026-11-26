# kern-agent-25 — Ein Seam-Typ fuer die frpc-Dienstaktionen

Roadmap: R-1756 (REF; Kevin 2026-11-24: R-0703 Schritt 1 nur `monitor`, Rest spaeter; Kevin 2026-11-25: faellig).

## Problem / Motivation

kern-agent-21 hat im Paket `monitor` sieben anonyme Structs mit drei `run`-Formen auf einen benannten Typ `command`
gebracht. R-1756 fragt, ob dasselbe ausserhalb von `monitor` noetig ist (`frpc`, `probe`, `discovery`, `cmd`), und
danach, ob `t.Parallel` moeglich wird.

Bestand auf origin/main:
- `frpc/sync.go:25`: sieben Paketvariablen fuer die Dienstaktionen (`restartService`, `disableService`,
  `enableService`, `isActive`, `reloadService`, `isDown`, `ownsAdminPort`), je Plattform in `platform_linux.go`,
  `platform_freebsd.go` und `platform_windows.go` implementiert. Die Tests sichern und setzen alle sieben einzeln
  zurueck (`sync_flow_test.go:46-58`, dazu `apply_test.go`).
- `probe` und `discovery`: je Einstiegspunkt der Allowlist eine einzelne Funktionsvariable in der Form ihrer echten
  Funktion (`runTool = allowlist.Run` in `probe/sensor_local.go:63` und `discovery/discovery.go:83`,
  `runToolEnv`, `runCapped`, `runToolReader`). Keine anonymen Structs, keine abweichenden Formen.
- `cmd/adminhelper-agent`: Einzelnaehte verschiedener Art (Terminal, Signale, Phasen des Laufs), je eine Variable.

## Ziel & Nicht-Ziele

Ziel: die sieben frpc-Dienstaktionen werden ein benannter Typ `serviceOps` mit einer Paketvariablen `service`; ein
Test tauscht und sichert die Dienstaktionen als ein Wert. Verhalten unveraendert.

Nicht-Ziele:
- `probe`, `discovery`, `cmd`: ihre Naehte haben schon je eine Form; ein Typ darum fuegte nichts hinzu (YAGNI).
- `t.Parallel`: bleibt unmoeglich, solange die Naehte Paketvariablen sind (jede Naht ist geteilter Zustand); das
  geht erst mit Naehten als Felder eines Syncer-/Collector-Werts, dem vollen Umbau aus R-0703, der nicht beauftragt
  ist. Das ist das Ergebnis der Pruefung aus R-1756.
- `ensureDataDir` (`frpc/sync.go:36`): eine Einzelnaht anderer Art, bleibt.

## Betroffene Komponenten & Dateien

`apps/agent/internal/frpc`: `sync.go` (Typ und Variable, Aufrufer), `admin.go` (`ownsAdminPort`),
`sync_flow_test.go`, `apply_test.go`.

## Datenmodell / API / Migrationen

Keine.

## Externe Integrationen

Keine.

## Trade-offs & Alternativen

- Interface mit Plattform-Typen statt Funktionsfeldern: verlangt je Stub einen Typ; die Tests stubben mit
  Closures. Funktionsfelder wie bei `command` (kern-agent-21).

## Risiken & Rollback

Ein Aufrufer, der eine falsche Aktion erwischt (etwa `enable` statt `restart`): die Sync-Flow-Tests zaehlen jede
Aktion je Fall. Windows- und FreeBSD-Tests werden per `GOOS=… go vet ./internal/frpc/` mitkompiliert. Rollback per
Revert.

## Doku-Impact

Keine (internes Refactoring, kein Verhalten).

## Offene Fragen

Keine.
