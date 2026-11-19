<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-48 — Fehlerzeilen vom Linux-Agent, SMART ohne Aufwecken — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-48 · Review: pro Task
Spec: docs/features/kern-monitoring-48.md (Roadmap R-1413, R-1569)
Heavy: linux-full — apps/agent (Sammler, Allowlist, smartctl-Aufruf)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Tasks

### T1 — R-1569: smartctl mit -n standby, schlafende Platte als standby melden  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/smart.go, apps/agent/internal/monitor/smart_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go, apps/agent/internal/monitor/allowlist_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @8427db994 2026-11-19T04:52:06+01:00
Review: approve (.ah-out/review/kern-monitoring-48/T1.verdict.json)
Änderung: `querySmartDevice` ruft `smartctl --all --json=c -n standby,3 [-d <typ>] <gerät>`; Exit 3 ergibt
`SmartDisk{Device, Standby: true}` (Feld `standby`, omitempty), keine weiteren Werte. Die Allowlist-Formen von
smartctl tragen `-n standby,3`. Tests: Aufruf trägt die Option, Exit 3 → standby-Platte, Exit 2 → weiter verworfen,
Allowlist nimmt die neuen Formen und lehnt die alten ab.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/ ./internal/allowlist/
Doku: → T6

### T2 — R-1569: Monitoring hält den letzten SMART-Stand einer schlafenden Platte  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/smart.py, apps/monitoring/tests/test_smart_checker.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @2cb3bc808 2026-11-19T04:58:28+01:00
Review: approve (.ah-out/review/kern-monitoring-48/T2.verdict.json)
Änderung: Jede gelesene Platte bekommt in den Details `read_at` (ISO-UTC). Eine Platte mit `standby: true` übernimmt
ihren Eintrag aus `prev_details["disks"]` (gleiches `device`) samt Kategorie und `read_at`, dazu `standby: true`; ihre
Probleme zählen weiter. Ohne Vorstand: Eintrag mit `standby: true`, Kategorie ok, nicht „not readable“. Die
Meldung nennt schlafende Platten („…, 1 asleep“). Tests: Stand übernommen (auch critical), ohne Vorstand, Metriken
einer schlafenden Platte aus dem Vorstand, `read_at` gesetzt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_smart_checker.py tests/test_checker_messages.py
Doku: → T6

### T3 — R-1569: Desktop zeigt „schläft, letzter Stand von …“  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/section/SecSmart.svelte, apps/desktop/ui/src/components/monitoring/section/SecSmart.test.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/models/checkDetails.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @8c89f6745 2026-11-19T05:05:19+01:00
Review: approve (.ah-out/review/kern-monitoring-48/T3.verdict.json)
Änderung: `MonitorSmartDetails.disks[]` um `standby?: boolean` und `read_at?: string`; eine Platte mit `standby`
zeigt einen Hinweis „schläft, letzter Stand von <Zeit>“ (ohne `read_at`: „schläft, noch kein Stand“). Test in
`SecSmart.test.ts`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/section/SecSmart.test.ts src/lib/api/types.contract.test.ts
Doku: → T6

### T4 — R-1413: Schwärzung der Fehlerzeilen im Agent  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/servicelogs.go, apps/agent/internal/monitor/servicelogs_test.go
Änderung: Neue Datei (SPDX) ohne Build-Tag: `cleanLogLine` wie `service_inventory.clean_log_line` (eine Zeile,
Steuerzeichen → Leerzeichen, Regeln aus `_RULES` und `_BASE64_RUN` in RE2, 300 Zeichen mit „…“). Der Test liest
`apps/monitoring/tests/service_log_redaction.json` und besteht jeden Vektor.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: → T6

### T5 — R-1413: Sammler service_logs: journalctl je Ausfall, Schalter aus dem Plan, Last-Tor  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/servicelogs_linux.go, apps/agent/internal/monitor/servicelogs_other.go, apps/agent/internal/monitor/servicelogs_linux_test.go, apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/report_test.go, apps/agent/internal/monitor/reportstate.go, apps/agent/internal/monitor/monitor.go, apps/agent/internal/probe/probe.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: `probe.Plan.ServiceLogs` (`service_logs`), weiter über `probeWork`. Nach dem Last-Tor ein optionaler
Sammler `service_logs`: Linux, Schalter an, je Unit aus `systemd.failed` (Unit-Klasse) ohne gemerkten Ausfall
(Unit + `since` aus `failed_details`) `journalctl --no-pager --quiet --output=cat --unit=<unit> --lines=10`,
Zeilen über `cleanLogLine`, höchstens 20 Units, in `systemd.failed_logs`. Report-State merkt gesendete Ausfälle,
vergisst erholte Units, Schalter aus leert ihn. Mehr als acht Dateien: Plan-Feld, Sammler, State und Allowlist
sind nur gemeinsam grün.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/ ./internal/allowlist/ ./internal/probe/
Doku: → T6
Abhängt von: T4

### T6 — Doku und Changelog  [ ]
Komponente: monitoring · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-48.md
Änderung: Fehlerzeilen kommen vom Linux-Agent (letzte 10 Einträge, einmal je Ausfall, Last-Tor); SMART: schlafende
Platten werden nicht geweckt, „letzter Stand“; Agent: Sammler und Allowlist-Aufrufe; Monitoring: `standby`/`read_at`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_smart_checker.py
Doku: diese Task
Task-Review: am Ende
Abhängt von: T1, T2, T3, T5

## Entscheidungen
- 2026-11-19 Übergabe: Kern 1 hat Plan und Kopf `aktiv` angelegt (0b30649c8, 8427db994); Kern 2 baut ab T1 (Kevin 2026-11-18: km48 gehört Kern 2).
- 2026-11-19 T1: `-n standby,3` nur für ATA/SCSI, nicht für NVMe (Scan-Protokoll `NVMe` oder Typ `nvme`): smartctl(8) führt `-n` nur unter `[ATA, SCSI]`. Die NVMe-Formen der Allowlist bleiben deshalb, die neuen kommen dazu; Status 3 ohne `-n` (NVMe) bleibt ein Öffnungsfehler.
- 2026-11-19 T2: Die Probleme einer schlafenden Platte stehen nicht in den Details; sie zählt mit ihrer letzten Kategorie als ein Problem „<Gerät> (<Modell>): <Kategorie> when last read (asleep)“. Keine Metrik-Serien für sie (keine Werte statt Nullen). `read_at` in ganzen Sekunden (`_now`, in den Tests eingefroren: Gleichheitstests vergleichen zwei Auswertungen).
