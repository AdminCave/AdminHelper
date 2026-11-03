<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-3 — Monitoring-Verlauf und Server-Vergleich

Roadmap R-1076, R-1077. Vorlage `AdminCave/DesignSystem@244e890`, `ui_kits/adminhelper/charts.jsx`
(`TimeChart`, `HistoryPanel`, `CompareView`). Zeilenangaben `origin/main@594a0af5`.

## Problem / Motivation
- **R-1076:** Das Server-Dashboard im Desktop zeigt je Check einen kleinen uPlot-Chart (`MonChart.svelte`) mit
  1h/6h/24h/7d. Es gibt keinen Verlauf je Server, der CPU, RAM, Speicher, Netzwerk, Latenz und Load gemeinsam zeigt,
  keine 30 Tage (`apps/monitoring/app/routers/checks.py:498` erlaubt nur `1h|6h|24h|7d`, obwohl VictoriaMetrics 90 Tage
  hält, `docker-compose.yml:582`), keine Schwellen, Ereignisse, Wartungsfenster, keine Vorperiode, keine Kennzahlen
  und keinen Export.
- **R-1077:** Ob ein Server auffällig ist, sieht man nur im Vergleich; heute fehlt jede Abfrage über mehrere Server.

## Ziel & Nicht-Ziele
Ziel: Das Mockup, soweit Daten dafür existieren.
- Verlauf je Server (Abschnitt im Server-Dashboard), Reiter **CPU & RAM** (Swap, wenn vorhanden), **Speicher**
  (je Mount, lineare Prognose bis voll), **Netzwerk** (ein oben, aus unten gespiegelt), **Latenz** (je Ping/HTTP/TCP-
  Check), **Load** (Load je CPU). Zeiträume 1 Std./24 Std./7 Tage/30 Tage; Crosshair-Tooltip, Ziehen zum Zoomen,
  Doppelklick zurück, Schwellenlinien aus der Check-Konfiguration, Ereignis-Marker aus dem Alert-Log,
  Wartungsfenster als Bänder, Vorperiode gestrichelt, Legende zum Ein-/Ausblenden, Ø/P95/Max/Aktuell über den
  sichtbaren Ausschnitt, CSV-Export des Reiters.
- Monitoring-Reiter **Verlauf**: bis zu vier Server je Metrik (CPU, RAM, vollster Mount, Netzwerk ein, Load/CPU) in
  einem Chart, Rangliste aller Agent-Server nach Ø mit Max und Sparkline; Klick wählt aus.

Nicht-Ziele: keine neue Retention, keine serverseitige Prognose (der Disk-Forecast-Check bleibt, wie er ist), kein
Web-Frontend, keine Persistenz der Auswahl, keine Server ohne Agent im Vergleich, kein Ersatz von `MonChart.svelte`.

## Betroffene Komponenten & Dateien
- **monitoring:** `app/routers/agent.py` (`_report_lines`, schreibt heute `cpu_percent`, `memory_percent`,
  `load_*`, Disks, Temperaturen; `swap_percent` und `cpu_count` liest nur der Checker, `app/checkers/agent.py:345`,
  `:364`); `app/routers/checks.py` (`get_check_metrics`, neue Routen unter `/status/…`); `app/maintenance.py`
  (`is_in_maintenance`, `:72`; neu: Intervalle in einem Zeitraum); `app/schemas.py`.
- **server:** keine Änderung — der Proxy (`apps/server/app/modules/monitoring_proxy/router.py`, Präfixe `checks`,
  `status`, …) reicht Pfad und Query durch.
- **agent (nur bei Ja zu Frage 1):** `internal/monitor/collector.go` (Byte-Zähler je Interface ohne Loopback).
- **desktop-rs:** ein Command zum Schreiben der CSV an den im Dialog gewählten Pfad (Muster
  `export_browser_p12`, `src-tauri/src/commands.rs:258`).
- **desktop-ui:** neue Bausteine `components/charts/TimeChart.svelte` (SVG, kein uPlot: gespiegelte Achse, Bänder,
  Prognose-Bereich und Tooltip sind in eigenem SVG kleiner als uPlot-Hooks) und `lib/charts.ts` (Statistik,
  Skala, Prognose-Fit, CSV); `components/monitoring/HistoryPanel.svelte` im `MonServerDashboard.svelte`;
  `components/monitoring/CompareView.svelte` als Reiter `history` in `lib/stores/monitoring.ts:32`
  (`MonitoringTab`); API in `lib/api/monitoring.ts`, Typen, i18n.
