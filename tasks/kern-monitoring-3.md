<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-3 — Task-Ledger
Status: bereit · Branch: feature/kern-monitoring-3 · Review: pro Task
Spec: docs/features/kern-monitoring-3.md (Roadmap R-1076, R-1077)
Heavy: linux-full — neue Monitoring-Routen und Agent-Push-Serien hinter dem Gateway, Agent-Collector, Desktop-Journey Monitoring; der Sammellauf fährt Stack, Agent-Monitoring und die GUI-E2E
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Vorlage `AdminCave/DesignSystem@244e890` (`ui_kits/adminhelper/charts.jsx`). Zeilenangaben `origin/main@594a0af5`.
Der Server-Proxy (`apps/server/app/modules/monitoring_proxy/router.py`) reicht `/status/…` und `/checks/…` samt Query
durch und bleibt unverändert. Desktop-Tasks bauen auf dem gemergten kern-design-2 auf (vorher `origin/main` in den
Branch mergen).

### T1 — Agent-Push schreibt Swap und CPU-Anzahl (R-1076)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/agent.py, apps/monitoring/tests/test_agent_report.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @27cbae5c 2026-11-02T20:24:40+01:00
Review: approve (.ah-out/review/kern-monitoring-3/T1.verdict.json)
Änderung: `_report_lines` (`app/routers/agent.py:149`) schreibt zusätzlich `swap_percent` und `cpu_count` aus `resources` als `monitor_agent_<key>` (gelesen wie die übrigen über `agent_number`); fehlt ein Feld, entsteht keine Zeile. Test: Report mit und ohne die Felder, Zeilen wörtlich.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_report.py
Doku: → T12

### T2 — Verlaufs-Endpunkt je Server, 30 Tage (R-1076)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/app/schemas.py, apps/monitoring/app/history.py, apps/monitoring/tests/test_status_history.py, apps/monitoring/tests/test_checks_metrics.py, apps/monitoring/tests/openapi.snapshot.json
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @17786838 2026-11-02T20:30:02+01:00
Review: approve (.ah-out/review/kern-monitoring-3/T2.verdict.json)
Änderung: `GET /checks/{id}/metrics` nimmt `period=30d` (Schritt 6h, `app/routers/checks.py:498`, `:510`). Neu `GET /status/server/{server_id}/history?period=1h|24h|7d|30d&previous=` (Schritte 1m/15m/1h/6h): Serien cpu, ram, swap, loadPerCpu (`load_1m / cpu_count`), Disks je Mount auf festem Raster mit `null`-Lücken, mit `previous=true` dieselben um eine Periode verschoben (`offset`), Schwellen aus der `agent_resources`-Konfiguration des Servers bzw. den Checker-Defaults; Abfragen mit Agent-Filter `check_id=""` wie `get_check_metrics`, Fehler über `_series_or_502`. Neue Datei `app/history.py` (Raster, Abfragen) mit SPDX-Header. Tests mit gemocktem `victoria.query_range`: Abfragen wörtlich, Raster, Lücken, previous, Schwellen, Server ohne Daten → leere Serien, VictoriaMetrics-Fehler → 502.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_status_history.py tests/test_checks_metrics.py tests/test_openapi_snapshot.py
Doku: → T12

### T3 — Ereignisse und Wartungsfenster im Verlauf (R-1076)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/maintenance.py, apps/monitoring/app/history.py, apps/monitoring/app/schemas.py, apps/monitoring/tests/test_maintenance.py, apps/monitoring/tests/test_status_history.py, apps/monitoring/app/routers/checks.py, apps/monitoring/tests/openapi.snapshot.json
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @cb013fa8 2026-11-02T20:35:23+01:00
Review: approve (.ah-out/review/kern-monitoring-3/T3.verdict.json)
Änderung: `maintenance.py` bekommt `maintenance_intervals(windows, server_id, start, end)`: die Intervalle aller `once`- und `weekly`-Fenster (Server und global) im Zeitraum, in UTC, mit der Zeitzonen-Logik von `_weekly_active` (DST-Wechsel getestet). Der Verlauf liefert `maintenance` und `events` (Alert-Log der Checks des Servers im Zeitraum: Zeit, Check-ID, Check-Name, neuer Status; höchstens 200, neueste zuerst).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_maintenance.py tests/test_status_history.py tests/test_openapi_snapshot.py
Doku: → T12
Abhängt von: T2

