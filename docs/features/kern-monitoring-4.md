<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-4 — Verlauf bis jetzt, Routen-Kollision, Live-E2E

Zug `tasks/kern-monitoring-4.md` mit R-1104, R-1107 und R-1103. R-1105 (Netzwerk im Verlauf) fährt nicht mit: es
ändert `apps/desktop/ui/src/lib/i18n/dictionaries.ts`, die auch der offene Branch `feature/kern-verbindungen-1`
ändert; die Zeile steht jetzt im Zug `tasks/kern-monitoring-5.md`.

## Problem / Motivation

- **R-1104 (BUG):** `history_window` (`apps/monitoring/app/history.py:59`) setzt `end` auf den letzten vollen
  Rasterschritt (`int(now) // step * step`). Der Verlauf zeigt die neuesten Daten deshalb erst, wenn der nächste
  Schritt voll ist: bis zu 1 min bei 1 Std., 15 min bei 24 Std., 1 h bei 7 Tagen, 6 h bei 30 Tagen. Betroffen sind
  `GET /status/server/{server_id}/history` (`apps/monitoring/app/routers/checks.py:599`) und `GET /status/compare`
  (`checks.py:646`).
- **R-1107 (BUG):** `GET /templates/assignments/{server_id}` (`apps/monitoring/app/routers/templates.py:152`) ist
  vor `GET /templates/{template_id}/builtin-update` (`templates.py:369`) registriert. Ein Aufruf mit
  `template_id=assignments` landet deshalb bei `get_server_assignments` und antwortet `[]` statt eines
  `BuiltinUpdateOut` oder 404. Der Wochenlauf vom 2026-11-02 (schemathesis) hat das gezeigt. Dieselbe Form hat
  `GET /templates/suggestions/{server_id}` (`templates.py:339`) mit `template_id=suggestions`.
- **R-1103 (FEAT):** Die Desktop-Live-E2E `apps/desktop/e2e/test/specs/monitoring-check.live.js` deckt den Verlauf
  und den Server-Vergleich aus kern-monitoring-3 nicht ab. T11 dort wurde verworfen: die Wartefunktion prüfte nach
  dem Neuladen, und `load()` leert die Anzeige sofort.

## Ziel & Nicht-Ziele

- Ziel: Der Verlauf und der Vergleich enden am ersten Rasterpunkt ab jetzt. Das Raster bleibt ausgerichtet, die
  Punktzahl bleibt gleich.
- Ziel: `GET /templates/{template_id}/builtin-update` beantwortet jede `template_id` selbst.
- Ziel: Die Monitoring-Journey öffnet den Verlauf des Agent-Servers und den Reiter Vergleich und prüft, dass etwas
  angezeigt wird; erst nach der Prüfung lädt sie mit einem anderen Zeitraum neu.
- Nicht-Ziel: Template-IDs als UUID typisieren oder die Pfade umbenennen (API-Vertrag); die übrigen
  Routen-Formen (siehe Risiken) bleiben, bis ein Lauf sie zeigt.
- Nicht-Ziel: Netzwerk im Verlauf (R-1105, nächster Zug).

## Betroffene Komponenten & Dateien

- monitoring: `apps/monitoring/app/history.py`, `apps/monitoring/tests/test_status_history.py`,
  `apps/monitoring/app/routers/templates.py`, `apps/monitoring/tests/test_templates_router.py`,
  `apps/monitoring/tests/openapi.snapshot.json` (nur falls die Reihenfolge der Pfade dort zählt).
- desktop-e2e: `apps/desktop/e2e/test/specs/monitoring-check.live.js`.

## Datenmodell / API / Migrationen

Keine Migration. Kein neuer Vertrag: `start`, `end` und `step` der History- und Compare-Antwort behalten ihre
Bedeutung. Neu ist nur, dass `end` jetzt nach `now` liegen kann, höchstens einen Schritt. Die Reihenfolge der
Template-Routen ändert keine Antwortform.

## Externe Integrationen

VictoriaMetrics `query_range` ([Key concepts, Range query](https://docs.victoriametrics.com/victoriametrics/keyconcepts/)):
„`end` is included only when it equals to `start+N*step`“. Wie VM ein `end` in der Zukunft behandelt, beschreibt
die Doku nicht. Eine Probe gegen `victoriametrics/victoria-metrics:v1.155.0` (das Image aus `docker-compose.yml`,
2026-11-03) hat es belegt: Samples bis `now-60s`, `step=900`, `avg_over_time(...[15m])`. Mit `end` auf dem
nächsten Rasterpunkt nach `now` liefert VM diesen Punkt auch, gemittelt über die Samples bis jetzt. Mit dem
abgerundeten `end` fehlt er.

## Trade-offs & Alternativen

- R-1104: `end` aufrunden (Empfehlung, Raster und Punktzahl bleiben) statt `end = now` (Raster verschiebt sich je
  Aufruf, `previous` und der Vergleich liegen nicht mehr auf festen Punkten).
- R-1107: die GET-Route `builtin-update` vor `assignments/{server_id}` und `suggestions/{server_id}` ziehen
  (Empfehlung, eine Zeile Verschiebung). Danach landet ein `server_id=builtin-update` bei `get_builtin_update` und
  bekommt 404. Server-IDs sind UUIDs, der Fall kommt real nicht vor. Die Alternative, `{template_id:uuid}` als
  Starlette-Convertor, ändert alle Template-Routen, die Parametertypen und das OpenAPI-Schema; das ist mehr als
  dieser Fund.

## Risiken & Rollback

- Ein Punkt in der Zukunft mittelt über einen kürzeren Zeitraum (nur bis jetzt). Für einen Mittelwert ist das
  richtig. Der Desktop zeichnet den Punkt am Ende der Achse. Rollback: Revert von T1.
- Weitere Kollisionen derselben Form sind möglich, etwa `POST /templates/suggestions/{server_id}/dismiss` gegen
  `POST /templates/{template_id}/assign/{server_id}`. T2 prüft, ob schemathesis sie zeigt. Was er nicht zeigt,
  wird eine Roadmap-Zeile, keine Task.
- R-1103 ist ein Test. Den Beweis bringt der Sammellauf (`desktop_e2e_monitoring.sh`).

## Doku-Impact

`docs/developer/monitoring.html` und die EN-Fassung: `end` ist der erste Rasterpunkt ab jetzt.
`changelog.d/kern-monitoring-4.md` für R-1104 und R-1107. Die Admin-Doku beschreibt die Schritte schon richtig.

## Offene Fragen

Keine.
