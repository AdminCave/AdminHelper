<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent: Wächter, Listener-Liste und Discovery — Task-Ledger
Status: bereit · Branch: feature/kern-agent-6 · Review: pro Task
Spec: docs/features/kern-agent-6.md (Roadmap R-1440, R-1441, R-1442, R-1447, R-1516)
Heavy: linux-full — Wächter, Listener-Leser und Discovery des Agents (`apps/agent`) auf echten Boxen; dazu vor dem Merge `freebsd_box.sh` (FreeBSD-Plattformcode und R-1442); kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Jede Task mit Wächter-Bezug (T1–T4, T9, T10): `security` parallel zum `reviewer`. Einzelheiten zu T2–T4 nur in
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

### T2 — R-1440: Härtung des Wächters für Fühler mit Zugangsdaten (Linux, FreeBSD)  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/probe/target.go, apps/agent/internal/probe/target_test.go, apps/agent/internal/probe/listen_freebsd.go, apps/agent/internal/probe/sockstat.go, apps/agent/internal/probe/sockstat_test.go, apps/agent/internal/probe/listen_linux.go, apps/agent/internal/probe/listen_linux_test.go, apps/agent/internal/probe/listen_gopsutil.go, apps/agent/internal/probe/sensor_net_test.go, apps/agent/internal/probe/sensor_proto_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @059fb6b75 2026-11-16T18:25:32+01:00
Review: approve (.ah-out/review/kern-agent-6/T2.verdict.json)
Abhängt von: T1
Änderung: Regel nach Kevins Entscheidung vom 2026-11-16 (privat). Gilt für jeden Aufrufer von `secretGuard`
(http, proto/redis, App-Views); unit- und container-Ziele unverändert. Tabellentests je Zielart mit und ohne
Zugangsdaten, fail-closed bei unlesbarer Eigenschaft.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T7

### T9 — R-1440: dieselbe Regel für die Socket, die die Verbindung annimmt (Linux, FreeBSD)  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/probe/peer_linux.go, apps/agent/internal/probe/peer_linux_test.go, apps/agent/internal/probe/peer_freebsd.go, apps/agent/internal/probe/peer_freebsd_test.go, apps/agent/internal/probe/peer_other.go, apps/agent/internal/probe/listen_linux.go, apps/agent/internal/probe/listen_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @e06ab71c3 2026-11-16T19:37:28+01:00
Review: approve (.ah-out/review/kern-agent-6/T9.verdict.json)
Abhängt von: T2
Beweis: security-Prüfung T2 2026-11-16 (privat)
Änderung: Die Prüfung nach dem Verbindungsaufbau wendet die Regel aus T2 auch auf die Socket an, die die Verbindung
angenommen hat (Einzelheiten privat). Erst der rote Test.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T7

### T3 — R-1440: dieselbe Härtung unter Windows  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard_windows.go, apps/agent/internal/probe/guard_windows_test.go, apps/agent/internal/probe/listen_gopsutil.go, apps/agent/internal/probe/listen_windows.go, apps/agent/internal/probe/listen_table.go, apps/agent/internal/probe/listen_table_test.go, apps/agent/internal/probe/peer_other.go, apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @d87be0650 2026-11-16T19:54:02+01:00
Review: approve (.ah-out/review/kern-agent-6/T3.verdict.json)
Abhängt von: T2
Änderung: Windows-Gegenstück der Regel aus T2 (privat); Windows-Konten nach Microsoft Learn „Security identifiers“.
Verifiziert im CI-Job `agent-windows`; lokal nur Build und Lint.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T7

### T10 — R-1440: Windows-Zeitvergleich mit Abstand  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard_windows.go, apps/agent/internal/probe/guard_windows_test.go, apps/agent/internal/probe/listen_table.go, apps/agent/internal/probe/listen_table_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @8c11ffc78 2026-11-16T20:00:45+01:00
Review: approve (.ah-out/review/kern-agent-6/T10.verdict.json)
Abhängt von: T3
Beweis: security-Prüfung T3 Runde 2 2026-11-16 (privat)
Änderung: Der Zeitvergleich aus T3 verlangt einen Abstand statt bloßer Reihenfolge (Einzelheiten privat); fail-closed.
Erst der Test für den Grenzfall.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T7

