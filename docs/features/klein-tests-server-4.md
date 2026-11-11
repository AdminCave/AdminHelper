<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-server-4

## Problem / Motivation
R-1293: In der CI (PR #453, Lauf 42859714863, py3.15 Shard 2/2) schlug
`test_while_frps_runs_every_poll_puts_the_answers_of_its_dashboard_into_the_state` mit "not the proxy lists within
10.0s" fehl. Das Supervisor-Log zeigte nur "frps started" und "state running"; ob das Dashboard je einen Request sah,
steht nirgends. Kevin verlangt die Ursache, nicht nur ein größeres Timeout.

Befund beim Planen (2026-11-11, lokal, Probe-Worktree): ungestört liegen die ersten Listen nach 1,7 s da (Budget 10 s),
der ganze Test braucht 4,2 s (zwei weitere Heartbeats bei 1 s Intervall). Unter 24 Rechenschleifen auf 8 Kernen blieb er
bei 4,2 bis 6,1 s (8 Läufe grün); die ganze Datei lief unter derselben Last mit `--cov=app` zweimal grün (161 passed).
Das Timeout ist lokal **nicht reproduzierbar**; `Dashboard._scan()` (liest `/proc` je Request) kostet mit 400 Prozessen
25 ms und scheidet aus.

## Ziel & Nicht-Ziele
Ziel: Der nächste Fehlschlag zeigt seine Ursache: die Meldung nennt die Requests, die das Dashboard sah, und die Listen,
die im State-Verzeichnis lagen. Kein höheres `WAIT`, keine Änderung am Supervisor. Nicht-Ziel: eine Ursache behaupten,
die nicht belegt ist.

## Betroffene Komponenten & Dateien
`apps/server/tests/test_frps_supervisor.py` (`_with_dashboard`).

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
- Diagnose in der Fehlermeldung (Empfehlung): kostet nichts im grünen Fall und trennt "Dashboard sah nie einen Request"
  (Supervisor/curl) von "Requests kamen, Antworten scheiterten" (Stub/Listen).
- Timeout anheben: verdeckt die Ursache.
- Supervisor um Log-Zeilen bei fehlgeschlagenen Requests erweitern: Produktänderung, nicht Sache dieses Zugs.

## Risiken & Rollback
Reine Teständerung; Rollback: Revert.

## Doku-Impact
Keine (Tests).

## Offene Fragen
Keine. Die Zeile R-1293 bleibt nach dem Merge als offene Ursache bestehen (neue Zeile `neu`), bis ein Fehlschlag die
Diagnose liefert.
