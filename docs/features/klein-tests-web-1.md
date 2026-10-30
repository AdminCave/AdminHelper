<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-web-1 — Web: zwei Test-Lücken in der Anmeldung

Roadmap R-0888, R-0891. Beide ergänzen Tests im Web-Frontend, kein Produktivcode ändert sich. `overlap.sh` ohne Treffer.

## Problem / Motivation
- **R-0888:** `apps/web/src/App.idle.test.ts:110` (Fall „idle_timeout_minutes 0 never signs out“) lässt nur 10 Minuten
  vergehen. Ein Rückfall auf `|| 30` in der Auswertung des Werts bliebe grün, weil 30 Minuten nicht erreicht werden.
  Soll: 31 Minuten plus ein Prüfintervall.
- **R-0891:** (a) Kein Test deckt einen scheiternden Logout unter der Web Lock (`apps/web/src/lib/api/client.crosstab.test.ts`,
  Abschnitt `logout across tabs`): die Sperre muss danach frei sein und das lokale Token fort. (b) Kein Test pinnt, dass
  ein Aufruf eines `/auth/`-Pfads nie refresht (`lib/api/auth.ts:21`, `client.ts:142`); davon hängt die
  Deadlock-Freiheit des Logouts unter der Sperre ab.

## Ziel & Nicht-Ziele
Tests, kein Produktivcode. Nicht-Ziel: das Verhalten der Sperre ändern.

## Betroffene Komponenten & Dateien
`apps/web/src/App.idle.test.ts` (T1); `apps/web/src/lib/api/client.crosstab.test.ts` (T2).

## Trade-offs
Die neuen Fälle nutzen die vorhandenen Stubs (`stubAuthServer`, `installLockManager`), keine neuen Hilfen.

## Risiken & Rollback
Test-only; Rollback: Revert. Ein Fall, der rot wird, zeigt einen echten Fehler und wird zur Roadmap-Zeile.

## Doku-Impact
Keine (interne Tests).

## Offene Fragen
Keine.
