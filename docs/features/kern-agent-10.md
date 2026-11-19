<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-10 — Prozess-Metriken finden busybox-Applets

Zug aus R-1606 (BUG).

## Problem / Motivation

Ein Prozess-Ziel (`target.kind = process`) wird an zwei Stellen nach seinem Namen gesucht:
- `ownedBy` (`apps/agent/internal/probe/target.go:200`) für Port und Socket vergleicht `programName`: bei einem
  Multicall-Binary (busybox, toybox, dropbearmulti) das Applet aus `argv`.
- `processesNamed` (`apps/agent/internal/probe/sensor_local.go:162`) für `count`, `rss_bytes` und `uptime_s` und
  `dockerdRuns` (`sensor_local.go:372`) vergleichen nur den Prozessnamen (comm).

Ein `busybox crond` heißt im Kernel `busybox`: der Socket-Sensor findet ihn als `crond`, der Prozess-Sensor meldet
`count: 0`. Gefunden am Rand des Reviews von kern-agent-8 (2026-11-18).

## Ziel & Nicht-Ziele

- **Ziel:** `processesNamed` und `dockerdRuns` messen einen Prozess mit demselben Namen, den `ownedBy` sieht: der
  Prozessname, bei einem Multicall-Binary das Applet (`programName`). Ein Multicall-Prozess, dessen Applet nicht
  lesbar ist, zählt nicht mit (wie in `ownedBy`).
- **Nicht-Ziel:** andere Namensregeln (Interpreter, `exe`-Link); ein Ziel `busybox` selbst findet weiter nur
  Prozesse, deren Applet `busybox` heißt, also keine.

## Betroffene Komponenten & Dateien

Agent: `apps/agent/internal/probe/sensor_local.go` (`processesNamed`, `dockerdRuns`, ein gemeinsamer Vergleich),
Tests in `sensor_local_test.go` (Nahtstellen `processName`/`processArgs`) und `sensor_local_linux_test.go` (echter
`busybox sleep`, ohne busybox auf dem Host ein Skip).

## Datenmodell / API / Migrationen

Keine. Werte und Felder bleiben, nur die Zuordnung der Prozesse ändert sich.

## Externe Integrationen

Keine neuen; gopsutil wie bisher (`Name`, `Cmdline` über `processArgs`).

## Trade-offs & Alternativen

- Je Prozess `programName` aufrufen kostet bei jedem Prozess einen zweiten Namens-Lesezugriff. Stattdessen den schon
  gelesenen Namen nehmen und nur bei einem Multicall-Namen `argv` lesen: ein Lesezugriff mehr nur für busybox &
  Co. **Empfehlung:** so.

## Risiken & Rollback

Ein Prozess-Ziel, das einem Applet-Namen gleicht (`crond`, `httpd`), zählt jetzt auch die busybox-Applets dieses
Namens mit; das ist das gewollte Verhalten und deckt sich mit Port- und Socket-Sensor. Rollback: Revert.

## Doku-Impact

`docs/admin/monitoring.html` (DE+EN): beschreibt das Prozess-Ziel nicht bis zur Namensregel, keine Änderung.
`changelog.d/kern-agent-10.md` (Fixed).

## Offene Fragen

Keine.
