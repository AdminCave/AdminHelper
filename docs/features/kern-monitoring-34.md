<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: Verschachtelungstiefe in Request-Bodies begrenzen (kern-monitoring-34)

Roadmap: R-1455 · Ledger: `tasks/kern-monitoring-34.md`

## Problem / Motivation

- **R-1455:** Freie JSON-Felder der Monitoring-API (`config`, `channel_config` in `apps/monitoring/app/schemas.py`) und
  der Agent-Report nehmen Werte beliebiger Verschachtelungstiefe an. Die Prüfung `find_unstorable`
  (`apps/monitoring/app/core/bounds.py:91`) läuft schon über jeden Wert, kennt aber keine Tiefe. Einzelheiten privat.

## Ziel & Nicht-Ziele

Ziel:
- `find_unstorable` weist einen Wert ab, der tiefer als eine feste Grenze verschachtelt ist (`MAX_DEPTH = 32`,
  gezählt ab dem Body). Die Abweisung ist ein `422` wie bei NUL und Surrogat, mit der Stelle als `loc`; als `input`
  trägt sie nicht den verschachtelten Wert, sondern `null`.
- Das gilt für jedes Schema auf `RequestModel` und für den Agent-Report (`_refuse_unstorable_report`,
  `apps/monitoring/app/routers/agent.py:223`); die Liveness zählt dort weiter wie bei NUL.

Nicht-Ziele: keine Migration und kein Umschreiben gespeicherter Zeilen; die Kopie von `bounds.py` im Server
(`apps/server/app/core/bounds.py`) bleibt, wie sie ist (eigene Zeile, falls nötig); keine Grenze im JSON-Parser selbst.

## Betroffene Komponenten & Dateien

- Monitoring: `app/core/bounds.py`, `app/routers/agent.py`, neuer Test `tests/test_depth.py`.

## Datenmodell / API / Migrationen

Keine Migration. API: ein Body, der tiefer als 32 Ebenen verschachtelt, ist `422` statt angenommen. Das OpenAPI-Schema
ändert sich nicht (Validator vor den Feldern). Server, Web, Desktop und Agent senden keine so tiefen Werte: die
tiefsten heutigen Bodies (Agent-Report mit Check-Details) liegen unter zehn Ebenen.

## Externe Integrationen

Keine.

## Trade-offs & Alternativen

- **Grenze im Walk von `find_unstorable` (gewählt):** ein Ort für alle Request-Schemas und den Agent-Report, iterativ,
  ohne Rekursion.
- Grenze je Feld per Typ: müsste jedes freie `dict`-Feld einzeln tragen und vergisst neue Felder.
- Die Grenze 32: weit über jedem heutigen Body, weit unter dem, was Serialisierung und Antworten tragen.

## Risiken & Rollback

Ein legitimer Body tiefer als 32 Ebenen würde abgewiesen; es gibt keinen. Rollback: Revert des Task-Commits.

## Doku-Impact

`docs/developer/monitoring.html` und `docs/en/developer/monitoring.html` (Prüfung des Reports), API-Referenz DE+EN
(Abschnitt Fehler), `changelog.d/kern-monitoring-34.md`.

## Offene Fragen

Keine.