- **desktop-e2e:** `monitoring-check.live.js` prüft Verlauf und Vergleich gegen den echten Stack.

## Datenmodell / API / Migrationen
Keine Migration. Alles additiv, alte Clients unberührt:
- `GET /checks/{id}/metrics?period=` nimmt zusätzlich `30d` (Schritt 6 h).
- **neu** `GET /status/server/{server_id}/history?period=1h|24h|7d|30d&previous=false` →
  `{period, step, start, end, series: {cpu, ram, swap, loadPerCpu, netIn, netOut, disks: {<mount>: …}},
  previous: {…gleiche Form, um eine Periode verschoben} | null, thresholds: {cpu, ram, disk, load}
  (warn/crit aus der `agent_resources`-Konfiguration des Servers, sonst Defaults des Checkers), events: [{at,
  checkId, checkName, status}] (Alert-Log der Checks des Servers im Zeitraum), maintenance: [{start, end, note}]}`.
  Serien sind `[[ts, value|null], …]` auf dem Raster `start..end/step`; fehlende Punkte sind `null`.
- **neu** `GET /status/compare?metric=cpu|ram|disk|net|load&period=…` → `{metric, period, step, start, end,
  servers: [{serverId, points}]}` für jeden Server mit Agent-Daten; `disk` = je Zeitpunkt der vollste Mount (`max by
  (server_id)`), `load` = `load_1m / cpu_count`.
- Neue VictoriaMetrics-Serien aus dem Agent-Push: `monitor_agent_swap_percent_value`,
  `monitor_agent_cpu_count_value`; bei Ja zu Frage 1 `monitor_agent_net_rx_bytes_total_value` /
  `…_tx_…` (Zähler, Abfrage `rate()*8/1e6` = Mbit/s).
- Vertrags-Drift: der Agent-Report wird nur um optionale Felder erweitert; ein alter Agent liefert keine
  Netzwerk-/Swap-Serie, der Reiter zeigt dann „keine Daten“.

## Externe Integrationen
VictoriaMetrics `query_range` (https://docs.victoriametrics.com/keyconcepts/#range-query): `start`/`end`/`step`,
`rate()` und `max by` sind PromQL-kompatibel; `-search.maxPointsPerTimeseries` (Default 30000) liegt weit über
den höchstens 168 Punkten je Serie. Tauri-IPC wie bestehende Commands.

## Trade-offs & Alternativen
- Ein Sammel-Endpunkt je Server statt n Einzelabfragen aus dem Desktop: eine Rundreise durch Proxy und mTLS,
  ein Zeitraster; Empfehlung so.
- Wartungsbänder serverseitig: die Wochenfenster hängen an IANA-Zeitzonen (`maintenance.py`), die Logik dort
  wiederzuverwenden ist sicherer als sie in TypeScript nachzubauen.
- Prognose clientseitig (lineare Regression über den sichtbaren Zeitraum, wie im Mockup): keine neue Serverlogik;
  sie widerspricht dem Disk-Forecast-Check nicht, sie zeigt nur den Trend des gewählten Zeitraums.
- Eigenes SVG statt uPlot für den neuen Chart (siehe oben); `MonChart.svelte` bleibt.

## Risiken & Rollback
- Last auf VictoriaMetrics: Vergleich über alle Server ist eine Abfrage je Metrik (`by (server_id)`), Verlauf
  höchstens acht Abfragen mit Vorperiode; Timeouts enden wie heute in 502 (`_series_or_502`).
- Rollback: jede Task einzeln revertierbar; die neuen Routen haben keine Verbraucher außer dem Desktop.

## Doku-Impact
`docs/admin/monitoring.html` + EN (Verlauf, Vergleich, Zeiträume an `:240`, die schon „30d“ nennen),
`docs/developer/monitoring.html` + EN (neue Serien, Routen), `docs/developer/api-reference.html` + EN,
`changelog.d/kern-monitoring-3.md`.

## Offene Fragen
1. **Netzwerk braucht den Agent** (Kevin, API-Vertrag Agent ↔ Monitoring): der Agent sammelt heute keine
   Netzwerkdaten. Empfehlung: ja — der Agent meldet Byte-Zähler je Interface (ohne Loopback, additiv im Report),
   das Monitoring schreibt sie als Zähler, die Abfrage rechnet Mbit/s. Ohne Ja fehlen Reiter „Netzwerk“ und die
   Vergleichsmetrik „Netzwerk ein“ (T5, T6 `[?]`; T9 und T10 blenden sie aus, solange keine Daten kommen).