### T4 — Vergleichs-Endpunkt über mehrere Server (R-1077)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/app/history.py, apps/monitoring/app/schemas.py, apps/monitoring/tests/test_status_compare.py, apps/monitoring/tests/openapi.snapshot.json
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @92d39a97 2026-11-02T20:38:43+01:00
Review: approve (.ah-out/review/kern-monitoring-3/T4.verdict.json)
Änderung: Neu `GET /status/compare?metric=cpu|ram|disk|load&period=…`: eine `query_range` je Metrik über alle Server (`by (server_id)`; disk = `max by (server_id)` über die Mounts, load = `load_1m / cpu_count`), Antwort je Server auf dem Raster aus T2. Route vor `/status/server/{server_id}` registriert, kein Konflikt mit `/status/summary`. Test mit Mock: Abfragen wörtlich, Zuordnung je Server, unbekannte Metrik 422.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_status_compare.py tests/test_status_history.py tests/test_openapi_snapshot.py
Doku: → T12
Abhängt von: T2

### T5 — Agent meldet Netzwerk-Zähler (R-1076)  [~] (verschoben in R-1105: wartet auf Kevins Antwort (Netzwerk über den Agent))
Komponente: agent · Dateien: apps/agent/internal/monitor/collector.go, apps/agent/internal/monitor/collector_test.go
Änderung: `resources.net` = Summe `bytes_recv`/`bytes_sent` über alle Interfaces außer Loopback (`net.IOCounters(true)`, gopsutil, Linux und Windows), über `resourceCalls` testbar wie Swap; ein Fehler lässt nur das Feld weg.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestCollect
Doku: → T12

### T6 — Netzwerk im Push, Verlauf und Vergleich (R-1076, R-1077)  [~] (verschoben in R-1105: wartet auf Kevins Antwort (Netzwerk über den Agent))
Komponente: monitoring · Dateien: apps/monitoring/app/routers/agent.py, apps/monitoring/app/history.py, apps/monitoring/tests/test_agent_report.py, apps/monitoring/tests/test_status_history.py, apps/monitoring/tests/test_status_compare.py
Änderung: Push schreibt `monitor_agent_net_rx_bytes_total`/`…_tx_…`; Verlauf liefert `netIn`/`netOut` als `rate(…[step])*8/1e6` (Mbit/s), Vergleich nimmt `metric=net`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_report.py tests/test_status_history.py tests/test_status_compare.py
Doku: → T12
Abhängt von: T4, T5

### T7 — CSV-Datei schreiben (R-1076)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/storage.rs, apps/desktop/src-tauri/src/main.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @5a50f656 2026-11-02T20:45:26+01:00
Review: approve (.ah-out/review/kern-monitoring-3/T7.verdict.json)
Änderung: Command `write_export_csv(dest_path, content)` nach dem Muster `export_browser_p12` (`src/commands.rs:258`): nur Endung `.csv`, `ensure_parent`, Schreiben, Pfad zurück; registriert in `main.rs`. Unit-Test in `storage.rs`: Schreiben, Endung abgelehnt.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- storage
Doku: keine (interner Command; der Export ist in T12 beschrieben)

