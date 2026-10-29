<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Betriebsskripte: Admin-Passwort in install.sh, Hilfe von agent-install.sh

Zug `ops-1` (Roadmap R-0858, R-0864). Stand des Codes: `origin/main@5cd3f8f3`. Die Zeilen R-0859, R-0862, R-0865
und R-0896 aus diesem Zug ändern Dateien offener Branches (`scripts/update.sh`, `docs/admin/installation.html`) und
fahren im Zug `ops-3`.

## Problem / Motivation

1. **Admin-Passwort in install.sh (R-0858).** `scripts/install.sh:53` setzt `ADMIN_PASSWORD=""`. Ist die Variable
   in der aufrufenden Shell exportiert, behält sie das Export-Attribut; der Wert aus `--admin-password`,
   `--admin-password-file` oder der Eingabe geht dann an jeden Kindprozess des Skripts. Einzelheiten privat.
2. **Hilfe von agent-install.sh (R-0864, BUG).** `-h` druckt mit `sed -n '6,44p'` (`scripts/agent-install.sh:124`)
   den Kopfkommentar und dazu die Zeile `set -euo pipefail`.

## Ziel & Nicht-Ziele

Ziel: das Passwort bleibt eine Shell-Variable des Skripts; `-h` druckt nur den Kopfkommentar. Nicht-Ziele: andere
Optionen, `update.sh`, Doku-Änderungen.

## Betroffene Komponenten & Dateien

`scripts`: `scripts/install.sh`, `scripts/agent-install.sh`, `scripts/tests/install_test.sh`,
`scripts/tests/agent_install_test.sh`.

## Datenmodell / API / Migrationen

Keine.

## Externe Integrationen

Keine. `export -n` ist ein bash-Builtin (bash-Handbuch, „Bourne Shell Builtins“).

## Trade-offs & Alternativen

- R-0858: `export -n ADMIN_PASSWORD` direkt bei der Initialisierung; das Passwort geht schon heute über stdin an
  `create-admin` (`install.sh:341`) und braucht keinen Export. Alternative `unset` nach Gebrauch: verworfen, der
  Wert lebt bis zum Ende des Skripts in derselben Shell, das Export-Attribut ist das Problem.
- R-0864: die Hilfe endet an der ersten Leerzeile nach dem Kommentar (`sed -n '6,/^$/p'`) statt an einer festen
  Zeilennummer, die beim nächsten Kommentar-Edit wieder verrutscht.

## Risiken & Rollback

Je Task ein Commit, einzeln zurücknehmbar. Der PR ändert `scripts/install.sh` und `scripts/agent-install.sh`: Kevin
merged (CLAUDE.md §2).

## Doku-Impact

Keine: das dokumentierte Verhalten ändert sich nicht.

## Offene Fragen

Keine.
