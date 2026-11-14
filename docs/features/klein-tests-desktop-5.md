<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-5

## Problem / Motivation
R-1298: In `scripts/tests/desktop_e2e_connect.sh` pipt `wait_rdp_log` (`docker exec … sh -c 'cat …' | grep -qiE …`)
unter `set -uo pipefail`. `grep -q` endet beim ersten Treffer, `cat` bekommt SIGPIPE, die Pipeline meldet Exit ≠ 0 und
der Treffer zählt nicht, so dass `wait_rdp_log` bis zum Timeout wartet (falsch-rot im Live-Lauf). Dasselbe Muster wie
R-1197, dort für den Marken-Wächter behoben.

## Ziel & Nicht-Ziele
Ziel: `wait_rdp_log` fasst die Logs erst in eine Variable und prüft diese; kein lokales Abschalten von pipefail.
Nicht-Ziele: weitere Funktionen des Skripts. R-1135 (wdio `strictSelectors`) fährt nicht mit: es braucht einen GUI-Lauf
auf der Desktop-Box, den Kevin vorher abstimmt (Frage am Gate); die Zeile wandert in `tasks/klein-tests-desktop-6.md`.

## Betroffene Komponenten & Dateien
`scripts/tests/desktop_e2e_connect.sh`.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
Variable fassen (wie im Skript schon üblich) statt `pipefail` lokal abzuschalten. Empfehlung: Variable.

## Risiken & Rollback
Der Live-Lauf braucht Docker und eine Desktop-Box; lokal belegt nur `bash -n`/shellcheck die Syntax, die SIGPIPE-Semantik
lässt sich lokal mit einer Gegenprobe zeigen. Das Verhalten im Live-Lauf bleibt bis zum nächsten Heavy-Lauf nicht
verifiziert. Rollback: Revert.

## Doku-Impact
Keine (Testskript).

## Offene Fragen
R-1135: Box-Lauf mit Kevin abstimmen (siehe Ledger-Bericht).
