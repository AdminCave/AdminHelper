<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent: Wächter, Listener-Liste und Discovery — Task-Ledger
Status: aktiv · Branch: feature/kern-agent-6 · Review: pro Task
Spec: docs/features/kern-agent-6.md (Roadmap R-1440, R-1441, R-1442, R-1447, R-1516)
Heavy: linux-full — Wächter, Listener-Leser und Discovery des Agents (`apps/agent`) auf echten Boxen; dazu vor dem Merge `freebsd_box.sh` (FreeBSD-Plattformcode und R-1442); kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Jede Task mit Wächter-Bezug (T1–T4): `security` parallel zum `reviewer`. Einzelheiten zu T2–T4 nur in
`tasks/private/sec-kern-agent-6-notes.md`.

### T1 — R-1441: lauschende Sockets unter Linux mit allen Prozessen lesen  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/listen_linux.go, apps/agent/internal/probe/listen_linux_test.go, apps/agent/internal/probe/listen_gopsutil.go, apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/probe/target.go, apps/agent/internal/probe/target_test.go, apps/agent/internal/probe/sensor_local_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @704f89b89 2026-11-16T18:12:57+01:00
Review: approve (.ah-out/review/kern-agent-6/T1.verdict.json)
Beweis: gopsutil v4 `net/net_linux.go` `connectionDedupKey` ohne PID (reviewer kern-agent-4 T2 2026-11-13)
Änderung: Neuer Leser `listen_linux.go` (SPDX) für `/proc/net/tcp` und `tcp6` (LISTEN-Zeilen, Adresse, Port, Inode,
UID nach proc_pid_net(5)) und eine Inode-Zuordnung über `/proc/<pid>/fd`; ein Listener trägt alle PIDs, die die
Socket halten. `listen_gopsutil.go` bleibt nur für Windows. Der Wächter urteilt über alle PIDs (ein Aktivator neben
dem Dienst entscheidet unabhängig von der Reihenfolge). Erst der rote Test: eine Socket, die zwei Prozesse halten.
Gegenprobe im Test: dieselben Adressen und Ports wie gopsutil auf dem Testhost.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (internes Lesen, Verhalten nur in der Reihenfolge-Abhängigkeit korrigiert)

### T2 — R-1440: Härtung des Wächters für Fühler mit Zugangsdaten (Linux, FreeBSD)  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/probe/target.go, apps/agent/internal/probe/target_test.go, apps/agent/internal/probe/listen_freebsd.go, apps/agent/internal/probe/sockstat.go, apps/agent/internal/probe/sockstat_test.go
Abhängt von: T1
Änderung: Regel nach Kevins Entscheidung vom 2026-11-16 (privat). Gilt für jeden Aufrufer von `secretGuard`
(http, proto/redis, App-Views); unit- und container-Ziele unverändert. Tabellentests je Zielart mit und ohne
Zugangsdaten, fail-closed bei unlesbarer Eigenschaft.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T7

### T3 — R-1440: dieselbe Härtung unter Windows  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/guard_windows.go, apps/agent/internal/probe/guard_windows_test.go, apps/agent/internal/probe/guard_other.go
Abhängt von: T2
Änderung: Windows-Gegenstück der Regel aus T2 (privat); Windows-Konten nach Microsoft Learn „Security identifiers“.
Verifiziert im CI-Job `agent-windows`; lokal nur Build und Lint.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T7

### T4 — R-1440: dieselbe Härtung für Unix-Sockets  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_local.go, apps/agent/internal/probe/sensor_local_linux.go, apps/agent/internal/probe/sensor_local_linux_test.go, apps/agent/internal/probe/sensor_local_freebsd.go, apps/agent/internal/probe/sensor_local_freebsd_test.go
Abhängt von: T2
Änderung: Unix-Socket-Fühler mit Zugangsdaten folgen derselben Regel über die Peer-Credentials (privat).
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T7

