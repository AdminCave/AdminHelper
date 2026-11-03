<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-4 — Task-Ledger
Status: bereit · Branch: feature/kern-monitoring-4 · Review: am Ende
Spec: docs/features/kern-monitoring-4.md (Roadmap R-1104, R-1107, R-1103)
Heavy: linux-full — Monitoring-Routen hinter dem Gateway und die Desktop-Journey Monitoring; der Sammellauf fährt Stack, Agent-Monitoring und `desktop_e2e_monitoring.sh`
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Verlauf und Vergleich enden am ersten Rasterpunkt ab jetzt (R-1104)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/history.py, apps/monitoring/tests/test_status_history.py, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-4.md, apps/monitoring/tests/test_status_compare.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @1c528c97 2026-11-03T17:26:32+01:00
Review: am Ende (Branch-Review)
Änderung: `history_window` rundet `end` auf den nächsten Rasterpunkt auf statt ab; `start = end - duration`, das Raster bleibt ausgerichtet. Test zuerst rot: für jeden Zeitraum gilt `end >= now`, `end - now < step`, `end % step == 0`, dieselbe Punktzahl; `now` genau auf einem Rasterpunkt bleibt dort.
Beweis: main@03c4068a apps/monitoring/app/history.py:62 `end = int(now) // step * step`; VM-Probe 2026-11-03 (Spec, Externe Integrationen) · Dedup-Key: BUG:monitoring:history.py:history_window
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_status_history.py tests/test_status_compare.py
Doku: docs/developer/monitoring.html + EN · changelog.d/kern-monitoring-4.md

### T2 — builtin-update-Route vor den Routen mit festem zweitem Segment (R-1107)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/templates.py, apps/monitoring/tests/test_templates_router.py, apps/monitoring/tests/openapi.snapshot.json, changelog.d/kern-monitoring-4.md, apps/monitoring/tests/test_template_suggestions.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @1cab4621 2026-11-03T17:32:02+01:00
Review: am Ende (Branch-Review)
Änderung: `GET /templates/{template_id}/builtin-update` wird vor `GET /templates/assignments/{server_id}` und `GET /templates/suggestions/{server_id}` registriert. Test zuerst rot: `GET /templates/assignments/builtin-update` und `GET /templates/suggestions/builtin-update` antworten 404 von `get_builtin_update`, nicht `[]`; die Zuweisungen und Vorschläge eines echten Servers bleiben gleich. Der OpenAPI-Snapshot ändert sich nur, wenn er die Reihenfolge der Pfade trägt.
Beweis: weekly 2026-11-02-2310 (schemathesis, Teil rest) · main@03c4068a apps/monitoring/app/routers/templates.py:152 vor :369 · Dedup-Key: bug:monitoring:templates.py:builtin-update-route-collision
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_templates_router.py tests/test_template_suggestions.py tests/test_openapi_snapshot.py
Doku: changelog.d/kern-monitoring-4.md

### T3 — Live-E2E: Verlauf und Server-Vergleich (R-1103)  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/monitoring-check.live.js
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped @98a49779 2026-11-03T17:38:34+01:00
Review: am Ende (Branch-Review)
Änderung: Die Monitoring-Journey öffnet den Verlauf des Agent-Servers (Chart mit CPU-Serie, Zeitraum 24 Std., CSV-Knopf) und den Reiter Vergleich (die Rangliste nennt den Server). Je Runde wartet sie erst, bis die Anzeige da ist, und prüft sie; danach lädt sie mit 1 Std. neu und wartet erneut, denn `load()` leert die Anzeige sofort. Beweis im Sammellauf (`desktop_e2e_monitoring.sh`).
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)

## Entscheidungen
- T2: `test_suggestion_route_is_not_taken_by_a_template_route` schrieb die alte Reihenfolge fest (ein Server namens `builtin-update` bekam Vorschläge); er prüft jetzt die neue Reihenfolge und die Vorschläge eines normalen Servers, wie es die Spec (Trade-offs) festlegt. Der OpenAPI-Snapshot sortiert die Schlüssel und bleibt gleich. Abgleich aller Routen (gleiche Methode, gleiche Segmentzahl, überlappende Pfade) über den echten Router: übrig bleibt nur `GET /alerts/log` vor `/alerts/{rule_id}` (gewollt); die in der Spec vermutete POST-Kollision gibt es nicht (`/templates/{id}/assign/{server_id}` ist nicht POST), also keine Roadmap-Zeile.
