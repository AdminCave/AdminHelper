<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-freebsd-1 — Task-Ledger
Status: erledigt · Branch: feature/kern-freebsd-1 · Review: pro Task
Spec: docs/features/kern-freebsd-1.md (Roadmap R-1253, R-1251)
Heavy: linux-full — Agent (FreeBSD-Sammler, rc-Skript, Paket); dazu vor dem Merge der FreeBSD-Box-Lauf `bash scripts/tests/freebsd_box.sh` auf der Pool-VM
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1253: cpu_count und Swap auch unter FreeBSD melden  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/collector.go, apps/agent/internal/monitor/collector_test.go, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-freebsd-1.md, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @ea5762394 2026-11-11T14:52:38+01:00
Review: approve (.ah-out/review/kern-freebsd-1/T1.verdict.json)
Änderung: Test zuerst: ein Stub mit `goos` `freebsd` erwartet `cpu_count` und die Swap-Felder wie unter Linux (rot);
dann lässt `collectSwapAndCPUCount` Linux und FreeBSD sammeln, Windows bleibt nil.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-freebsd-1.md

### T2 — R-1251: frpc-Ausgabe unter FreeBSD in eine eigene Logdatei mit Rotation  [x]
Komponente: agent · Dateien: apps/agent/freebsd/adminhelper_frpc, apps/agent/freebsd/newsyslog.conf, apps/agent/build-pkg.sh, apps/agent/internal/frpc/rcscript_test.go, apps/agent/cmd/adminhelper-agent/packaging_pkg_test.go, scripts/tests/box_freebsdbox.sh, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/kern-freebsd-1.md, docs/developer/agent.html, docs/en/developer/agent.html
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @f4a4fd4d8 2026-11-11T15:03:58+01:00
Review: approve (.ah-out/review/kern-freebsd-1/T2.verdict.json)
Änderung: Test zuerst: `rcscript_test.go` erwartet `-o /var/log/adminhelper/frpc.log` und `-H` statt `-S`/`-T`, der
Paket-Test die newsyslog-Datei im Plist (rot). Dann rc-Skript (`start_precmd` legt `/var/log/adminhelper` 0700
an), `newsyslog.conf` (SPDX-Kommentar; SIGHUP an `/var/run/adminhelper_frpc.pid`) unter
`etc/newsyslog.conf.d/adminhelper.conf` im Paket; der Box-Lauf prüft Datei, Modus 600 und `newsyslog -F`.
Elf Dateien: rc-Skript, Paket und ihre Tests gehören zusammen, dazu die Doku DE+EN.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-freebsd-1.md

### T3 — Abschlussprüfung: FreeBSD ohne Swap-Gerät meldet 0/0, Box beweist das Wiederöffnen nach der Rotation  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/collector.go, apps/agent/internal/monitor/collector_test.go, scripts/tests/box_freebsdbox.sh
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @9e341326a 2026-11-11T15:16:53+01:00
Review: approve (.ah-out/review/kern-freebsd-1/T3.verdict.json)
Änderung: Funde der Abschlussprüfung. gopsutil meldet unter FreeBSD ohne Swap-Gerät den Fehler „no swap devices found“ (mem_freebsd.go, vm.nswapdev 0); der Agent meldet dann 0/0 ohne swap_percent wie Linux, Test je OS plus Gegenprobe unter Linux (R-1253). Die Box prüft nach `newsyslog -F`, dass newsyslog nichts meldet und der daemon(8)-Supervisor die Inode der neuen Logdatei hält (fstat), statt nur den frpc-Prozess (R-1251).
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (Verhalten wie in T1 dokumentiert: ohne Swap-Gerät 0/0 ohne swap_percent)

## Entscheidungen
