<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-5 — Netzwerk ein/aus im Monitoring-Verlauf

Roadmap: R-1105 (FEAT, Rest von R-1076; Kevin 2026-11-03: Agent-Report additiv erweitern). Vorlage
`AdminCave/DesignSystem@244e890` (`ui_kits/adminhelper/charts.jsx`: Reiter „Netzwerk“, `mirror`, Mbit/s; Vergleich
„Netzwerk ein“). Stand `origin/main@c550f4a9`. Baut auf kern-monitoring-3 (Verlauf, Vergleich), dessen T5/T6 hierher
verschoben wurden.

## Problem / Motivation
Der Verlauf eines Servers (`components/monitoring/HistoryPanel.svelte`) zeigt CPU & RAM, Speicher, Latenz und Load,
der Vergleich (`CompareView.svelte`) CPU, RAM, Speicher und Load. Netzwerk fehlt, weil der Agent keine
Netzwerkdaten sammelt (`apps/agent/internal/monitor/collector.go`, `collectSwapAndCPUCount` meldet nur Swap und
CPU-Zahl).

## Ziel & Nicht-Ziele
**Ziel:**
- Der Agent meldet zwei Byte-Zähler in `resources`: `net_rx_bytes_total`, `net_tx_bytes_total` (Linux und Windows),
  additiv: alte Agents senden sie nicht, alte Monitoring-Dienste ignorieren sie. Keine neue Report-Version.
- Das Monitoring schreibt sie als `monitor_agent_net_rx_bytes_total` / `…_tx_…`; der Verlauf liefert `netIn` /
  `netOut` in Mbit/s, der Vergleich nimmt `metric=net` (eingehend je Server).
- Desktop: Reiter **Netzwerk** im Verlauf (eingehend oben, ausgehend unten gespiegelt, `TimeChart` `mirror`), nur
  wenn der Server Netzwerkdaten hat; Vergleichsmetrik **Netzwerk ein**.

**Nicht-Ziele:**
- Zähler je Interface in der UI, Schwellen oder Alarme auf Netzwerk (kein Checker liest die Werte).
- Web-Frontend (zeigt keinen Verlauf).

## Betroffene Komponenten & Dateien
- Agent: `apps/agent/internal/monitor/collector.go` (+ `collector_test.go`).
- Monitoring: `app/routers/agent.py` (`_report_lines`), `app/history.py` (`history_queries`, `build_series`,
  `_COMPARE_NAMES`/`compare_query`), `app/routers/checks.py` (Pattern `metric`), Tests
  `test_agent_report.py`, `test_status_history.py`, `test_status_compare.py`, OpenAPI-Snapshot.
- Desktop-UI: `lib/api/types.ts` (`HistorySeries.netIn/netOut`, Vergleichsmetrik), `components/monitoring/
  HistoryPanel.svelte`, `CompareView.svelte` (+ Tests), `lib/i18n/dictionaries.ts`.

## Datenmodell / API / Migrationen
- Agent-Report (additiv): `resources.net_rx_bytes_total`, `resources.net_tx_bytes_total`, ganze Zahlen (Bytes seit
  Boot, Summe über die gezählten Interfaces). Gezählt wird unter Linux jedes Interface mit
  `/sys/class/net/<name>/device` (physisch oder virtio); findet sich keins (Container, `veth`), alle außer Loopback.
  So zählt ein Proxmox-Host `eno1`, aber nicht noch einmal `vmbr0` und die `tap`/`veth` der Gäste. Windows: alle
  außer Loopback. Ein Fehler lässt beide Felder weg.
- Monitoring: Zeilen nur für eine nicht-negative JSON-Ganzzahl (Regel wie `cpu_count`). Verlauf
  `rate(monitor_agent_net_rx_bytes_total_value{…}[window]) * 8 / 1e6` (Mbit/s); `rate` verkraftet den Rücksprung
  nach einem Neustart. Ob MetricsQL `rate` bei 5-min-Push und 5-min-Fenster die Probe vor dem Fenster mitnimmt, liest
  T2 vor dem Bau in der VictoriaMetrics-Doku nach (**nicht verifiziert**); sonst Fenster mindestens 10 min.
- API: `GET /status/server/{id}/history` liefert zusätzlich `series.netIn`, `series.netOut` (leere Liste ohne
  Daten); `GET /status/compare?metric=` nimmt `net`. Additiv; der Snapshot ändert sich. Keine Migration.

## Externe Integrationen
gopsutil `net.IOCounters(true)` (Linux `/proc/net/dev`, Windows `GetIfEntry2`), VictoriaMetrics MetricsQL `rate`
(https://docs.victoriametrics.com/victoriametrics/metricsql/). Beides liest die jeweilige Task vor dem Bau nach.

## Trade-offs & Alternativen
- **Summe im Agent — empfohlen** statt Zähler je Interface im Report: je Interface hieße eine Serie je Interface
  und Server in VictoriaMetrics (Docker-Hosts haben Dutzende `veth`) und die Auswahl der Interfaces im Monitoring.
  Der Agent kennt `/sys/class/net` und entscheidet dort.
- Mbit/s im Agent rechnen: bräuchte Zustand zwischen zwei Reports und verlöre bei jedem Neustart einen Punkt;
  Zähler + `rate` ist der übliche Weg.

## Risiken & Rollback
- Falsche Interface-Auswahl zählt doppelt oder nichts: Tests für Host mit Bridge, Container ohne `device`, Loopback.
- Rollback: Commit zurücknehmen; die Serien laufen nach der Retention aus. Kein Datenpfad außer VictoriaMetrics.

## Doku-Impact
`docs/developer/agent.html`, `docs/developer/monitoring.html` (Report-Felder, Serien, Verlauf, Vergleich),
`docs/admin/monitoring.html` (Reiter Netzwerk, Vergleich), je DE+EN; Changelog-Fragment.

## Offene Fragen
Keine: Kevin hat die Agent-Erweiterung am 2026-11-03 entschieden (additiv).
