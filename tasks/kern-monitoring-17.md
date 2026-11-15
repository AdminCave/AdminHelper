<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Check-Status info — Task-Ledger
Status: bereit · Branch: feature/kern-monitoring-17 · Review: pro Task
Spec: docs/features/kern-monitoring-17.md (Roadmap R-1280)
Heavy: linux-full — neuer Status in Monitoring-API und Desktop-Journeys (Übersicht, Verlauf), kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Regelstufe info, Bewertung und Benachrichtigung (R-1280)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/model.py, apps/monitoring/app/checkers/probe.py, apps/monitoring/app/check_engine.py, apps/monitoring/app/alerter.py, apps/monitoring/tests/test_status_info.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @e1329dad1 2026-11-15T17:00:45+01:00
Review: approve (.ah-out/review/kern-monitoring-17/T1.verdict.json)
Änderung: `Rule.level` nimmt `info`; `_rate` gibt `info`, wenn nur info-Regeln halten. Die Engine zählt `info` wie `ok` (Fehler- und Ok-Zähler, Dämpfung, Hold der Entwarnung). Für die Benachrichtigung gilt `info` als `ok`: `warning/critical → info` ist eine Entwarnung, `ok ↔ info` still, `info → warning` alarmiert. Neue Testdatei mit SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_status_info.py tests/test_alerter.py tests/test_alerter_sent_state.py tests/test_catalog_sensors.py
Doku: → T5

### T2 — Übersicht und Metrik für info (R-1280)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/schemas.py, apps/monitoring/app/routers/checks.py, apps/monitoring/app/core/victoria.py, apps/monitoring/tests/openapi.snapshot.json, apps/monitoring/tests/test_status_info.py, apps/monitoring/tests/test_response_shapes.py, apps/monitoring/tests/test_pagination.py, apps/monitoring/tests/test_status_page_api.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @83cb5c6fc 2026-11-15T17:03:24+01:00
Review: approve (.ah-out/review/kern-monitoring-17/T2.verdict.json)
Änderung: `StatusSummaryOut` und `GET /status/summary` zählen `info`; `monitor_check_status` schreibt für `info` den Wert 4. OpenAPI-Snapshot nachziehen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_status_info.py tests/test_openapi_snapshot.py tests/test_response_shapes.py tests/test_pagination.py tests/test_status_page_api.py
Doku: → T5
Abhängt von: T1

### T3 — OPNsense: Hinweise für Update und CARP-Wartung (R-1280)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/opnsense.py, apps/monitoring/tests/test_catalog_opnsense.py, apps/monitoring/app/checkers/probe.py, apps/monitoring/tests/test_status_info.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @149865080 2026-11-15T17:05:03+01:00
Review: approve (.ah-out/review/kern-monitoring-17/T3.verdict.json)
Änderung: Modul `opnsense` Version 2: `update_available` wahr und `update_reboot` wahr sind `info` (Check firmware), `maintenance` wahr ist `info` (Check carp); Docstring nachziehen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_opnsense.py tests/test_catalog_sensors.py tests/test_status_info.py
Doku: → T5
Abhängt von: T1

### T4 — Desktop: info blau, Host bleibt grün, eigene Zählung (R-1280)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/models/monitoring.ts, apps/desktop/ui/src/lib/models/monitoring.test.ts, apps/desktop/ui/src/components/monitoring/MonSummaryCards.svelte, apps/desktop/ui/src/components/monitoring/MonStatusTimeline.svelte, apps/desktop/ui/src/components/charts/TimeChart.svelte, apps/desktop/ui/src/components/monitoring/card/MonCard.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/monitoring/MonServerDashboard.svelte, apps/desktop/ui/src/components/monitoring/MonServerListItem.svelte, apps/desktop/ui/src/components/ui/Pill.svelte, apps/desktop/ui/src/lib/stores/monitoringPulse.test.ts, apps/desktop/ui/src/components/monitoring/card/ModuleCard.svelte, apps/desktop/ui/src/components/monitoring/card/MonCard.test.ts, apps/desktop/ui/src/styles/app.css
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @86897cbcc 2026-11-15T17:18:14+01:00
Review: approve (.ah-out/review/kern-monitoring-17/T4.verdict.json)
Änderung: `MonStatus` und `MonitoringStatusSummary` um `info`; `STATUS_PRIORITY.info` 0 (die Ampel bleibt grün), `computeSummary` zählt `info`; Karte „Hinweis“ in der Übersicht, Zeitleiste (Wert 4) und Chart blau, `MonCard` mit `data-status='info'`; Label DE/EN. Mehr als acht Dateien nur, weil Typ, Modell und die Farb-Stellen eine Änderung sind: die Label-Maps in `MonServerDashboard`/`MonServerListItem` müssen unter TS strict jeden `MonStatus` tragen, die Server-Ansicht bekommt eine blaue `Pill` (Ton `info`), die Fixture in `monitoringPulse.test.ts` das neue Pflichtfeld. Karten nehmen `cardStatus` (blau bei nur Hinweisen, `ModuleCard`), der Punkt einer info-Zeile braucht `.mon-dot.mon-info` in `app.css`, `opensByDefault` lässt eine Hinweis-Karte zu (`MonCard.test.ts`).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/models/monitoring.test.ts src/lib/api/types.contract.test.ts src/components/monitoring/MonHeartbeatBar.test.ts src/lib/stores/monitoringPulse.test.ts src/components/monitoring/card/MonCard.test.ts
Doku: → T5
Abhängt von: T2

### T5 — Doku DE+EN und Changelog (R-1280)  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-17.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @abb61523c 2026-11-15T17:38:21+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Status-Abschnitt (fünfter Status `info`, Farbe, Ampel, Zählung), Alert-Regeln (Entwarnung auf `info`, stille Wechsel), OPNsense-Tabelle (Regeln der Version 2), Werte von `monitor_check_status` (4 info); Changelog-Fragment.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: die Dateien dieser Task
Task-Review: am Ende

### T6 — Entwickler-Doku: info in Zählern, Checker-Vertrag und Alert-Pipeline (R-1280)  [x]
Komponente: scripts · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d9a9860f5 2026-11-15T18:07:52+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Fund der Abschlussprüfung: `next_ok_count()`/`holds_recovery()` zählen `info` wie `ok`, der Checker-Vertrag nennt `info`, die Alert-Pipeline nennt die Umsetzung `info → ok` (`alert_status`); Admin-Doku: eine warning-/critical-Regel ohne Wert macht den Check `unknown`, auch wenn eine info-Regel hält.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: die Dateien dieser Task
Task-Review: am Ende

## Entscheidungen
- T4: Eine Karte mit nur Hinweisen öffnet nicht von selbst und steht nicht unter den Problemen (`opensByDefault('info')` false): ein Hinweis ist kein Problem (Roadmap-Titel „kein Gelb, keine Glocke“).
- T3: Eine info-Regel ohne verwertbaren Wert wird übersprungen, statt den Check `unknown` zu machen: OPNsense sendet `update_available`/`update_reboot` erst nach einer Update-Prüfung, und ein Hinweis soll einen Check nie schlechter als `info` machen. Fehlende Werte von warning/critical-Regeln bleiben `unknown` (Fund aus T1).
