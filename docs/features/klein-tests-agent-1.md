<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-agent-1 — Agent: zwei Test-Lücken

Roadmap R-0851, R-0883. Beide ergänzen Tests im Go-Agent, kein Produktivcode ändert sich. `overlap.sh` ohne Treffer.

## Problem / Motivation
- **R-0851:** `apps/agent/cmd/adminhelper-agent/docs_cli_test.go` liest nur Aufrufe, die den Namen als eigenes Wort
  tragen (`docCallRE`). Aufrufe über einen Pfad oder die Windows-Binary
  (`.\adminhelper-agent-windows-x86_64.exe service install` in `docs/admin/agent-deployment.html`,
  `adminhelper-agent-windows-x86_64.exe version` in `docs/developer/cicd.html`) prüft niemand gegen den echten
  Befehlsbaum. Soll: der Leser erkennt Pfad- und `.exe`-Aufrufe und prüft sie wie die anderen.
- **R-0883:** Der `ctx`, den `collectSmart` an den scan-Aufruf von smartctl gibt (`internal/monitor/smart.go`), und
  der `ctx`, den `serviceHealth` an `filterEnabledInactive` und `resolveAliases` gibt (`services_linux.go`), prüft
  kein Test: ein Aufruf mit `context.Background()` bliebe grün, und ein hängender Lauf würde das 60-s-Budget des
  Oneshot-Laufs sprengen. Soll: je ein Test, der den durchgereichten `ctx` erkennt.

## Ziel & Nicht-Ziele
- Tests (und beim Leser ein Normalisierungsschritt in der Testdatei), kein Produktivcode. Nicht-Ziel: den
  Parser `parseCalls` der Box-Skripte ändern.

## Betroffene Komponenten & Dateien
`apps/agent/cmd/adminhelper-agent/docs_cli_test.go` (T1); `apps/agent/internal/monitor/smart_test.go`,
`services_linux_test.go` (T2).

## Trade-offs
Pfad und `.exe` werden vor dem Abgleich auf den Namen zurückgeführt, statt `parseCalls` zu erweitern: `parseCalls`
gehört zu den Box-Skripten und bleibt unberührt.

## Risiken & Rollback
Test-only; Rollback: Revert. Findet der erweiterte Leser eine echte Abweichung in der Doku (ein Befehl, den es nicht
gibt), ist das ein Doku-Bug: korrigieren, DE+EN.

## Doku-Impact
Keine, außer eine gefundene Abweichung wird korrigiert (Task nennt dann die Seiten).

## Offene Fragen
Keine.
