<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-5 — Task-Ledger
Status: erledigt · Branch: feature/kern-monitoring-5 · Review: pro Task
Spec: docs/features/kern-monitoring-5.md (Roadmap R-1105)
Heavy: linux-full — `apps/agent` und der Push-Pfad Agent → Monitoring; der Sammellauf fährt Stack und Agent-Monitoring
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Vorlage `AdminCave/DesignSystem@244e890` (`ui_kits/adminhelper/charts.jsx`). Stand `origin/main@c550f4a9`. T3 baut nach
dem Merge von kern-notify-1 (gemeinsam: `apps/desktop/ui/src/lib/i18n/dictionaries.ts`).

### T1 — Agent meldet Netzwerk-Byte-Zähler (R-1105)  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/collector.go, apps/agent/internal/monitor/collector_test.go, apps/agent/internal/monitor/report.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @7c1f759f 2026-11-04T18:42:24+01:00
Review: approve (.ah-out/review/kern-monitoring-5/T1.verdict.json)
Änderung: `resources.net_rx_bytes_total`/`net_tx_bytes_total` = Summe über die gezählten Interfaces aus `net.IOCounters(true)` (Linux: mit `/sys/class/net/<name>/device`, sonst alle außer Loopback; Windows: alle außer Loopback), über `resourceCalls` testbar wie Swap; ein Fehler lässt beide Felder weg. gopsutil-Doku vorher lesen.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestResources
Doku: → T4

### T2 — Netzwerk im Push, Verlauf und Vergleich (R-1105)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/agent.py, apps/monitoring/app/history.py, apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_agent_report.py, apps/monitoring/tests/test_status_history.py, apps/monitoring/tests/test_status_compare.py, apps/monitoring/tests/openapi.snapshot.json, apps/monitoring/app/schemas.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @a61e4e72 2026-11-04T18:51:41+01:00
Review: approve (.ah-out/review/kern-monitoring-5/T2.verdict.json)
Änderung: Push schreibt `monitor_agent_net_rx_bytes_total`/`…_tx_…` (nur nicht-negative JSON-Ganzzahl); Verlauf liefert `netIn`/`netOut` als `rate(…[window])*8/1e6` (Mbit/s, eigene Abfrage), Vergleich nimmt `metric=net` (eingehend). MetricsQL-`rate` am Fensterrand vorher in der VictoriaMetrics-Doku nachlesen. OpenAPI-Snapshot nachziehen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_report.py tests/test_status_history.py tests/test_status_compare.py tests/test_openapi_snapshot.py
Doku: → T4

### T3 — Desktop: Reiter Netzwerk und Vergleich „Netzwerk ein“ (R-1105)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/components/monitoring/HistoryPanel.svelte, apps/desktop/ui/src/components/monitoring/HistoryPanel.test.ts, apps/desktop/ui/src/components/monitoring/CompareView.svelte, apps/desktop/ui/src/components/monitoring/CompareView.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @c0761055 2026-11-04T19:49:58+01:00
Review: approve (.ah-out/review/kern-monitoring-5/T3.verdict.json)
Änderung: Reiter „Netzwerk“ (nur mit mindestens einem Netzwerkpunkt; eingehend oben, ausgehend unten, `mirror`, Einheit Mbit/s, keine Schwellen, keine Ereignisse) und Vergleichsmetrik `net` mit Einheit Mbit/s, ohne festes Maximum.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/HistoryPanel.test.ts src/components/monitoring/CompareView.test.ts
Doku: → T4
Abhängt von: T2

### T4 — Doku DE+EN und Changelog (R-1105)  [x]
Komponente: monitoring · Dateien: docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-5.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @baffd903 2026-11-04T19:51:01+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Report-Felder und Interface-Auswahl (agent.html), Serien, Verlauf `netIn`/`netOut` und `metric=net` (monitoring.html), Reiter Netzwerk und Vergleich (admin); Changelog-Fragment.
Task-Review: am Ende
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_status_history.py
Doku: diese Task

### T5 — Changelog-Fragment umlautfrei (R-1105)  [x]
Komponente: monitoring · Dateien: changelog.d/kern-monitoring-5.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @d639f223 2026-11-04T20:01:01+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Fund der Abschlussprüfung: das Fragment schreibt ae/oe/ue statt Umlauten (`changelog.d/README.md`, `.claude/rules/docs.md`).
Task-Review: am Ende
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_status_history.py
Doku: diese Task

## Entscheidungen
- T1: Loopback über die Flags von `net.Interfaces()` (gopsutil benennt die Zähler wie die Standardbibliothek bzw. /proc/net/dev); Linux zählt Interfaces mit `/sys/class/net/<name>/device`, ohne solche alle außer Loopback; jeder gescheiterte Lesevorgang lässt beide Felder weg (eine Teilsumme sähe aus wie ein Einbruch). `report.go` in `Dateien:` nachgetragen (Einbau in den Report).
- T2: MetricsQL-`rate` nimmt laut VictoriaMetrics-Doku die letzte Probe vor dem Fenster mit und extrapoliert nicht; das 5-min-Fenster bleibt (bei 5-min-Push liegt eine Probe davor). Verlauf skaliert in Python (`keep_metric_names` behält den Namen nur ohne Binäroperation), der Vergleich in der Abfrage (`* 8 / 1e6`). Ein Zähler über int64 geht als float hinein (`format_line`). Verschwindet ein Interface, fällt die Summe und `rate` zeigt eine Spitze von einem Punkt: hingenommen, Doku in T4. `schemas.py` in `Dateien:` nachgetragen.
- T3: Der Reiter Netzwerk erscheint nur, wenn `netIn` oder `netOut` einen Punkt trägt; während ein Verlauf lädt, bleibt ein gewählter Reiter stehen (ein Periodenwechsel wirft nicht auf CPU), ein Server ohne Daten fällt auf CPU zurück. Ereignisse der Checks bleiben im Reiter weg (sie sagen nichts über Verkehr). Der Vergleich nutzt die vorhandene Skalierung ohne festes Maximum für Nicht-%-Einheiten.
- T4: Der Ausreißer beim Verschwinden eines Interfaces steht in der Entwickler-Doku (Verlauf), nicht in der Admin-Doku; Admin nennt, dass ältere Agents keinen Reiter Netzwerk bekommen.
- T5: Umlaute im Fragment durch ae/oe/ue ersetzt (Fund der Abschlussprüfung); die Fragmente von main enthalten ebenfalls keine.
