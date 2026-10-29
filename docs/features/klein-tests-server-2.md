<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-server-2 — Server-Test: Timeout ohne Traceback

Roadmap R-0852. Nur Testcode, kein Produktivcode. `overlap.sh` ohne Treffer.

## Problem / Motivation
`apps/server/tests/test_mtls_scope.py` (`test_mtls_enforce_defaults_to_enforced_without_the_env`) startet einen
Unterprozess mit `timeout=60` und der kopierten Umgebung. Läuft er in den Timeout, zeigt pytest die Frames von
`subprocess.run`, und die tragen `env` (die ganze Umgebung der Session, auch Tokens). Die übrigen Subprozess-Tests
(`test_conftest_app_engine.py`, `test_conftest_event_teardown.py`, `test_conftest_db_password.py`) fangen
`TimeoutExpired` und rufen `pytest.fail(..., pytrace=False)`.

## Ziel & Nicht-Ziele
Derselbe Abfang in diesem Test. Nicht-Ziel: Timeouts ändern oder die Tests zusammenführen.

## Betroffene Komponenten & Dateien
`apps/server/tests/test_mtls_scope.py`.

## Risiken & Rollback
Test-only; Revert genügt. Der Pfad tritt nur im Fehlerfall ein, die Gegenprobe zeigt ihn mit einem kurzen Timeout.

## Doku-Impact
Keine (interner Test).

## Offene Fragen
Keine.
