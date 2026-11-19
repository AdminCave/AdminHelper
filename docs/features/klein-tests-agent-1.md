<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-agent-1

## Problem / Motivation
R-1625: `TestGuardChecksTheOwnersOfThePortAfterTheConnect/a_user_holds_it_on_a_host_that_tells_no_taker`
(`apps/agent/internal/probe/guard_test.go`) schlug auf `windows-latest` mit „the listener took no connection“ nach
30 s fehl (main-CI Lauf 44467133925); der Merge-Diff berührte `internal/probe` nicht. Der Test wartet auch bei einem
vom Guard abgewiesenen Dial (`want == false`) darauf, dass der Listener die Verbindung annimmt. Der Guard schließt
sie sofort; Go-`Accept` überspringt eine vor dem Accept zurückgesetzte Verbindung auf FreeBSD (`ECONNABORTED`), der
Test nimmt dort schon die Ausnahme. Dasselbe Zurücksetzen vor dem Accept ist auf Windows möglich (nicht
verifiziert: kein Windows-Host im Pool).

## Ziel & Nicht-Ziele
Ziel: bei einem abgewiesenen Dial wartet der Test auf Windows wie auf FreeBSD nicht auf den Accept; `ownersCalls`
belegt dort das Urteil nach dem Connect. Nicht-Ziele: Produktivcode, größere Frist (`testing.md`: 30 s sind schon die
Obergrenze), weitere Tests.

## Betroffene Komponenten & Dateien
`apps/agent/internal/probe/guard_test.go` (nur Test).

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
Die Ausnahme auf `windows` erweitern (Empfehlung, kleinste Änderung, derselbe Mechanismus wie FreeBSD) oder den
Accept-Goroutine-Abbruch bei Fehler im Helfer `takenBy` ändern (trifft alle Nutzer des Helfers).

## Risiken & Rollback
Nur Testcode; Revert. Der Dauerlauf 50/50 gilt auf der betroffenen Plattform (Windows): nicht lokal fahrbar, im
Commit-Body „nicht verifiziert“; Linux-Lauf 50/50 belegt nur, dass nichts bricht. Die PR-CI fährt windows-latest.

## Doku-Impact
Keiner (Tests).

## Offene Fragen
Keine.
