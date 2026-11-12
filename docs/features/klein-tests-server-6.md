<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-server-6 — Spec

## Problem
- **R-1308:** `test_an_input_that_turns_unreadable_is_rejected_and_logged_once` in
  `apps/server/tests/test_frps_supervisor.py` (Z. 1191) scheiterte in der CI (Lauf 42985691597, Shard 2/2) mit
  `not running within 10.0s`: Nach `chmod 0600` wartet der Test mit `box.wait_state("running")` (Z. 1212) nur
  `WAIT = 10` s. Der Supervisor übernimmt den wieder lesbaren Input erst, wenn er unverändert bleibt; das Log endete
  bei `input changed, taking it over once it stays the same`. Auf einem langsamen Runner reicht die kurze Frist nicht.

## Ziel / Nicht-Ziele
Der Test wartet auf die Bedingung mit einer Obergrenze von 30 s (`3 * WAIT`, wie die Nachbartests), die Abfrage bleibt
kurz getaktet (`testing.md`, Fristen). Gleiches für das `degraded`-Warten derselben Übernahme (Z. 1197). Kein
Produktcode, kein anderer Test, `WAIT` bleibt.

## Dateien
`apps/server/tests/test_frps_supervisor.py`.

## Datenmodell / API / Integrationen
Keine.

## Trade-offs
Ein globales `WAIT = 30` würde alle Tests der Datei betreffen; die Ursache ist hier belegt, also nur dieser Test.

## Risiken & Rollback
Ein grüner Dauerlauf (50 Läufe, `testing.md` Wackler) belegt den Fix; ein Commit, rückgängig per Revert.

## Doku-Impact
Keine.

## Offene Fragen
Keine.
