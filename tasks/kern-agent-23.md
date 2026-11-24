# kern-agent-23 — Task-Ledger
Status: aktiv · Branch: feature/kern-agent-23 · Review: pro Task
Spec: docs/features/kern-agent-23.md (Roadmap R-1701, R-1728)
Heavy: linux-full — apps/agent (Platten-Sammler FreeBSD, Paketaufteilung monitor/send/push mit Provisioning-Aufrufer)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1701: FreeBSD liest die Platten ohne Hänger (MNT_NOWAIT, Netz-Mounts mit Frist)  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/collector.go, apps/agent/internal/monitor/disks_bounded.go, apps/agent/internal/monitor/disks_freebsd.go, apps/agent/internal/monitor/disks_other.go, apps/agent/internal/monitor/disks_test.go, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-agent-23.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @049ae8f5f 2026-11-24T20:00:59+01:00
Review: approve (.ah-out/review/kern-agent-23/T1.verdict.json)
Beweis: main@4c8173e06 apps/agent/internal/monitor/collector.go:304-321 (disk.Usage je Mount), gopsutil v4.26.10 disk/disk_freebsd.go:27,33 (Getfsstat MNT_WAIT) · Dedup-Key: bug:agent:collector.go:freebsd-hung-share-blocks-report
Änderung: Unter FreeBSD baut `collectDisks` die Liste aus `unix.Getfsstat(MNT_NOWAIT)`. Netz-Mounts (nfs, smbfs, fusefs) fragt `boundedStats` je in einer Goroutine mit 5 s Frist frisch ab, ein Mount ohne Antwort fehlt in diesem Lauf. Die Umrechnung `Statfs_t` → `DiskInfo` ist eine reine Funktion ohne Build-Tag und wird unter Linux getestet. Grundlage ist der gesicherte Stand aus kern-agent-22 T3: Antwort erst senden, dann melden, und nach der Frist die gepufferten Antworten abholen. Wackler-Gegenprobe: `-count=20000` bei `GOMAXPROCS` 2 und 8, Summary in den Commit-Body. Neue Dateien mit SPDX-Header. Nicht auf FreeBSD gefahren, weil keine Box im Pool ist; der Cross-Build läuft in der Verify.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: docs/developer/agent.html DE+EN (Platten unter FreeBSD) · changelog.d/kern-agent-23.md

### T2 — R-1728: Lauf als Collect + Done im Paket monitor  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/cycle.go, apps/agent/internal/monitor/monitor.go, apps/agent/internal/monitor/plan_test.go, apps/agent/internal/monitor/loadgate_test.go, apps/agent/internal/monitor/servicelogs_linux_test.go, apps/agent/internal/monitor/reportstate_test.go, apps/agent/internal/monitor/report_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @a795e5bf4 2026-11-24T20:16:23+01:00
Review: approve (.ah-out/review/kern-agent-23/T2.verdict.json)
Änderung: Neu `Collect(ctx, cfg) *Cycle` (Plan, Credentials, Report-Zustand, Report, Inventory-Drossel) und `(*Cycle).Done(pushed bool)`, das den Zustand nach Versand oder Verlust schreibt (die heutige `kept`-Logik aus `Push`). `Push` nutzt beides und verhält sich gleich. Die Zustandstests nach einem verlorenen Versand fahren `Collect` + `Done(false)` statt eines HTTP-Push. Ihre Zusicherungen bleiben unverändert, nur der Einstieg wechselt. Neue Datei mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T4

### T3 — R-1728: Versand nach monitor/send, Init und Push nach monitor/push  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/monitor.go, apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/report_test.go, apps/agent/internal/monitor/init_test.go, apps/agent/internal/monitor/monitor_test.go, apps/agent/internal/monitor/send/send.go, apps/agent/internal/monitor/send/send_test.go, apps/agent/internal/monitor/push/push.go, apps/agent/internal/monitor/push/init.go, apps/agent/internal/monitor/push/push_test.go, apps/agent/internal/monitor/push/init_test.go, apps/agent/cmd/adminhelper-agent/main.go, apps/agent/cmd/adminhelper-agent/run.go, apps/agent/cmd/adminhelper-agent/monitor_init_test.go, apps/agent/internal/provision/provision.go
Änderung: `PushReport` und `pushOnce` ziehen als `send.Report` in ein Blattpaket. `Init`, `InitParams`, `preserveServices`, `fetchServerCertPEM`, `Push` und `pushReserve` ziehen nach `push` (importiert `monitor` und `send`). Die Aufrufer in `cmd` und `provision` (Risikopfad, `security`) importieren `push`. Die Tests ziehen mit, ohne geänderte Zusicherungen. Neue Dateien mit SPDX-Header. Mehr als acht Dateien, weil Paketwechsel und Aufrufer zusammen kompilieren müssen.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T4
Test-Löschung: apps/agent/internal/monitor/init_test.go::* — zieht nach internal/monitor/push/init_test.go; apps/agent/internal/monitor/monitor_test.go::* — zieht nach internal/monitor/push/init_test.go; apps/agent/internal/monitor/report_test.go::TestPushReportSuccessNoRetry — zieht nach internal/monitor/send/send_test.go; apps/agent/internal/monitor/report_test.go::TestPushReportRetriesOnceOnTransientError — zieht nach send; apps/agent/internal/monitor/report_test.go::TestPushReportFailsAfterSingleRetry — zieht nach send; apps/agent/internal/monitor/report_test.go::TestPushReportAbortsInFlightRequestOnContextCancel — zieht nach send; apps/agent/internal/monitor/report_test.go::TestPushBudgetKeepsThePushReserve — zieht nach internal/monitor/push/push_test.go; apps/agent/internal/monitor/report_test.go::TestPushKeepsTheStateThroughALostPush — zieht nach internal/monitor/push/push_test.go (Ende-zu-Ende-Test aus T2)

### T4 — Doku: Paketaufteilung des Agent-Monitorings (R-1728)  [ ]
Komponente: scripts · Dateien: docs/developer/agent.html, docs/en/developer/agent.html
Änderung: Die Abschnitte zum Report-Bau und Versand nennen `monitor` (Collectoren, `Collect`/`Done`), `monitor/send` (Versand) und `monitor/push` (Init, TOFU, Lauf). Verweise auf `PushReport` und `monitor.go` sind nachgezogen.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/agent.html DE+EN
Task-Review: am Ende
Abhängt von: T3

## Entscheidungen
