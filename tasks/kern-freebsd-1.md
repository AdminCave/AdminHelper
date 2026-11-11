<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-freebsd-1 — Task-Ledger
Status: aktiv · Branch: feature/kern-freebsd-1 · Review: pro Task
Spec: docs/features/kern-freebsd-1.md (Roadmap R-1253, R-1251)
Heavy: linux-full — Agent (FreeBSD-Sammler, rc-Skript, Paket); dazu vor dem Merge der FreeBSD-Box-Lauf `bash scripts/tests/freebsd_box.sh` auf der Pool-VM
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1253: cpu_count und Swap auch unter FreeBSD melden  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/collector.go, apps/agent/internal/monitor/collector_test.go, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-freebsd-1.md
Änderung: Test zuerst: ein Stub mit `goos` `freebsd` erwartet `cpu_count` und die Swap-Felder wie unter Linux (rot);
dann lässt `collectSwapAndCPUCount` Linux und FreeBSD sammeln, Windows bleibt nil.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-freebsd-1.md

### T2 — R-1251: frpc-Ausgabe unter FreeBSD in eine eigene Logdatei mit Rotation  [ ]
Komponente: agent · Dateien: apps/agent/freebsd/adminhelper_frpc, apps/agent/freebsd/newsyslog.conf, apps/agent/build-pkg.sh, apps/agent/internal/frpc/rcscript_test.go, apps/agent/cmd/adminhelper-agent/packaging_pkg_test.go, scripts/tests/box_freebsdbox.sh, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/kern-freebsd-1.md
Änderung: Test zuerst: `rcscript_test.go` erwartet `-o /var/log/adminhelper/frpc.log` und `-H` statt `-S`/`-T`, der
Paket-Test die newsyslog-Datei im Plist (rot). Dann rc-Skript (`start_precmd` legt `/var/log/adminhelper` 0700
an), `newsyslog.conf` (SPDX-Kommentar; SIGHUP an `/var/run/adminhelper_frpc.pid`) unter
`etc/newsyslog.conf.d/adminhelper.conf` im Paket; der Box-Lauf prüft Datei, Modus 600 und `newsyslog -F`.
Neun Dateien: rc-Skript, Paket und ihre Tests gehören zusammen.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/kern-freebsd-1.md

## Entscheidungen