### T8 — Chart-Baustein TimeChart (R-1076, R-1077)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/charts/TimeChart.svelte, apps/desktop/ui/src/components/charts/TimeChart.test.ts, apps/desktop/ui/src/lib/charts.ts, apps/desktop/ui/src/lib/charts.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @b32f8bf4 2026-11-02T21:00:15+01:00
Review: approve (.ah-out/review/kern-monitoring-3/T8.verdict.json)
Änderung: SVG-Chart nach `TimeChart` im Mockup: Serien (Linie, Fläche, Strich), gespiegelte Achse, Schwellen, Ereignis-Marker, Bänder, Vorperiode, Prognose-Bereich ab „jetzt“, Crosshair-Tooltip, Ziehen zum Zoomen (≥ 3 Punkte), Doppelklick zurück, Tastatur: Fokus und Pfeiltasten bewegen das Crosshair. `lib/charts.ts`: `niceMax`, `stats` (Ø/P95/Max/Aktuell über Ausschnitt, `null` ignoriert), `linearSlope`, `daysUntilFull`, `toCsv`. Neue Dateien mit SPDX-Header; Tests für jede Funktion und für Tooltip, Zoom-Ereignis, ausgeblendete Serie.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/charts.test.ts src/components/charts/TimeChart.test.ts src/lib/i18n/i18n.test.ts
Doku: → T12

### T9 — Verlauf im Server-Dashboard (R-1076)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/HistoryPanel.svelte, apps/desktop/ui/src/components/monitoring/HistoryPanel.test.ts, apps/desktop/ui/src/components/monitoring/MonServerDashboard.svelte, apps/desktop/ui/src/lib/api/monitoring.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/i18n/i18n.test.ts, apps/desktop/ui/src/components/charts/TimeChart.svelte
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @d827d235 2026-11-02T21:19:20+01:00
Review: approve (.ah-out/review/kern-monitoring-3/T9.verdict.json)
Änderung: `HistoryPanel` über den Abschnitten in `MonServerDashboard.svelte` (nur Server mit Agent-Daten): Reiter CPU & RAM, Speicher (Prognose-Pill „voll in ~n Tagen“ unter 60 Tagen), Netzwerk (nur mit Daten), Latenz (je Ping/HTTP/TCP-Check aus `getCheckMetrics` mit gleichem Zeitraum), Load; Zeitraum-Umschalter, Vorperiode, Legende, Kennzahlentabelle, Zoom zurücksetzen, CSV über Dialog `save` + `write_export_csv`. Fehler einer Ladung zeigt eine Meldung statt leerer Achsen. Acht Dateien, weil API, Typ, Bridge und i18n nur dieser Ansicht dienen.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/HistoryPanel.test.ts src/lib/i18n/i18n.test.ts
Doku: → T12
Abhängt von: T2, T3, T7, T8

### T10 — Reiter Verlauf: Server vergleichen (R-1077)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/CompareView.svelte, apps/desktop/ui/src/components/monitoring/CompareView.test.ts, apps/desktop/ui/src/lib/stores/monitoring.ts, apps/desktop/ui/src/components/monitoring/MonitoringOverview.svelte, apps/desktop/ui/src/lib/api/monitoring.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/pages/Monitoring.svelte, apps/desktop/ui/src/lib/i18n/i18n.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @ebb59c87 2026-11-02T21:28:58+01:00
Review: approve (.ah-out/review/kern-monitoring-3/T10.verdict.json)
Änderung: `MonitoringTab` (`lib/stores/monitoring.ts:32`) um `history`; `CompareView`: Metrik-Umschalter, Zeitraum, Chart mit bis zu vier Servern (der fünfte verdrängt den ältesten), Rangliste aller Agent-Server nach Ø im Ausschnitt mit Balken, Sparkline, Ø, Max; Klick oder Checkbox wählt; Servernamen aus dem Server-Store. Test: Auswahl-Grenze, Rangfolge, Zoom wirkt auf Rangliste.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/CompareView.test.ts src/lib/i18n/i18n.test.ts
Doku: → T12
Abhängt von: T4, T8

### T11 — Live-E2E: Verlauf und Vergleich (R-1076, R-1077)  [~] (verworfen: Prüfer-Blocker nach zwei Runden (Wartefunktion prüft nach dem Neuladen, Anzeige ist dann leer); Abdeckung als eigene Roadmap-Zeile)
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/monitoring-check.live.js
Änderung: Die Monitoring-Journey öffnet den Verlauf des Agent-Servers (Chart mit CPU-Serie, Zeitraum 24 Std., CSV-Knopf vorhanden) und den Reiter Verlauf (Rangliste nennt den Server). Beweis im Sammellauf (`desktop_e2e_monitoring.sh`).
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T9, T10

