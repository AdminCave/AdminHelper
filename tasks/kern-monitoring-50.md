# Dienst-Details Windows/FreeBSD: Fehlerzeilen und „Mehr Log“ — Task-Ledger
Status: bereit · Branch: feature/kern-monitoring-50 · Review: pro Task
Spec: docs/features/kern-monitoring-50.md (Roadmap R-1391)
Heavy: windows — Windows-Agent-Sammler; keine Windows-Box im Pool, die Windows-CI-Jobs (go test als Admin) sind der Plattform-Beleg; Linux-Pfad unverändert
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1391: Windows-Agent sendet Fehlerzeilen gestoppter Auto-Start-Dienste  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/winevents.go, apps/agent/internal/monitor/winevents_test.go, apps/agent/internal/monitor/servicelogs_windows.go, apps/agent/internal/monitor/servicelogs_other.go, apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/report_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go, apps/agent/internal/monitor/winevents_windows_test.go, apps/agent/internal/monitor/servicelogs_linux.go, apps/agent/internal/monitor/servicelogs_linux_test.go, apps/agent/internal/monitor/allowlist_test.go, apps/agent/internal/monitor/servicelogs_windows_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @e38207850 2026-11-19T11:10:22+01:00
Review: approve (.ah-out/review/kern-monitoring-50/T1.verdict.json)
Änderung:
- `winevents.go` (neu, SPDX, ohne Build-Tag) parst die RenderedXml zweier fester `wevtutil`-Aufrufe:
  - System: SCM-Ereignisse der letzten 24 h
  - Application: Level 1–3 der letzten 24 h, je `/c:200`
- Je Dienst wählt der Parser die letzten 10 Ereignisse: im System-Log die SCM-Ereignisse, deren `param1` Dienst- oder Anzeigename ist; im Application-Log die, deren Provider der Dienstname ist. Zeilen älteste zuerst, über `cleanLogLine`.
- `servicelogs_windows.go` (neu, SPDX) führt die Aufrufe einmal je Lauf aus.
- `report.go` wählt die Kandidaten je Plattform: unter Linux `failed`, unter Windows gestoppte `enabled`-Dienste mit `exit`, mit `since` aus den Crash-Ereignissen. Unter Windows setzt `report.go` `log_units`.
- Die Allowlist bekommt die zwei Aufrufe.

Tests:
- Parser mit Fixture-XML
- Auswahl, Einmal-je-Ausfall, Linux-Block ohne `log_units` unverändert
- Allowlist

Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/ ./internal/allowlist/
Doku: → T4

### T2 — R-1391: Monitoring speichert Zeilen für log_units  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/service_inventory.py, apps/monitoring/tests/test_service_inventory.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @068dc7a53 2026-11-19T11:11:34+01:00
Review: approve (.ah-out/review/kern-monitoring-50/T2.verdict.json)
Änderung: `store_service_report` nimmt als Liste der Dienste mit Zeilen `log_units`, wenn der Block sie als Liste trägt (gekappt wie `failed`), sonst `failed`. Gespeichert, behalten und gelöscht wird nach dieser Liste. Tests: Windows-Block mit `log_units` speichert und löscht; Linux-Block ohne `log_units` wie bisher; `log_units` keine Liste → `failed`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_service_inventory.py tests/test_service_inventory_api.py
Doku: → T4

