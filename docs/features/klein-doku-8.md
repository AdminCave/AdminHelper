<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-doku-8 — Spec

## Problem
- **R-1282** (Nit aus kern-server-8): Der Monitoring-Dienst lehnt einen Query-Parameter, den das Schema als Einzelwert
  deklariert, bei mehrfacher Angabe mit `422` ab (R-1131, `apps/monitoring/app/core/query_params.py`, App-weite
  Abhängigkeit `reject_repeated_scalar_query` in `main.py`). `docs/developer/api-reference.html` (DE+EN) sagt das seit
  kern-server-8; `docs/developer/monitoring.html` (DE+EN) nennt es nicht.

## Ziel / Nicht-Ziele
Ein Satz in `monitoring.html` (DE+EN) nach dem Modulbaum, in der Form des Satzes aus `api-reference.html`:
`?offset=1&offset=2` ergibt `422` mit `loc` `["query", <name>]` und den Werten als Liste in `input`; ein unbekannter
Parameter wird weiter ignoriert; Array-Parameter bleiben. Keine Code-Änderung.

## Dateien
`docs/developer/monitoring.html`, `docs/en/developer/monitoring.html`.

## Datenmodell / API / Migrationen
Keine.

## Doku-Impact
Die Änderung ist die Doku.

## Risiken & Rollback
Keine; reiner Text.

## Offene Fragen
Keine.
