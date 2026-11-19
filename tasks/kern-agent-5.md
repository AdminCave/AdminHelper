<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent: Wächter, Container-Wurzel und http-Fühler — Task-Ledger
Status: erledigt · Branch: feature/kern-agent-5 · Review: pro Task
Spec: docs/features/kern-agent-5.md (Roadmap R-1438, R-1439, R-1519, R-1513, R-1499, R-1517, R-1508)
Heavy: linux-full — Wächter und Fühler des Agents (`apps/agent`); kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Jede Task mit Wächter- oder Risikobezug (T1–T4, T7): `security` parallel zum `reviewer`.

### T1 — R-1438: Namenslisten des Wächters vervollständigen  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @b1c944014 2026-11-16T16:10:12+01:00
Review: approve (.ah-out/review/kern-agent-5/T1.verdict.json)
Änderung: `forwarders`/`forwarderNames`, `activators`/`superServers` und `blockedProcesses` um die Programme aus der
Zeile ergänzen (Details privat); Namen vorher an Handbuch oder Quelle prüfen, ganze Namen dort, wo ein Präfix fremde
Programme träfe. Tabellentests je Name, Negativtests für ähnliche Namen.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T8

### T2 — R-1519: Argumente des Port-Weiterleiters streng lesen  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @86b052117 2026-11-16T16:17:25+01:00
Review: approve (.ah-out/review/kern-agent-5/T2.verdict.json)
Änderung: `pastaPort` liest jede Argumentform, die das Programm anders lesen könnte, als „kein Port bekannt“ und
weist damit ab (fail-closed); Werte von Optionen mit Argument werden übersprungen. Erst die roten Tabellentests.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (gleiche Abweisung wie bisher, nur in mehr Fällen)
Abhängt von: T1

### T3 — R-1439: Super-Server-Regel am Unix-Socket  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/sensor_local_linux.go, apps/agent/internal/probe/sensor_local_freebsd.go, apps/agent/internal/probe/guard_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @6020ac427 2026-11-16T16:24:22+01:00
Review: approve (.ah-out/review/kern-agent-5/T3.verdict.json)
Änderung: `checkPeer` (Linux und FreeBSD) weist einen Unix-Socket ab, den ein Super-Server hält, der je Verbindung
einen Dienst startet (wie systemd und inetd schon heute); die Namen in einer Liste neben `activators`. Tests über die
Namensprüfung.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T8
Abhängt von: T1

### T4 — R-1513: Container-Wurzel an den Container binden  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/app_wordpress.go, apps/agent/internal/probe/app_wordpress_linux.go, apps/agent/internal/probe/app_wordpress_cron.go, apps/agent/internal/probe/app_mail.go, apps/agent/internal/probe/app_proxy.go, apps/agent/internal/probe/app_nextcloud_aio.go, apps/agent/internal/probe/app_wordpress_linux_test.go, apps/agent/internal/probe/app_wordpress_other.go, apps/agent/internal/probe/app_wordpress_test.go, apps/agent/internal/probe/sensor_local_linux.go, apps/agent/internal/probe/sensor_local_freebsd.go, apps/agent/internal/probe/app_mail_test.go, apps/agent/internal/probe/app_nextcloud_aio_test.go, apps/agent/internal/probe/app_proxy_linux_test.go, apps/agent/internal/probe/app_wordpress_cron_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @ec03c65c9 2026-11-16T16:40:12+01:00
Review: approve (.ah-out/review/kern-agent-5/T4.verdict.json)
Änderung: `containerRoot` bekommt die Container-ID, öffnet zuerst `/proc/<pid>` als Verzeichnis, prüft über dieses
Handle die cgroup des Prozesses gegen die ID und öffnet die Wurzel über dasselbe Handle; passt sie nicht, Fehler ohne
Pfad. Test unter Linux mit einem Prozess, dessen cgroup die ID nicht trägt.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (keine sichtbare Änderung, außer einer Abweisung im Wettlauf)

### T5 — R-1499: Stille-Frist der TLS-Erkennung am Budget ausrichten  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_http.go, apps/agent/internal/probe/sensor_net_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @5a2d5a9d5 2026-11-16T16:47:54+01:00
Review: approve (.ah-out/review/kern-agent-5/T5.verdict.json)
Änderung: `speaksTLS` wartet höchstens min(`answerWait`, halbe Restzeit bis zur Frist des Kontexts) (Kevin
2026-11-16, Option B). Erst der rote Test: stiller Klartext-Server, `timeout_s` 1 → Schema http und gesund.
Beweis: feature/kern-monitoring-30@a4a220b9e sensor_http.go speaksTLS (Review kern-monitoring-30 2026-11-14)
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T8