### T3 — R-1391: „Mehr Log“ unter Windows und FreeBSD  [x]
Komponente: desktop · Dateien: apps/desktop/src-tauri/src/connection/ssh.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/stores/connectFlow.ts, apps/desktop/ui/src/components/monitoring/section/ServiceList.svelte, apps/desktop/ui/src/components/monitoring/section/ServiceList.test.ts, apps/desktop/ui/src/components/monitoring/section/SecServices.svelte, apps/desktop/ui/src/lib/bridge/invoke.test.ts, apps/desktop/ui/src/lib/stores/connectFlow.test.ts, apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/terminal/SshTerminal.test.ts, apps/desktop/ui/src/components/monitoring/section/SecServices.test.ts
Evidenz: run.sh[quick] desktop: 3 passed, 0 failed, 15 skipped @88d5defb0 2026-11-19T11:37:47+01:00
Review: approve (.ah-out/review/kern-monitoring-50/T3.verdict.json)
Änderung: `terminal_open_ssh_journal` nimmt `platform`. Je Plattform läuft ein fester Remote-Aufruf:
- **linux:** journalctl wie bisher.
- **windows:** `powershell -NoProfile -NonInteractive -EncodedCommand <Base64 UTF-16LE>`. Darin liest `Get-WinEvent` System und Application der letzten 24 h, filtert auf den Dienst (Provider = Name, oder SCM mit `param1` = Name/Anzeigename) und zeigt die neuesten 200. Der Name steht nur in der Windows-Dienstklasse, in einfachen Anführungszeichen.
- **freebsd:** `grep -h -F -e '<name>' /var/log/messages | tail -n 200`, der Name nur in der `rcscript`-Klasse der Agent-Allowlist.

UI:
- `ServiceList` erhält die Plattform des Servers (os_type) von `SecServices` und zeigt „Mehr Log“ unter linux, windows und freebsd/opnsense.
- `other` zeigt keinen Knopf.

Tests: argv je Plattform, Ablehnung außerhalb der Klasse, das dekodierte Skript, UI je Plattform.
Verify: bash scripts/dev/verify.sh desktop --strict
Doku: → T4

### T4 — R-1391: Doku Dienst-Details je Plattform  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-50.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @0d1e18f9d 2026-11-19T11:39:52+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Abschnitt Dienst-Details (DE+EN):
- Windows: Fehlerzeilen bei gestopptem Auto-Start-Dienst mit Exit-Code, aus System- und Application-Log.
- „Mehr Log“ je Plattform: journalctl, Ereignisprotokoll über PowerShell, syslog.
- FreeBSD ohne Fehlerzeilen.

Dazu das CHANGELOG-Fragment.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Task-Review: am Ende
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-50.md
Abhängt von: T1, T2, T3

### T5 — R-1391: Entwickler-Doku Fehlerzeilen und „Mehr Log“ je Plattform  [x]
Komponente: scripts · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/desktop.html, docs/en/developer/desktop.html, docs/features/kern-monitoring-50.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @14fe85ff8 2026-11-19T11:51:30+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Abschlussprüfung (Funde wichtig, Doku): `monitoring.html` nennt `systemd.log_units` (Report-Beispiel, Fehlerzeilen nach `log_units` sonst `failed`); `agent.html` nennt den Windows-Weg von `collectServiceLogs` und `scmLogArgs`/`appLogArgs` in der Allowlist; `desktop.html` nennt `platform` von `terminal_open_ssh_journal` und die Befehle je Plattform. Spec Stufe 3 FreeBSD auf `grep -F` und die `rcscript`-Klasse (Nit).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Task-Review: am Ende
Doku: docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/desktop.html, docs/en/developer/desktop.html
Abhängt von: T4

## Entscheidungen
- 2026-11-19 Plan: `log_units` statt `failed ∪ enabled_inactive`, damit Linux nach `reset-failed` unverändert Zeilen verliert; Windows-Stufe 2 mit zwei festen `wevtutil`-Aufrufen und Auswahl in Go, kein Dienstname im Aufruf; Stufe 3 Windows über `-EncodedCommand`, weil `wevtutil`-XPath sich für cmd und PowerShell als Login-Shell nicht gleich quoten lässt.
- 2026-11-19 T3: `Komponente: desktop` statt `desktop-rs desktop-ui`, weil `task-close.sh` das Feld ohne Leerzeichen vergleicht; `verify.sh desktop` fährt beide.
