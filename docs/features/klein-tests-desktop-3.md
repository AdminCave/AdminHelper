<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-3

## Problem / Motivation
R-1197: In `scripts/tests/desktop_e2e_connect.sh` (Wächter für die RDP-Marken, `session`) pipt
`docker exec … cat /var/log/xrdp.log | grep -Eq …` unter `set -o pipefail`. `grep -q` beendet sich beim ersten Treffer,
`cat` bekommt SIGPIPE, die Pipeline meldet Exit ≠ 0 und die Marke `session` kommt verspätet oder nie (nur falsch-rot im
Live-Lauf). Zeile 234–236 desselben Skripts fasst das Log schon erst in eine Variable.

## Ziel & Nicht-Ziele
Ziel: der Wächter liest das Log in eine Variable und prüft diese. Nicht-Ziel: weitere Pipes im Skript (`wait_rdp_log`
hat dasselbe Muster, ist aber nicht Teil der Zeile; als eigene Roadmap-Zeile zu melden). R-1135 (wdio
`strictSelectors`) fährt nicht mit: es braucht einen GUI-Lauf auf der Desktop-Box, den Kevin vorher abstimmt; die Zeile
wandert in `tasks/klein-tests-desktop-5.md`.

## Betroffene Komponenten & Dateien
`scripts/tests/desktop_e2e_connect.sh`.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
Variable fassen (wie im Skript schon üblich) statt `pipefail` lokal abzuschalten. Empfehlung: Variable.

## Risiken & Rollback
Der Live-Lauf (`desktop_e2e_connect.sh`) braucht Docker und eine Desktop-Box; hier belegt `shellcheck`/`bash -n` nur die
Syntax. Das Verhalten (Marke kommt) bleibt bis zum nächsten Heavy-Lauf nicht verifiziert. Rollback: Revert.

## Doku-Impact
Keine (Testskript).

## Offene Fragen
Keine.
