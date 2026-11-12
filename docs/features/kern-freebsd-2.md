# kern-freebsd-2: FreeBSD-Nacharbeit (Log-Hinweis, Swap-Fehlertext, Rotationsprüfung)

Roadmap: R-1327, R-1330, R-1331 (Kevin 2026-11-12, Triage). R-1332 fährt nicht mit: `apps/monitoring/app/checkers/agent.py`
und `apps/desktop/ui/src/lib/api/types.ts` ändern offene Branches (`overlap.sh`), die Zeile geht nach
`tasks/kern-freebsd-3.md`.

## Problem / Motivation

- **R-1327:** Seit kern-freebsd-1 schreibt frpc unter FreeBSD nach `/var/log/adminhelper/frpc.log` statt ins syslog.
  Zeilen, die ein früherer Build mit dem Tag `adminhelper-frpc` ins syslog geschrieben hat, bleiben nach dem Upgrade
  in `/var/log/messages`, `/var/log/daemon.log` und deren Archiven, bis newsyslog sie herausrotiert. Kevin: Hinweis in
  Doku und Release-Notes, keine automatische Bereinigung fremder Systemlogs. Einzelheiten in `tasks/private/`.
- **R-1330:** `collectSwapAndCPUCount` (`apps/agent/internal/monitor/collector.go:215`) erkennt „kein Swap-Gerät“ am
  Fehlertext `no swap devices found` von gopsutil (`mem/mem_freebsd.go:121`, v4.26.10). Ändert ein gopsutil-Bump den
  Text, meldet ein FreeBSD-Host ohne Swap still keinen Swap mehr, und kein Test merkt es.
- **R-1331:** `scripts/tests/box_freebsdbox.sh:231` prüft nach der Rotation nur die INUM-Spalte von `fstat`. Eine Datei
  auf einem anderen Dateisystem mit derselben Inode-Nummer würde als „neues Log“ zählen.

## Ziel & Nicht-Ziele

- **Ziel:**
  - `docs/admin/agent-deployment.html` + EN (FreeBSD, Logs) und `changelog.d/kern-freebsd-2.md` sagen, dass frühere
    Builds frpc-Ausgaben ins syslog schrieben, dass diese Zeilen dort bis zur Rotation bleiben und das Paket fremde
    Systemlogs nicht anfasst.
  - Der Fehlertext steht als Konstante in `collector.go`; ein Test liest die `mem_freebsd.go` des gepinnten gopsutil
    und wird rot, wenn sie den Text nicht mehr erzeugt.
  - Die Box-Prüfung vergleicht MOUNT und INUM.
- **Nicht-Ziele:** kein Säubern von `/var/log/messages`; kein Wechsel weg vom Fehlertext (gopsutil hat keinen
  exportierten Fehler dafür).

## Betroffene Komponenten & Dateien

- `apps/agent/internal/monitor/collector.go`, `collector_test.go` (agent).
- `scripts/tests/box_freebsdbox.sh` (Harness-Pfad, Kevins Wort in der Notiz von R-1331).
- `docs/admin/agent-deployment.html`, `docs/en/admin/agent-deployment.html`, `changelog.d/kern-freebsd-2.md`.

## Datenmodell / API / Migrationen

Keine.

## Externe Integrationen

gopsutil `mem.SwapMemory` unter FreeBSD (`mem_freebsd.go`: `errors.New("no swap devices found")` bei
`vm.nswapdev == 0`). `fstat(1)`: Spalten `USER CMD PID FD MOUNT INUM MODE …` (FreeBSD-Manpage fstat(1)).

## Trade-offs & Alternativen

- R-1330: Test gegen die Quelle des gepinnten Moduls statt eines FreeBSD-Laufs ohne Swap: läuft auf jeder Plattform
  der PR-CI und schlägt beim Bump an; die Box hat Swap, ein Lauf ohne Swap bräuchte eine eigene VM-Konfiguration.
- R-1331: MOUNT aus `df -P` der Logdatei; fstat zeigt den Mountpunkt.

## Risiken & Rollback

Gering; Revert der Task-Commits.

## Doku-Impact

`docs/admin/agent-deployment.html` + EN (Abschnitt Logs, FreeBSD-Absatz). CHANGELOG `### Changed`.

## Offene Fragen

Keine.
