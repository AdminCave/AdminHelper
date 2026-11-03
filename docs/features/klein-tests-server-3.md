<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-server-3 — Spec

Zug der Klein-Session (Roadmap R-1084).

## Problem
R-1084: `test_hook_reader_grace_is_one_deadline_for_both_streams` (`apps/server/tests/test_hook_isolation.py`) misst
`extra = held - plain` aus je einem einzigen Lauf. Unter Host-Last (~20–30) schwankt der Worker-Start je Lauf um mehr
als die Toleranz; `extra` fiel auf 0.794 s gegen die Untergrenze 0.8·grace. Die Aussage des Tests (zwei Reader teilen
eine Grace, nicht zwei) bleibt richtig, die Messung ist zu empfindlich.

## Ziel
Die Messung nimmt je Variante das Minimum mehrerer Läufe (Last verlängert, verkürzt nie): ein Lauf, der die Grace
tatsächlich überspringt oder verdoppelt, fällt weiterhin durch. Nicht-Ziel: Produktcode, Grenzen aufweichen.

## Doku-Impact
Keine (Test-Interna).

## Risiken
Etwa 4 s längere Laufzeit des Tests. Rollback: Revert.
