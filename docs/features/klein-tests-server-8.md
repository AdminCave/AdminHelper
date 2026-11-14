<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-server-8

## Problem / Motivation
R-1416: `test_ip_filter.py::TestTrustedProxyNameThread::test_an_unexpected_error_drops_the_last_addresses` patcht
`mw.time.sleep`; `mw.time` ist das globale `time`-Modul, also gilt der Patch für alle Threads. Ein fremder Thread
(etwa der Namens-Thread eines anderen Resolvers) ruft das Fake-`sleep` und schreibt einen Eintrag in `seen`
(CI: `[gw, [], []]` statt `[gw, [], gw]`). Dasselbe Risiko trägt der Nachbartest
`test_an_unexpected_error_clears_before_a_round_out_of_turn_publishes` (das Fake wirft `_Stop` in einem fremden Thread).

R-1417: `test_hook_isolation.py::test_hook_reader_grace_is_one_deadline_for_both_streams` misst `held - plain` und
verlangt `0.8 * grace <= extra`. Unter Host-Last streut die Differenz zweier Minima aus je drei Läufen um mehr als die
0,2 s Abstand (CI: 0,7 s bei grace 1,0), obwohl das Verhalten stimmt.

## Ziel & Nicht-Ziele
Ziel: (1) das Fake-`sleep` wirkt nur im Thread des Tests, andere Threads schlafen echt; (2) die Untergrenze des
Grace-Tests liegt so weit unter `grace`, dass Last sie nicht reißt, die Obergrenze (`1.6 * grace`, trennt „eine Frist“
von „zwei Fristen“) bleibt. Nicht-Ziele: Produktivcode, größeres Timeout, weitere Tests.

## Betroffene Komponenten & Dateien
`apps/server/tests/test_ip_filter.py`, `apps/server/tests/test_hook_isolation.py` (nur Tests).

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
R-1416: `sleep` im Produktcode injizierbar machen (mehr Oberfläche für einen Testfehler) oder Fake nur im eigenen
Thread zählen (Testcode). Empfehlung: Testcode. R-1417: mehr Läufe je Messung (kostet je 1 s) oder Untergrenze senken.
Empfehlung: Untergrenze `0.5 * grace`; ein Fehler, bei dem die Frist gar nicht gewartet wird, liegt weiter bei ≈ 0.

## Risiken & Rollback
Nur Testcode; Rollback: Revert. Beleg je Fix: Dauerlauf 50/50 (`.claude/rules/testing.md`), für R-1416 dazu eine
Gegenprobe mit einem Fremd-Thread, der `time.sleep` hämmert (alt rot, neu grün).

## Doku-Impact
Keine (Tests).

## Offene Fragen
Keine.