### T4 — R-1440: dieselbe Härtung für Unix-Sockets  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_local.go, apps/agent/internal/probe/sensor_local_linux.go, apps/agent/internal/probe/sensor_local_linux_test.go, apps/agent/internal/probe/sensor_local_freebsd.go, apps/agent/internal/probe/sensor_local_freebsd_test.go, apps/agent/internal/probe/guard.go, apps/agent/internal/probe/sensor_unixsocket.go, apps/agent/internal/probe/sensor_local_windows.go, apps/agent/internal/probe/sensor_net_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @f3288fa16 2026-11-16T20:11:24+01:00
Review: approve (.ah-out/review/kern-agent-6/T4.verdict.json)
Abhängt von: T2
Änderung: Unix-Socket-Fühler mit Zugangsdaten folgen derselben Regel über die Peer-Credentials (privat).
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T7

### T5 — R-1442: Probe-Tests als Box-Nutzer unter FreeBSD  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/main_freebsd_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @7981f1e04 2026-11-16T20:21:45+01:00
Review: approve (.ah-out/review/kern-agent-6/T5.verdict.json)
Beweis: kern-agent-4 T4 2026-11-13, `freebsd_box.sh` (62 passed, 1 failed, Phase tests internal/probe); Gegenprobe
origin/main@1ece3d3e6, Testbinary als Box-Nutzer `-run MeetingsView|CaddyUpstreams`: 9 FAIL mit `getcred: operation
not permitted` · Dedup-Key: BUG:agent:freebsd-box:probe-getcred-user-phase
Änderung: Die BBB-Meetings- und Caddy-Upstream-Tests prüfen ihre View, nicht den Kernel: sie setzen den Wächter über
die Test-Naht (`peerSocket` wie `stubHost` in `guard_test.go`), statt `net.inet.tcp.getcred` zu fragen. Der echte
Weg bleibt in den Root-Tests (`PROBE_ROOT_TESTS`). Beleg: `freebsd_box.sh` grün (Heavy, vor dem Merge).
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (nur Tests)

### T6 — R-1447: Discovery meldet bei mehr als 64 lauschenden Ports „unbekannt“  [x]
Komponente: agent · Dateien: apps/agent/internal/discovery/discovery.go, apps/agent/internal/discovery/discovery_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @ffc2d93e1 2026-11-16T20:27:22+01:00
Review: approve (.ah-out/review/kern-agent-6/T6.verdict.json)
Beweis: kern-monitoring-29 Abschlussprüfung 2026-11-13 · Dedup-Key: bug:agent:discovery:listening-cap
Änderung: `listeningIn` (`discovery.go:398`) gibt über `maxContainerPorts` `nil` zurück statt der ersten 64; der
Monitoring-Server nimmt dann die exponierten Ports (`module_sync.py` `_seen_ports`). Der Test „busy“
(`discovery_test.go:930`) erwartet künftig `nil`; erst rot.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T7

### T7 — Doku und Changelog  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-agent-6.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @dac2fb0bc 2026-11-16T20:46:05+01:00
Review: am Ende (nur Doku, Branch-Review)
Abhängt von: T2, T3, T4, T6, T9, T10
Änderung: Monitoring-Seite DE+EN: die Regel für Fühler mit Zugangsdaten und ihr Ausweg (Unit- oder Container-Ziel),
die Discovery-Ports „unbekannt“ ab 64. `changelog.d/kern-agent-6.md` (SPDX) neutral: Härtung, Fixes.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/monitoring.html · docs/en/admin/monitoring.html · changelog.d/kern-agent-6.md
Task-Review: am Ende