### T5 — R-1442: Probe-Tests als Box-Nutzer unter FreeBSD  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/app_bbb_test.go, apps/agent/internal/probe/app_bbb_unix_test.go, apps/agent/internal/probe/app_proxy_test.go
Beweis: kern-agent-4 T4 2026-11-13, `freebsd_box.sh` (62 passed, 1 failed, Phase tests internal/probe); Gegenprobe
origin/main@1ece3d3e6, Testbinary als Box-Nutzer `-run MeetingsView|CaddyUpstreams`: 9 FAIL mit `getcred: operation
not permitted` · Dedup-Key: BUG:agent:freebsd-box:probe-getcred-user-phase
Änderung: Die BBB-Meetings- und Caddy-Upstream-Tests prüfen ihre View, nicht den Kernel: sie setzen den Wächter über
die Test-Naht (`peerSocket` wie `stubHost` in `guard_test.go`), statt `net.inet.tcp.getcred` zu fragen. Der echte
Weg bleibt in den Root-Tests (`PROBE_ROOT_TESTS`). Beleg: `freebsd_box.sh` grün (Heavy, vor dem Merge).
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (nur Tests)

### T6 — R-1447: Discovery meldet bei mehr als 64 lauschenden Ports „unbekannt“  [ ]
Komponente: agent · Dateien: apps/agent/internal/discovery/discovery.go, apps/agent/internal/discovery/discovery_test.go
Beweis: kern-monitoring-29 Abschlussprüfung 2026-11-13 · Dedup-Key: bug:agent:discovery:listening-cap
Änderung: `listeningIn` (`discovery.go:398`) gibt über `maxContainerPorts` `nil` zurück statt der ersten 64; der
Monitoring-Server nimmt dann die exponierten Ports (`module_sync.py` `_seen_ports`). Der Test „busy“
(`discovery_test.go:930`) erwartet künftig `nil`; erst rot.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T7

### T7 — Doku und Changelog  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-agent-6.md
Abhängt von: T2, T3, T4, T6
Änderung: Monitoring-Seite DE+EN: die Regel für Fühler mit Zugangsdaten und ihr Ausweg (Unit- oder Container-Ziel),
die Discovery-Ports „unbekannt“ ab 64. `changelog.d/kern-agent-6.md` (SPDX) neutral: Härtung, Fixes.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/monitoring.html · docs/en/admin/monitoring.html · changelog.d/kern-agent-6.md
Task-Review: am Ende

### T8 — R-1516: docker ps + inspect an einer Stelle  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/app_nextcloud_aio.go, apps/agent/internal/probe/sensor_local.go, apps/agent/internal/probe/app_wordpress_cron.go, apps/agent/internal/probe/app_nextcloud_aio_test.go, apps/agent/internal/probe/sensor_local_test.go, apps/agent/internal/probe/app_wordpress_cron_test.go
Änderung: `dockerPublications` (`sensor_local.go:267`) und `wpDBContainer` (`app_wordpress_cron.go:328`) nutzen
`inspectAllContainers` (`app_nextcloud_aio.go:114`); die Behandlung verschwundener Container steht nur noch dort.
Refactor: Suite grün vorher und nachher, Fehlerpfade durch Bestandstests gedeckt.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (internes Refactoring)

## Entscheidungen
- 2026-11-16 R-1448 (FreeBSD-rc.d-Dienste als Units) fährt im Zug `tasks/kern-agent-7.md`: braucht eine Namensregel
  zwischen Agent-Discovery und den Unit-Namen der Monitoring-Module (`haproxy.service`), also Agent und Monitoring.
- 2026-11-16 R-1441: eigener `/proc/net/tcp`-Leser statt Patch an gopsutil (Spec, Trade-offs).
- 2026-11-16 R-1440: Lesarten der Regel stehen in `tasks/private/sec-kern-agent-6-notes.md`.
