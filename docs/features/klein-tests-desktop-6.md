<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-6

## Problem / Motivation
R-1493: In `scripts/tests/desktop_e2e_connect.sh` pipen `wait_log` (Z. 40) und die Web-Prüfung (Z. 222)
`docker logs … | grep -q` unter `set -uo pipefail`. `grep -q` endet beim ersten Treffer, `docker logs` bekommt SIGPIPE,
die Pipeline meldet Exit ≠ 0 und der Treffer zählt nicht (falsch-rot, bei langen Logs). Dasselbe Muster wie R-1298/R-1197.
R-1135: `apps/desktop/e2e/wdio.conf.js:66` setzt `strictSelectors: false`, weil wdio 10 bei mehreren Treffern von `$`
wirft; welche Selektoren mehrdeutig sind, zeigt nur ein GUI-Lauf auf der Desktop-Box.

## Ziel & Nicht-Ziele
Ziel: die zwei Stellen fassen das Log erst in eine Variable (wie `wait_rdp_log`); kein pipefail-Abschalten.
Nicht-Ziele: R-1135 wird erst nach Kevins Abstimmung des Box-Laufs gebaut (`[?]`-Task). Dieselben `wait_log`-Zeilen in
`desktop_e2e_connect_tunnel.sh:40` und `desktop_e2e_workspaces.sh:61` gehören nicht zu R-1493; sie werden als eigene
Roadmap-Zeile gemeldet.

## Betroffene Komponenten & Dateien
`scripts/tests/desktop_e2e_connect.sh`; für R-1135 `apps/desktop/e2e/wdio.conf.js`, Specs unter `apps/desktop/e2e/test/specs/`.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
wdio 10 `strictSelectors` (Verhalten laut R-1135-Beleg kern-deps-3 T3).

## Trade-offs & Alternativen
Variable fassen statt `pipefail` lokal abzuschalten (Skript-Konvention). Empfehlung: Variable.

## Risiken & Rollback
Live-Verhalten braucht Docker und Desktop-Box, bis zum nächsten Heavy-Lauf nicht verifiziert; lokal Gegenprobe der
SIGPIPE-Semantik. Rollback: Revert.

## Doku-Impact
Keine (Testskripte).

## Offene Fragen
R-1135: Box-Lauf (warm.env desktop, zuletzt von Lane kern-rdp-7 belegt) mit Kevin abstimmen. Empfehlung: Lauf, wenn die Box frei ist.
