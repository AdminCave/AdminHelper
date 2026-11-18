<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-13 — Nachlese kern-monitoring-42 und -43

Roadmap R-1530, R-1547. Nur Tests und ein Kommentar, kein Produktverhalten.

## Problem je Zeile
- **R-1530:** (a) `execx_unix_test.go` prueft mit einer 200-ms-Frist die Frist selbst, sagt das aber nicht in einem
  Kommentar (`.claude/rules/testing.md`, Fristen). (b) `TestAContainerOverItsBudgetIsAnErrorThatNamesNoPath` baut
  Dateien von je ca. 1,2 MiB: jede ueberschreitet schon `maxApacheFileBytes` (1 MiB), der Test trifft also die
  Dateigrenze statt des Container-Budgets `maxContainerConfBytes` (4 MiB).
- **R-1547:** `test_catalog_web.py` prueft das Binden der zentralen Checks von `web_domain` v2 nur ueber
  `central_config`, nie ueber `adopt()` mit dem echten Modul aus dem Katalog.

## Ziel und Nicht-Ziele
Der Budget-Test trifft das Budget (Dateien unter 1 MiB, Summe ueber 4 MiB); die Frist traegt ihren Kommentar; ein Test
uebernimmt `web_domain` ueber `adopt()` und prueft Check-Arten, Konfig und Plan. Nicht-Ziel: Produktcode aendern.

## Nicht in diesem Zug
R-1546, R-1549, R-1550, R-1551, R-1574, R-1590, R-1591, R-1593 fahren nicht mit: sie aendern Dateien, die
`feature/kern-monitoring-18` oder `-45` aendern (`overlap.sh`), oder betreffen Code, den `main` noch nicht hat. Sie
wandern nach `tasks/klein-nachlese-14.md`.

## Doku-Impact
Keine (Tests, ein Test-Kommentar).

## Risiken und Rollback
Gering; Revert. Der Budget-Test muss rot werden, wenn das Budget wegfaellt (Gegenprobe im Review).

## Offene Fragen
Keine.
