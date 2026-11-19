<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-8 — Agent: Programmnamen von Multicall-Binaries

Roadmap: R-1523. R-1524 fährt nicht mit (`discovery.go` ändert auch `feature/kern-monitoring-18`, nächster Zug
`tasks/kern-agent-9.md`).

## Problem / Motivation

Die Namensregeln des Wächters (`apps/agent/internal/probe/guard.go`: `blockedProcesses`, `hostDaemons`,
`forwarders`, `activators`, `superServers`; Unix-Socket-Weg `unixActivator`) urteilen nach dem Prozessnamen
(`processName`, `guard.go:300`). Ein Multicall-Binary (busybox, toybox, dropbearmulti), das ohne Link unter seinem
eigenen Namen startet (`busybox tcpsvd …`), trägt den Namen des Binaries, nicht den des Applets; die Regel für das
Applet greift dann nicht.

## Ziel & Nicht-Ziele

**Ziel:** An jeder Stelle, an der eine Namensregel urteilt, gilt für ein Multicall-Binary der Name des Applets, so
wie das Binary selbst ihn bestimmt: `argv[0]` (Basisname), und ist das der Name des Binaries, `argv[1]`. Lassen sich
die Argumente nicht lesen oder nennen sie kein Applet, weist der Wächter ab (fail-closed, wie bei `exe` in
`checkForwarder`).

**Nicht-Ziele:** keine neuen Namen in den Listen; keine Prüfung, ob das Applet im Binary existiert; ein Prozess, der
seine Argumente selbst umschreibt, bleibt das hingenommene Restrisiko der Namensregeln (Doku).

## Betroffene Komponenten & Dateien

- `apps/agent/internal/probe/guard.go`: Liste der Multicall-Binaries und eine Funktion, die den Namen des Programms
  aus Name und Argumenten bestimmt; Aufrufer `guard.go:592` (activator), `:714` (judgeListener), `:839`
  (checkInside), `checkForwarder` (`:765`).
- `apps/agent/internal/probe/sensor_local_linux.go:223`, `sensor_local_freebsd.go:148` (Unix-Socket-Weg),
  `target.go:193`, `discover.go:41` (`ProcessName` für die Erkennung).
- Tests: `apps/agent/internal/probe/guard_test.go` (über die Hooks `processName`/`processArgs`).
- Doku: `docs/admin/monitoring.html` und `docs/en/admin/monitoring.html` (Abschnitt „Nur dieser Host“).

## Datenmodell / API / Migrationen

Keine. Die Erkennung meldet für ein so gestartetes Programm künftig den Applet-Namen statt `busybox`.

## Externe Integrationen

Keine (Verhalten von busybox: Applet aus dem Basisnamen von `argv[0]`, sonst `busybox <applet>`; dropbearmulti
ebenso; nicht gegen upstream-Doku verifiziert, Tests mit beiden Formen).

## Trade-offs & Alternativen

- Auflösung in `nameOf` selbst: einfacher, aber die Tests ersetzen `processName` und sähen sie nicht. Empfohlen: eine
  eigene Funktion über beiden Hooks, die alle Namensregel-Aufrufer nutzen.
- Multicall-Binary pauschal abweisen: schlösse busybox-Dienste (etwa `httpd`) aus, die heute geprüft werden können.

## Risiken & Rollback

Ein unlesbares argv eines busybox-Prozesses (anderer Nutzer, hidepid) führt künftig zu `not_allowed`; bisher wurde
er nach `busybox` beurteilt. Rollback: Revert des Task-Commits.

## Doku-Impact

`docs/admin/monitoring.html` DE+EN: ein Satz, dass bei Multicall-Programmen der Name des Applets gilt und
unlesbare Argumente abgewiesen werden. Changelog-Fragment.

## Offene Fragen

Keine.
