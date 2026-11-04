<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-5 — Task-Ledger
Status: geplant · Branch: feature/kern-monitoring-5 · Review: pro Task
Spec: docs/features/kern-monitoring-5.md (Roadmap R-1105)
Heavy: linux-full — `apps/agent` und der Push-Pfad Agent → Monitoring; der Sammellauf fährt Stack und Agent-Monitoring
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Vorlage `AdminCave/DesignSystem@244e890` (`ui_kits/adminhelper/charts.jsx`). Stand `origin/main@c550f4a9`. T3 baut nach
dem Merge von kern-notify-1 (gemeinsam: `apps/desktop/ui/src/lib/i18n/dictionaries.ts`).

### T1 — Agent meldet Netzwerk-Byte-Zähler (R-1105)  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/collector.go, apps/agent/internal/monitor/collector_test.go
Änderung: `resources.net_rx_bytes_total`/`net_tx_bytes_total` = Summe über die gezählten Interfaces aus `net.IOCounters(true)` (Linux: mit `/sys/class/net/<name>/device`, sonst alle außer Loopback; Windows: alle außer Loopback), über `resourceCalls` testbar wie Swap; ein Fehler lässt beide Felder weg. gopsutil-Doku vorher lesen.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestResources
Doku: → T4

### T2 — Netzwerk im Push, Verlauf und Vergleich (R-1105)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/agent.py, apps/monitoring/app/history.py, apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_agent_report.py, apps/monitoring/tests/test_status_history.py, apps/monitoring/tests/test_status_compare.py, apps/monitoring/tests/openapi.snapshot.json
Änderung: Push schreibt `monitor_agent_net_rx_bytes_total`/`…_tx_…` (nur nicht-negative JSON-Ganzzahl); Verlauf liefert `netIn`/`netOut` als `rate(…[window])*8/1e6` (Mbit/s, eigene Abfrage), Vergleich nimmt `metric=net` (eingehend). MetricsQL-`rate` am Fensterrand vorher in der VictoriaMetrics-Doku nachlesen. OpenAPI-Snapshot nachziehen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_report.py tests/test_status_history.py tests/test_status_compare.py tests/test_openapi_snapshot.py
Doku: → T4

### T3 — Desktop: Reiter Netzwerk und Vergleich „Netzwerk ein“ (R-1105)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/components/monitoring/HistoryPanel.svelte, apps/desktop/ui/src/components/monitoring/HistoryPanel.test.ts, apps/desktop/ui/src/components/monitoring/CompareView.svelte, apps/desktop/ui/src/components/monitoring/CompareView.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Reiter „Netzwerk“ (nur mit mindestens einem Netzwerkpunkt; eingehend oben, ausgehend unten, `mirror`, Einheit Mbit/s, keine Schwellen, keine Ereignisse) und Vergleichsmetrik `net` mit Einheit Mbit/s, ohne festes Maximum.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/HistoryPanel.test.ts src/components/monitoring/CompareView.test.ts
Doku: → T4
Abhängt von: T2

### T4 — Doku DE+EN und Changelog (R-1105)  [ ]
Komponente: monitoring · Dateien: docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-5.md
Änderung: Report-Felder und Interface-Auswahl (agent.html), Serien, Verlauf `netIn`/`netOut` und `metric=net` (monitoring.html), Reiter Netzwerk und Vergleich (admin); Changelog-Fragment.
Task-Review: am Ende
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_status_history.py
Doku: diese Task

## Entscheidungen
