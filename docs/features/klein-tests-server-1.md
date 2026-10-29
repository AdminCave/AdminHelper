<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-server-1 — Server-Test-Lücken

Roadmap R-0925, R-0889, R-0892. R-0852 (`test_mtls_scope.py` Timeout) fährt nicht mit: `feature/fehlervertrag` ändert
dieselbe Datei; die Zeile wandert in `klein-tests-server-2`.

## Problem / Motivation
- **R-0925:** `test_route_auth_gate._dependency_qualnames` liest nur den `dependant` der Route. Seit FastAPI >= 0.138
  liegen die Abhängigkeiten aus `include_router(..., dependencies=...)` in `_IncludedRouter.include_context`; ein Guard
  allein am Include fällt dem Gate nicht auf (ein Router ohne eigenen Guard gälte als offen oder, umgekehrt, die
  Prüfung bliebe blind). `test_stream.py` hat das Muster schon als `_include_dependency_qualnames`.
- **R-0889:** Der Zweig „Refresh-Token ohne jti/exp" (`blacklist_token` liefert False → Reuse) in
  `users/auth_router.py` hat keinen eigenen Test.
- **R-0892:** Drei Lücken der Hooks/CLI-Tests: das Flag `-s` des Hook-Workers ist nicht getrennt von
  `PYTHONNOUSERSITE` prüfbar; die Zeitgrenzen pinnen die gemeinsame Reader-Deadline nicht;
  `create-admin --password X --password-stdin` zusammen startet nicht neu, `X` bleibt in argv.

## Ziel & Nicht-Ziele
- Ziel: je Lücke ein Test, der fallen kann (Gegenprobe); bei R-0892 lehnt die CLI beide Flags zusammen ab
  (`parser.error`).
- Nicht-Ziel: weitere Umbauten der Hook-Runner- oder Auth-Logik.

## Betroffene Komponenten & Dateien
`apps/server/tests/test_route_auth_gate.py`, `test_stream.py`, `test_auth_token_lifecycle.py`,
`test_hook_isolation.py`, `test_cli.py`, `apps/server/app/cli.py`.

## Datenmodell / API / Migrationen
Keine. Einzige Verhaltensänderung: `create-admin` und `reset-admin` weisen `--password` zusammen mit
`--password-stdin` mit Exit 2 und einer Meldung ab (bisher bei `create-admin`: `--password` ohne Neustart).

## Externe Integrationen
Keine (FastAPI-Interna nur in Tests, Muster aus `test_stream.py`).

## Trade-offs & Alternativen
Der Include-Walk zieht in `test_route_auth_gate.py` um und `test_stream.py` importiert ihn (eine Quelle statt
zwei). Alternative: Duplikat belassen, verworfen.

## Risiken & Rollback
Nur Tests plus eine kleine Argument-Prüfung; jede Task einzeln zurücknehmbar.

## Doku-Impact
`README.md` und `docs/admin/troubleshooting.html` (DE+EN) nennen `--password-stdin`; falls sie die Kombination
beschreiben, nachziehen, sonst keine. Fragment `changelog.d/klein-tests-server-1.md`.

## Offene Fragen
Keine. Die Ablehnung der Flag-Kombination steht in der Titelzeile von R-0892 (von Kevin angenommen).
