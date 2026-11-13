<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-freebsd-5: FreeBSD-Proben auf eigene Adressen, root-Tests im Box-Lauf

Roadmap: R-1411 (BUG), R-1412 (REF).

## Problem / Motivation
- **R-1411:** Der Proben-Wächter liest unter FreeBSD die lauschenden TCP-Sockets aus `sockstat -46 -l -n -q -w -P tcp`
  (`apps/agent/internal/probe/sockstat.go`, `parseSockstat`). `-l` listet auch Sockets ohne Gegenstelle, darunter
  ungebundene (`tcp4 *:* *:*`), etwa die eigene Dial-Socket des Wächters während `Control`. `sockstatListener`
  verlangt einen numerischen Port und verwirft damit die ganze Ausgabe; jede Probe auf eine eigene Adresse
  scheitert. Beweis: kern-freebsd-3 Box-Lauf 2026-11-12, main@c702ea485, `TestHTTPClient*` und
  `TestGuardDropsAConnectionAnotherSocketTook` rot mit `sockstat printed a line of unknown form: tcp4 *:* *:*`.
- **R-1412:** Die root-Tests von `internal/probe` aus kern-freebsd-3 (getcred, pf-rdr) laufen in keiner Automatik;
  `box_freebsdbox.sh roottests` fährt nur die root-Tests von `internal/monitor`.

## Ziel & Nicht-Ziele
- Ziel: eine Zeile ohne Port (`*`) ist keine lauschende Socket und wird übersprungen; jede andere unbekannte Form
  verwirft die Ausgabe weiter (der Wächter urteilt nie auf einer Teilliste).
- Ziel: Phase `roottests` fährt auch die root-Tests von `internal/probe`, den pf-Test nur auf der reinen
  FreeBSD-Box (`freebsd_box.sh`), nie auf der OPNsense-Box (er leert pf).
- Nicht-Ziel: gebundene, nicht lauschende Sockets aussortieren (sockstat zeigt sie wie Listener; heutiges Verhalten).

## Betroffene Komponenten & Dateien
- agent: `apps/agent/internal/probe/sockstat.go`, `apps/agent/internal/probe/sockstat_test.go`.
- scripts (Harness, Kevins Wort 2026-11-13): `scripts/tests/box_freebsdbox.sh`, `scripts/tests/freebsd_box.sh`.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
sockstat(1) im FreeBSD-Basissystem (`-l`: Sockets ohne Gegenstelle, auch ungebundene).

## Trade-offs & Alternativen
- Ungebundene Zeilen überspringen (gewählt) statt `-l` durch eine eigene Zustandsprüfung zu ersetzen: kleinste
  Änderung, die strikte Ablehnung jeder anderen Form bleibt.
- pf-Test über `AH_FREEBSD_PF=1` aus `freebsd_box.sh` (sudo mit `env`) statt immer: die OPNsense-Box fährt dieselbe
  Phase, und ihr pf ist die Firewall.

## Risiken & Rollback
Ein übersprungener Port `*` kann keinen Listener verbergen (ohne Port lauscht nichts). Rollback: Revert des Merges.

## Doku-Impact
Keine Seite beschreibt das Parsen; Changelog-Fragment unter `### Fixed`.

## Offene Fragen
Keine.
