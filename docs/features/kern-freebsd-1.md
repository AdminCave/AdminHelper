<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-freebsd-1 — FreeBSD-Agent: Ressourcen und frpc-Log

Roadmap R-1253, R-1251. Zug `tasks/kern-freebsd-1.md`.

## Problem / Motivation
- **R-1253:** `collectSwapAndCPUCount` (`apps/agent/internal/monitor/collector.go:203`) meldet `cpu_count` und Swap
  nur unter Linux. Unter FreeBSD bewertet das Monitoring darum weder die Load je CPU noch den Swap, obwohl der
  Agent die Load schon meldet.
- **R-1251:** Das rc-Skript `apps/agent/freebsd/adminhelper_frpc` schickt die Ausgabe von frpc per `daemon -S` ins
  syslog. Sie gehört wie das Agent-Log in eine eigene Datei unter `/var/log/adminhelper/`, mit Rotation.

## Ziel & Nicht-Ziele
- Ziel: FreeBSD meldet `cpu_count`, `swap_total_mb`, `swap_used_mb` und (mit Swap-Gerät) `swap_percent` wie Linux.
- Ziel: frpc schreibt unter FreeBSD nach `/var/log/adminhelper/frpc.log` (Modus 0600), newsyslog rotiert die Datei.
- Nicht-Ziel: Windows (meldet weiter keine dieser Felder), der Log-Pfad unter Linux (journald), OPNsense-Plugin.

## Betroffene Komponenten & Dateien
- Agent: `apps/agent/internal/monitor/collector.go`, `collector_test.go`.
- Agent/Paket: `apps/agent/freebsd/adminhelper_frpc`, neu `apps/agent/freebsd/newsyslog.conf`,
  `apps/agent/build-pkg.sh` (Plist), `apps/agent/internal/frpc/rcscript_test.go`,
  `apps/agent/cmd/adminhelper-agent/packaging_pkg_test.go`, `scripts/tests/box_freebsdbox.sh`.

## Datenmodell / API / Migrationen
Keine. Die Report-Felder gibt es schon (Linux); das Monitoring wertet sie betriebssystemunabhängig aus.

## Externe Integrationen
- daemon(8), FreeBSD 15.0: `-o` hängt die Ausgabe an eine Datei an und legt sie mit 0600 an, `-H` öffnet sie auf
  SIGHUP neu („for interoperability with newsyslog(8)“). Ohne `-S` und ohne syslog-Optionen geht nichts ins syslog.
  https://man.freebsd.org/cgi/man.cgi?query=daemon&sektion=8&manpath=FreeBSD+15.0-RELEASE
- newsyslog.conf(5): Felder `logfile owner:group mode count size when flags pid_file [signal]`, Standardsignal
  SIGHUP an die PID aus `pid_file`; `/etc/newsyslog.conf` bindet `/usr/local/etc/newsyslog.conf.d/[!.]*.conf` ein.
  https://man.freebsd.org/cgi/man.cgi?query=newsyslog.conf&sektion=5&manpath=FreeBSD+15.0-RELEASE
- gopsutil v4.26.10: `mem.SwapMemory` liest unter FreeBSD `vm.swap_info`, `cpu.Counts` die sysctl-Werte.

## Trade-offs & Alternativen
- Log weiter ins syslog, nur mit eigener Facility: braucht eine Änderung an `/etc/syslog.conf` des Hosts. Verworfen.
- `daemon -o` mit `-H` und einem newsyslog-Eintrag, der dem daemon-Supervisor (`-P`-Pidfile) SIGHUP schickt:
  Bordmittel, keine Host-Konfiguration außer einer Datei im Paket. Empfehlung.
- Das rc-Skript legt `/var/log/adminhelper` (0700) vor dem Start an, falls der Agent es noch nicht angelegt hat.

## Risiken & Rollback
Ein falsches Pidfile im newsyslog-Eintrag ließe frpc nach der Rotation in die umbenannte Datei schreiben (laut,
keine Datenverluste). Der FreeBSD-Box-Lauf prüft Datei, Modus und Rotation. Rollback: Revert.

## Doku-Impact
`docs/admin/agent-deployment.html` DE+EN (Logs: frpc unter FreeBSD), `docs/developer/monitoring.html` DE+EN
(`resources.cpu_count`/Swap: Linux und FreeBSD), CHANGELOG-Fragment.

## Offene Fragen
Keine.