### T6 — R-1517: Body-Grenze im Leser von fetchExpecting  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_http.go, apps/agent/internal/probe/sensor_net_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @07e1df74e 2026-11-16T16:53:58+01:00
Review: approve (.ah-out/review/kern-agent-5/T6.verdict.json)
Änderung: der `data.`-Zweig liest höchstens `maxBodyBytes`+1 über `io.LimitReader` und meldet darüber
`errBodyTooLarge`, unabhängig vom Transport. Erst der rote Test mit einem Client ohne `cappedBody`.
Beweis: feature/kern-monitoring-33@67dcb890c apps/agent/internal/probe/sensor_http.go fetchExpecting
Dedup-Key: bug:agent:sensor_http.go:fetchExpecting
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (Grenze gilt heute schon über den Transport)
Abhängt von: T5

### T7 — R-1508: vHost folgt der Weiterleitung auf seinen eigenen Namen  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/sensor_http.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/probe/sensor_net_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @9a80d6d56 2026-11-16T17:09:58+01:00
Review: approve (.ah-out/review/kern-agent-5/T7.verdict.json)
Änderung: Eine Weiterleitung auf denselben Namen wie der Host-Header des ersten Requests, mit demselben Schema und
Port, geht weiter an die Adresse des ersten Requests (Host und SNI bleiben der Name); alles andere lehnt
`sameTarget` ab wie bisher. Test: vHost leitet auf `https://<name>/login` → 200; Weiterleitung auf anderen Namen
oder Port bleibt abgewiesen.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T8
Abhängt von: T6

### T8 — Doku DE+EN und Changelog  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-agent-5.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @1a0915ffd 2026-11-16T17:21:31+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: „Nur dieser Host“ (Super-Server auch am Unix-Socket, weitere Weiterleiter allgemein benannt), http-Fühler
im Modus `auto` mit kurzem Timeout, vHost-Weiterleitung auf den eigenen Namen; Changelog neutral, umlautfrei.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/monitoring.html docs/en/admin/monitoring.html changelog.d/kern-agent-5.md
Task-Review: am Ende
Abhängt von: T7

### T9 — Abschlussprüfung: Changelog und Frist im TLS-Test  [x]
Komponente: agent · Dateien: changelog.d/kern-agent-5.md, apps/agent/internal/probe/sensor_net_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @460c28b71 2026-11-16T17:36:30+01:00
Review: approve (.ah-out/review/kern-agent-5/T9.verdict.json)
Änderung: Changelog-Eintrag zu R-1517 richtig (1 MiB, Checks mit JSON-Feldern), Aufzählung der Container-Ansichten
mit „etwa“; im Test der Stille-Frist die 200-ms-Frist erst direkt vor `speaksTLS` anlegen (Branch-Review).
Verify: bash scripts/dev/verify.sh agent --strict -- -run '^TestSpeaksTLS' ./internal/probe/
Doku: changelog.d/kern-agent-5.md
Abhängt von: T8

## Entscheidungen
- R-1440 fährt nicht mit (nächster Zug `tasks/kern-agent-6.md`).
- T2: `pastaPort` liest die Optionen wie pasta selbst (getopt-String und Optionsliste aus passt 2025-05-03, Debian
  13, `apt-get download passt`; Optionen enden am ersten Operanden, `+`); jede Form, die eine andere Version anders
  lesen könnte, sagt nichts (fail-closed) statt nur Präfixe `--tcp`/`--c` und Bündel mit `t`/`c` abzulehnen.
- T4: Die cgroup gehört dem Container nur an festen Orten ab der Wurzel: `/docker/<id>`, `/system.slice/docker-<id>.scope`,
  `/machine.slice/libpod-<id>.scope`, `/libpod_parent/libpod-<id>` oder darunter; diese Eltern legt nur root an, ein
  delegierter Teilbaum (Nutzer, Unit, Gast) kann keinen davon tragen. Ein eigenes `--cgroup-parent` und
  rootless-Container öffnen damit nichts (fail-closed). Eine ID, die nicht 64 Hex-Zeichen hat, öffnet nichts. Die
  Wurzel öffnet `os.OpenRoot` über `/proc/self/fd/<n>` des per `openat` geöffneten `root`, `os.Root` folgt dem
  Magic-Link selbst nicht.
- T7: Nur ein vHost-Ziel folgt einer Weiterleitung auf seinen eigenen Namen (`sameVhost`, eigenes `CheckRedirect` des
  Clients im http-Fühler), bei gleichem Schema und Port, an die Adresse des ersten Requests mit dem Namen als
  Host-Header; SNI bleibt der Name. `sameTarget` bleibt unverändert: der Parameter `host=localhost` erweitert keine
  Weiterleitung (bestehender Test). Go entscheidet vor `CheckRedirect`, ob es `Authorization` und Cookies abstreift
  (`net/http/client.go`: Host der URL geändert); nach einem Sprung auf den Namen fehlen sie also, ein eigener Header
  (`use: header`) geht mit, aber nur an dieselbe Adresse.