### T8 — R-1516: docker ps + inspect an einer Stelle  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/app_nextcloud_aio.go, apps/agent/internal/probe/sensor_local.go, apps/agent/internal/probe/app_wordpress_cron.go, apps/agent/internal/probe/app_nextcloud_aio_test.go, apps/agent/internal/probe/sensor_local_test.go, apps/agent/internal/probe/app_wordpress_cron_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @80d09522f 2026-11-16T20:34:16+01:00
Review: approve (.ah-out/review/kern-agent-6/T8.verdict.json)
Änderung: `dockerPublications` (`sensor_local.go:267`) und `wpDBContainer` (`app_wordpress_cron.go:328`) nutzen
`inspectAllContainers` (`app_nextcloud_aio.go:114`); die Behandlung verschwundener Container steht nur noch dort.
Refactor: Suite grün vorher und nachher, Fehlerpfade durch Bestandstests gedeckt.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (internes Refactoring)

### T11 — Entwickler-Doku des Wächters und Grenzen der Regel  [x]
Komponente: scripts · Dateien: docs/developer/agent.html, docs/en/developer/agent.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @62de16a7f 2026-11-16T21:09:57+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Abschlussprüfung (reviewer branch, wichtig): der Wächter-Absatz der Entwickler-Doku DE+EN nennt den
eigenen Linux-Leser und den Windows-Leser statt gopsutil, streicht den Satz zur ersten PID, nennt die Prüfung der
Listener nach dem Verbindungsaufbau (auch Windows) und die strenge Regel für Ziele mit Zugangsdaten. Monitoring-Seite:
der Bezug von „Einzige Ausnahme von beidem“ eindeutig, die Grenze nennt `mac_portacl` und root in Jail bzw. Container
mit Host-Netz.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/agent.html · docs/en/developer/agent.html · docs/admin/monitoring.html · docs/en/admin/monitoring.html
Task-Review: am Ende

### T12 — R-1442: Box-Nutzer-Tests unter FreeBSD, Rest  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_log_test.go, apps/agent/internal/probe/app_fpm.go, apps/agent/internal/probe/guard_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @fe3f35765 2026-11-16T21:12:33+01:00
Review: approve (.ah-out/review/kern-agent-6/T12.verdict.json)
Beweis: freebsd_box.sh auf feature/kern-agent-6@3023efa92 2026-11-16: `fbsdbox tests: 17 passed, 1 failed` (internal/probe:
TestPoolDirIsThePlaceOfThePackages, TestNginxStatusReadsTheCountersOfItsPlace, TestAnIPv6PlaceIsAskedWithItsAddressInBrackets,
TestNginxStatusWithoutAPlaceOrAPageOfItsForm, TestApacheStatusReadsTheWorkersOfItsPlace, TestGuardChecksTheOwnersOfThePortAfterTheConnect)
Änderung: `stubTools` reicht den `sockstat`-Aufruf des Wächters (FreeBSD liest Listener über `runTool`) an den echten
Runner durch, statt ihn als Antwort der Ansicht zu zählen; `poolDirOf` streicht `.service` nur unter Linux (FreeBSD kennt
nur rc.d-Namen); der Test der Besitzerprüfung nach dem connect verlangt unter FreeBSD kein `Accept` einer abgewiesenen
Verbindung (Go überspringt dort die zurückgesetzte mit `ECONNABORTED`; dass nach dem connect geprüft wurde, belegt
`ownersCalls`).
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (Tests und eine FreeBSD-Randbedingung ohne dokumentiertes Verhalten)

## Entscheidungen
- 2026-11-16 R-1448 (FreeBSD-rc.d-Dienste als Units) fährt im Zug `tasks/kern-agent-7.md`: braucht eine Namensregel
  zwischen Agent-Discovery und den Unit-Namen der Monitoring-Module (`haproxy.service`), also Agent und Monitoring.
- 2026-11-16 R-1441: eigener `/proc/net/tcp`-Leser statt Patch an gopsutil (Spec, Trade-offs).
- 2026-11-16 R-1440: Lesarten der Regel stehen in `tasks/private/sec-kern-agent-6-notes.md`.
- 2026-11-16 R-1442: statt die BBB- und Caddy-Tests einzeln zu stubben ein `TestMain` nur für FreeBSD und Nicht-root
  (`main_freebsd_test.go`): die Gegenprobe zeigte 31 betroffene Tests im Paket, nicht nur die 9 aus dem Beweis.
