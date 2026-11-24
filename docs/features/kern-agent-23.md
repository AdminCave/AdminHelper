# kern-agent-23: Platten unter FreeBSD ohne Hänger, Paket `monitor` getrennt (R-1701, R-1728)

## Problem / Motivation

- **R-1701 (BUG):** Unter FreeBSD fragt `collectDisks` (`apps/agent/internal/monitor/collector.go`) über gopsutil
  `disk.Partitions` und `disk.Usage` jedes Dateisystem frisch ab (`Getfsstat(MNT_WAIT)`, statfs je Mount), ohne
  Timeout. Eine hängende NFS- oder SMB-Freigabe hält den ganzen Kern-Sammler an, bis `timeout 270` aus
  `cronentry.go` den Lauf beendet. Dann kommt kein Report, und der Host wirkt tot.
- **R-1728 (REF):** `internal/monitor` enthält Collectoren, Report-Zustand, Transport (`PushReport`), Ersteinrichtung
  (`Init`, TOFU-Pinning) und den Lauf (`Push`) in einem Paket. Die Tests des Zustands nach einem verlorenen Versand
  laufen deshalb über einen echten HTTP-Push. R-0688 hat die Aufteilung vorgeschlagen, kern-agent-20 hat sie
  ausdrücklich verschoben.

## Ziel & Nicht-Ziele

Ziel:
- Unter FreeBSD kommen Mounts und Belegung aus `Getfsstat(MNT_NOWAIT)`. Netz-Mounts (nfs, smbfs, fusefs) bekommen
  `statfs` mit 5 s Frist. Ein Mount, der bis dahin nicht antwortet, fehlt in diesem Lauf.
- `monitor` enthält nur noch Collectoren und Report-Zustand. Ein Lauf ist `Collect` plus `Done(pushed)`.
- Der Versand liegt in einem Blattpaket `internal/monitor/send`.
- `Init` und `Push` liegen in `internal/monitor/push`.

Nicht-Ziele:
- Kein anderes Verhalten unter Linux und Windows.
- Kein geändertes Wire-Format, keine geänderten CLI-Befehle.
- R-1706 (`service status` je rc.d-Skript): fährt nicht mit, der Messwert fehlt (Frage an Kevin).

## Betroffene Komponenten & Dateien

Nur `apps/agent`:
- `internal/monitor/collector.go`, neu `disks_bounded.go`, `disks_freebsd.go`, `disks_other.go` und `disks_test.go`.
- `internal/monitor/monitor.go`, `report.go` (Push-Teil), neu `cycle.go`.
- Tests, die `Push` fahren: `plan_test.go`, `loadgate_test.go`, `servicelogs_linux_test.go`, `reportstate_test.go`,
  `report_test.go`.
- Neu `internal/monitor/send/`, `internal/monitor/push/`.
- Aufrufer: `cmd/adminhelper-agent/main.go`, `run.go`, `monitor_init_test.go`, `internal/provision/provision.go`.

## Datenmodell / API / Migrationen

Keine. Report, Zustandsdateien und CLI bleiben unverändert.

## Externe Integrationen

- FreeBSD `getfsstat(2)`: `MNT_NOWAIT` liest die Statistik aus dem Kernel-Cache, ohne die Dateisysteme zu fragen.
- gopsutil v4.26.10 `disk/disk_freebsd.go:27,33` nutzt `MNT_WAIT`.

## Trade-offs & Alternativen

- **R-1701:** Statt nur gopsutil mit Context-Timeout zu fahren (das statfs im Kernel lässt sich nicht abbrechen),
  läuft ein eigener `Getfsstat(MNT_NOWAIT)`. Nur Netz-Mounts werden zusätzlich frisch gefragt, je in einer Goroutine
  mit Frist (`boundedStats`). Die Goroutine eines hängenden Mounts bleibt im Kernel, bis er antwortet. Der Lauf ist ein
  Oneshot-Prozess, also endet sie mit ihm.
- Der Stand aus kern-agent-22 T3 kam nach zwei Review-Runden ohne approve hierher. Der Test wackelte, weil `Done`
  vor dem Senden lief. Der Stand sendet erst und meldet dann, und er übernimmt nach der Frist die gepufferten
  Antworten. Die Gegenprobe ist ein Dauerlauf (`-count=20000` bei `GOMAXPROCS` 2 und 8).
- **R-1728:** Init und Push brauchen den Report, also können sie nicht im Transportpaket liegen, ohne einen
  Importzyklus zu erzeugen. Daher drei Pakete: `monitor` (Collectoren und Zustand) ← `send` (Versand, Blatt) ←
  `push` (Init und Lauf, importiert beide). Die Zustandstests nach einem verlorenen Versand fahren dann `Collect` und
  `Done(false)` ohne HTTP. Der Ende-zu-Ende-Lauf über `Push` bleibt als ein Test in `push`.
- Verworfen: nur `PushReport` auszulagern. Dabei blieben Init und TOFU im Sammelpaket.

## Risiken & Rollback

- R-1701 ist auf FreeBSD nicht gefahren, weil keine Box im Pool ist. Verifiziert wird über den Cross-Build in der
  Verify und eine reine Umrechnungsfunktion ohne Build-Tag, die unter Linux getestet wird.
- R-1728 berührt `internal/provision` (Risikopfad), also `security` für diese Task. Jede Task lässt sich einzeln
  revertieren.
- Heavy linux-full (Sammellauf).

## Doku-Impact

- `docs/developer/agent.html` DE+EN: Platten unter FreeBSD (T1), Paketaufteilung (T4).
- `changelog.d/kern-agent-23.md`: nur R-1701, weil die Aufteilung intern ist.

## Offene Fragen

Keine. R-1706 bleibt draußen, die Frage geht gesondert an Kevin.
