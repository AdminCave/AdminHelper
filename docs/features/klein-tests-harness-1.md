<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-harness-1 — Spec

## Problem (R-1005)
`scripts/dev/tests/test_lock_pins.py::test_the_running_environment_is_read_by_default` startet `lock-pins.py` zweimal
ohne `--freeze`; das Skript liest dann die ganze Umgebung über `importlib.metadata` (`read_environment`). Das
Hilfsprogramm `run()` setzt für jeden Subprozess `timeout=30`. Unter Last (Beleg: `task-close` von
`klein-tests-stack-2` T2, erster Lauf rot durch Timeout, zweiter grün bei Last ~8) reicht das nicht. Die Titelangabe
„pip freeze“ stimmt nicht: das Skript ruft kein `pip freeze` auf, sondern liest die Metadaten selbst.

## Ziel / Nicht-Ziele
Ziel: der Test ist unter Last stabil. Nicht-Ziel: `lock-pins.py` ändern oder den Test abschwächen (beide Assertions
bleiben).

## Dateien
`scripts/dev/tests/test_lock_pins.py` (Timeout von `run()` als Parameter, der Default-Umgebungs-Test setzt einen
großzügigen Wert).

## Datenmodell / API / Integrationen
Keine.

## Trade-offs
Ein globaler höherer Timeout würde auch echte Hänger der übrigen Tests verdecken; deshalb nur für den Test, der die
ganze Umgebung liest. Alternative (Umgebung im Test mocken) würde genau den Pfad nicht mehr prüfen, den der Test
beweisen soll.

## Risiken & Rollback
Gering; reine Teständerung, ein Commit zurücknehmbar.

## Doku-Impact
Keine.

## Offene Fragen
Keine.
