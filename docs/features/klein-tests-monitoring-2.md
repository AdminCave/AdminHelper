<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-monitoring-2 — Testluecken Monitoring und Server-Antwortform (R-0966, R-0977)

## Problem
- R-0966: `apps/monitoring/tests/test_checker_messages.py` fuehrt je Meldungspfad einen Fall (R-0422), kennt aber zwei
  HTTP-Meldungen nicht: „Redirect without Location header“ (`checkers/http.py`, Redirect ohne `location`) und
  „Too many content encodings (>5)“ (`DecodingError` in `checkers/http.py`).
- R-0977: Die Antwortform-Tests lassen Luecken: `test_metrics_pass_the_series_through` prueft `data` nur als nicht leer
  statt gegen die durchgereichte Serie; es fehlt eine duenne Check-/Zustandszeile (State-Zeile mit NULL-Feldern);
  `POST /checks/{id}/run` wird nicht ueber die Route gegen den Produzenten geprueft; die interne Serverliste
  (`/api/internal/servers`) ist nur fuer einen Server mit Tags belegt, nicht fuer einen ohne.

## Ziel & Nicht-Ziele
Nur Tests; kein Produktcode. Entdeckt ein neuer Test ein falsches Verhalten, wird daraus eine Roadmap-Zeile.

## Betroffene Dateien
`apps/monitoring/tests/test_checker_messages.py`, `apps/monitoring/tests/test_response_shapes.py`,
`apps/server/tests/test_response_shapes.py`.

## Datenmodell / API / Externes
Keine Aenderung.

## Trade-offs
Je Komponente eine Task (ein `Verify:`); Review am Ende (3 Tasks, nur Tests).

## Risiken & Rollback
Reine Tests; Revert des Task-Commits.

## Doku-Impact
Keine.

## Offene Fragen
Keine.
