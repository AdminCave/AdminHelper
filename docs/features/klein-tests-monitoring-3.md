<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-monitoring-3 — Spec

## Problem
- **R-1146:** In `apps/monitoring/tests/test_check_engine_concurrency.py` (parametrize von
  `test_bell_failed_post_without_a_newer_dispatch_changes_nothing`, Z. 399–408) heißt der zweite Fall
  `alarm-after-cooldown`. Den Glocken-Cooldown gibt es seit R-1079 nicht mehr: `hub_sent_at` entscheidet nichts mehr.
  Der Fall prüft einen Alarm, dessen Glocken-Zeile vorher `ok` zeigte (`("ok", 11:00)`, eine Stunde vor `_BELL_NOW`).

## Ziel / Nicht-Ziele
Die ID nennt, was der Fall prüft: `alarm-after-ok-record`. Parameter und Verhalten bleiben gleich; kein anderer Test
ändert sich. Die ID kommt nirgends sonst vor (gegrept in `apps`, `scripts`, `docs`, `tasks`).

## Dateien
`apps/monitoring/tests/test_check_engine_concurrency.py`.

## Datenmodell / API / Integrationen
Keine.

## Trade-offs
Keine. Kein Changelog-Fragment (nur eine Test-ID).

## Risiken & Rollback
Keine; ein Commit.

## Doku-Impact
Keine.

## Offene Fragen
Keine.