### T12 — Doku Verlauf und Vergleich (R-1076, R-1077)  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-monitoring-3.md, docs/developer/desktop.html, docs/en/developer/desktop.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @6dc3a843 2026-11-02T21:52:04+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Bedienung Verlauf und Vergleich, Zeiträume (`docs/admin/monitoring.html:240` nennt schon „30d“, das die API bisher nicht kennt), neue Serien und Routen, CSV-Export; Changelog-Fragment umlautfrei.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: die genannten Dateien
Task-Review: am Ende

### T13 — Doku-Funde der Abschlussprüfung (R-1076, R-1077)  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-3.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @2b1c5410 2026-11-02T22:09:02+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Liste nennt nur die Zeitfenster der UI (1h, 6h, 24h, 7d; ExpandChart.svelte:22), Changelog sagt, dass das Monitoring Swap und CPU-Zahl aus dem Agent-Report speichert (der Agent meldete sie schon), Developer-Doku nennt TimeChart für Verlauf und Vergleich neben uPlot.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: die genannten Dateien
Task-Review: am Ende

## Entscheidungen
- T2: `loadPerCpu` ist `load_5m / cpu_count` (nicht `load_1m` wie in der Spec), weil die Load-Schwellen des Checkers (`_grade_load`) auf `load_5m` je CPU stehen; so gelten die Schwellenlinien für die gezeigte Linie.
- T2: Jeder Punkt ist `avg_over_time(…[Fenster])` (Fenster = Schritt, mindestens 5m = Push-Intervall des Agents) mit `keep_metric_names` (MetricsQL-Doku: alle Rollups nehmen den Modifier), nicht der letzte Rohwert; bei 6 h je Punkt stünde sonst ein Sample für sechs Stunden. Die Vorperiode wird als eigener Zeitraum abgefragt und auf das Raster verschoben, ohne `offset`.
- T3: Ereignisse sind die Zeilen des Alert-Logs (nur Statuswechsel, zu denen eine Alert-Regel passte); mehrere Regeln schreiben je Wechsel eine Zeile, gleiche Zeilen (Check, alter und neuer Status) binnen 60 s zählen einmal. Wartungsbänder in Unix-Sekunden, auf den Zeitraum zugeschnitten, globale Fenster eingeschlossen.
- T4: `/status/compare` nimmt cpu, ram, disk (der vollste Mount je Server, `max by (server_id)`) und load (`load_5m / cpu_count` wie T2); `net` fehlt, bis der Agent Netzwerkdaten liefert (T5/T6, Frage an Kevin). Server ohne Agent-Daten erscheinen nicht; die Liste ist nach `serverId` sortiert, Namen löst der Desktop auf.
- T9: Der Reiter Netzwerk fehlt, bis der Agent Netzwerkdaten liefert (T5/T6, Frage an Kevin). Latenz: je Check `fetchMetrics` mit dem Zeitraum der History, Punkte per Rundung auf deren Raster gelegt (gleiche Schrittweiten), gemessener Wert vor der Check-Dauer. Die Speicher-Prognose läuft ein Viertel des Zeitraums weiter. „Agent-Daten“ heißt: der Server hat einen `agent_resources`-Check.
- T9: Dazu zwei Nachzüge aus T8: `svelte-ignore` im Runes-Modus trennt mehrere Codes per Komma (sonst gilt der zweite als Beschreibung und svelte-check warnt), und der i18n-Test kennt die dynamischen Präfixe `monitoring.history.tab.`/`.period.`.
- T10: Die Reiterleiste steht in `pages/Monitoring.svelte`, nicht in `MonitoringOverview.svelte` (Dateiliste angepasst). Die erste Antwort wählt die vier Server mit dem höchsten Ø; danach gehört die Auswahl dem Nutzer, auch leer, und bleibt beim Metrik- oder Zeitraumwechsel. Die Metrik Netzwerk fehlt wie in T9. Balken und Sparkline skalieren bei % auf 100, bei Load auf den größten Wert.
