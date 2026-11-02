<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-3 — Agent: Terminal nach Ctrl-C, Go 1.27

Roadmap: R-1007 (BUG), R-1036 (REF). Zeilenangaben `origin/main@0294b3b1`.

## Problem / Motivation
- **R-1007:** `adminhelper-agent provision --token-stdin` (und jede andere Stelle, die `readStdinSecret` nutzt) liest
  auf einem Terminal über `term.ReadPassword` (`apps/agent/cmd/adminhelper-agent/main.go:106`) ohne Echo. Bricht der
  Nutzer mit Ctrl-C ab, endet der Prozess über das Standard-Signalverhalten, ohne dass `x/term` den Terminalzustand
  zurücksetzt: die Shell bleibt ohne Echo, bis der Nutzer `stty sane` oder `reset` tippt.
- **R-1036:** `apps/agent/go.mod` deklariert `go 1.25.0`; Go 1.25 ist seit 2026-08-19 ohne Support. CI, Audit und
  Release bauen schon mit 1.27 (`go-version: "1.27"`). Die direkten Abhängigkeiten gopsutil, x/sys und x/term haben
  neuere Fassungen (`go list -m -u`, 2026-11-02).

## Ziel & Nicht-Ziele
- Ziel: Nach Ctrl-C während der verdeckten Eingabe hat das Terminal wieder seinen vorherigen Zustand, der Prozess
  endet mit Exit 130 (Linux-Konvention für SIGINT) und gibt einen Zeilenumbruch aus.
- Ziel: `go 1.27.0` mit `toolchain go1.27.3`, gopsutil v4.26.10, x/sys v0.49.0, x/term v0.47.0.
- Nicht-Ziel: Andere Signale als Interrupt (SIGTERM an einen interaktiven Prompt ist kein Nutzerfall); andere
  Abhängigkeiten als die genannten (cobra und lumberjack sind aktuell).

## Betroffene Komponenten & Dateien
`apps/agent/cmd/adminhelper-agent/main.go` (`readTerminal`, `readStdinSecret`), `provision_cmd_test.go`,
`apps/agent/go.mod`, `apps/agent/go.sum`, `docs/developer/agent.html` und `docs/en/developer/agent.html` (Baum zeigt
„go.mod Go 1.25“), `DEVELOPMENT.md` (Abschnitt „Go Toolchain (Agent)“), `changelog.d/kern-agent-3.md`.

## Datenmodell / API / Migrationen
Keine. Kein Wire-Format, keine Vertrags-Drift.

## Externe Integrationen
`golang.org/x/term`: `GetState`/`Restore` (https://pkg.go.dev/golang.org/x/term), `os/signal.Notify` mit
`os.Interrupt` (unter Windows Ctrl-C an der Konsole, https://pkg.go.dev/os/signal#hdr-Windows).

## Trade-offs & Alternativen
- Vor dem Lesen `term.GetState(fd)`, Interrupt per `signal.Notify` abfangen, im Signalfall `term.Restore` und
  `os.Exit(130)`; nach dem Lesen `signal.Stop`. Das Abfangen gilt nur für die Dauer der Eingabe. **Empfehlung.**
- Alternative: Eigenes Raw-Mode-Lesen ohne `ReadPassword` — mehr Code, gleiche Wirkung.
- Testbarkeit: Signalkanal, Restore und Exit als austauschbare Variablen wie `readTerminal`, damit der Test ohne
  echtes Signal und ohne TTY läuft.

## Risiken & Rollback
Gering: der Pfad greift nur auf einem Terminal. Rollback per Revert der Task. Go 1.27 als Mindestversion: wer lokal
mit älterem Go baut, lädt per `GOTOOLCHAIN=auto` 1.27.3 nach (geprüft auf der Dev-Box mit 1.26.9).

## Doku-Impact
`docs/developer/agent.html` DE+EN (Go-Version im Baum), `DEVELOPMENT.md` (go.mod-Mindestversion), CHANGELOG über
`changelog.d/kern-agent-3.md`.

## Offene Fragen
Keine.
