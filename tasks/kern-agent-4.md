<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent: Härtung von Probe-Wächter und Dateizugriff der Fühler — Task-Ledger
Status: erledigt · Branch: feature/kern-agent-4 · Review: pro Task
Spec: docs/features/kern-agent-4.md (Roadmap R-1425, R-1426, R-1427, R-1428, R-1430)
Heavy: linux-full — Wächter und Fühler des Agents (`apps/agent`), Docker-Ports auf echten Boxen; kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Jede Task: `security` parallel zum `reviewer` (SEC-Zug).

### T1 — R-1426: weitere Weiterleiter und Super-Server im Wächter  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @b7e2ade25 2026-11-13T19:25:45+01:00
Review: approve (.ah-out/review/kern-agent-4/T1.verdict.json)
Änderung: `forwarders`/`forwarderNames` um die Namen aus der Zeile ergänzen (ganze Namen dort, wo ein Präfix fremde
Programme träfe); Super-Server mit eigenem Listener in `judgeListener` wie die Aktivatoren behandeln. Tabellentests
je Name, dazu Negativtests für Namen, die nicht treffen dürfen.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T6

### T2 — R-1425: frische Zielprüfung vor dem Versand eines Geheimnisses  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/probe/target.go, apps/agent/internal/probe/target_linux.go, apps/agent/internal/probe/sensor_http.go, apps/agent/internal/probe/app_bbb.go, apps/agent/internal/probe/app_bbb_test.go, apps/agent/internal/probe/sensor_net_test.go, apps/agent/internal/probe/sensor_proto.go, apps/agent/internal/probe/sensor_proto_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @fe5c8a3ad 2026-11-13T19:41:36+01:00
Review: approve (.ah-out/review/kern-agent-4/T2.verdict.json)
Änderung: Der Wächter bekommt eine Option für Verbindungen mit Geheimnis: `control` urteilt dann auf einem höchstens
`listenerFresh` alten Snapshot und verlangt, dass der Listener auf Adresse und Port die Regel erfüllt, mit der
`resolve` das Ziel gefunden hat. `bbbMeetings` und `fetch` mit Zugangsdaten nutzen sie. Tests: Listenerwechsel
zwischen `resolve` und Versand wird abgewiesen, ohne Geheimnis unverändert.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T6

### T3 — R-1427: Prozess hinter einem veröffentlichten Docker-Port prüfen  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/probe/sensor_local.go, apps/agent/internal/probe/netns_linux.go, apps/agent/internal/probe/netns_other.go, apps/agent/internal/probe/netns_linux_test.go, apps/agent/internal/probe/sensor_local_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @1991e620b 2026-11-13T19:58:50+01:00
Review: approve (.ah-out/review/kern-agent-4/T3.verdict.json)
Änderung: `publication` trägt die PID des Containers (`State.Pid`); neue Naht `containerListeners` (Linux:
`/proc/<pid>/net/tcp{,6}` im Namespace des Containers, Inode → Prozess über `/proc/*/fd` der Prozesse desselben
Namespace; sonst nicht unterstützt). `checkPublished` und `checkProxy` beurteilen den Prozess auf dem Container-Port
wie einen Listener des Hosts; nicht ermittelbar → abweisen. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T6

### T4 — R-1428: Dateien der Fühler über einen Pfad-Deskriptor öffnen  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_local.go, apps/agent/internal/probe/sensor_local_linux.go, apps/agent/internal/probe/sensor_local_freebsd.go, apps/agent/internal/probe/sensor_local_windows.go, apps/agent/internal/probe/sensor_local_linux_test.go, apps/agent/internal/probe/sensor_local_freebsd_test.go, apps/agent/internal/probe/app_bbb.go, apps/agent/internal/probe/app_bbb_unix_test.go, apps/agent/internal/probe/sensor_local_test.go, apps/agent/internal/probe/sensor_local_unix_test.go, apps/agent/internal/probe/app_bbb_unix.go, apps/agent/internal/probe/app_bbb_windows.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @af595889a 2026-11-13T20:25:41+01:00
Review: approve (.ah-out/review/kern-agent-4/T4.verdict.json)
Änderung: gemeinsamer Helfer nach dem Muster `openRegular`: als Pfad öffnen, `fstat` regulär und
`refuseKernelFile` am Pfad-Deskriptor, dann genau diesen zum Lesen öffnen (Linux `/proc/self/fd`, FreeBSD
`O_EMPTY_PATH` mit Werten aus `sys/sys/fcntl.h`, Windows wie bisher). `readSmallFile` und `readCapped` nutzen ihn;
`countFailMarkers` liest die mtime per `Fstatat(…, AT_SYMLINK_NOFOLLOW)` am Verzeichnis. Tests: Gerät, FIFO und
Link-Tausch werden nie zum Lesen geöffnet.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T6

### T5 — R-1430: Invariante der LDAP-Ansicht im Doc-Kommentar  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/app_ldap.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @83dec9acf 2026-11-13T20:33:25+01:00
Review: approve (.ah-out/review/kern-agent-4/T5.verdict.json)
Änderung: Doc-Kommentar von `ldapReplication` nennt: nur Search, feste Attribute, die `namingContexts` der
Root-DSE werden Base der `contextCSN`-Suchen (Scope base), sonst fließt nichts aus Antworten in Folgeanfragen.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (nur Code-Kommentar)

### T6 — Doku: Wächter und Dateizugriff der Fühler  [x]
Komponente: scripts · Dateien: docs/developer/agent.html, docs/en/developer/agent.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-agent-4.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @daa6f5fb1 2026-11-13T20:37:57+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Abschnitte Wächter (Entwickler) und „Nur dieser Host“ (Admin) DE+EN auf den Stand von T1–T4;
CHANGELOG-Fragment `### Security`, neutral.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/agent.html, docs/admin/monitoring.html DE+EN · changelog.d/kern-agent-4.md
Task-Review: am Ende
Abhängt von: T1, T2, T3, T4

## Entscheidungen
- 2026-11-13 Plan: R-1425 über frischen Snapshot plus Zugehörigkeitsregel im Wächter statt Peer-Zuordnung je
  Plattform (Spec, Trade-offs).
- 2026-11-13 Plan: R-1427 ermittelt den Prozess im Container-Namespace; nicht ermittelbar → abweisen; Container-
  Adressen als Ziel bleiben außerhalb (Spec, Nicht-Ziele).
- 2026-11-13 Plan: R-1428 FreeBSD nur mit aus den FreeBSD-Quellen belegten Konstanten; sonst bleibt FreeBSD beim
  heutigen Weg, Folgezeile.
- 2026-11-13 T1: `nc` ganz, dazu die Debian-Varianten über `nc.`/`netcat` (dort heißt der Prozess nach dem
  Alternativen-Ziel); `tsh` ganz (Präfix träfe `tshark`); tcpserver und s6-tcpserver* als Aktivator, nicht als
  Weiterleiter: hält ein gestarteter Dienst die Socket mit, gilt er wie bei inetd.
- 2026-11-13 T2: die Regel liegt als Fabrik im `endpoint` (`owns`), damit der Wächter sie vor dem Versand neu
  baut (der Namens-Cache von `ownedBy` gälte sonst weiter); ein von Docker veröffentlichter Port nimmt keine
  Verbindung mit Geheimnis an; ohne Regel (Loopback, Container-Adresse) zählt nur der frische Snapshot.
  Korrektur zu T1: `comm` ist der Basename des exec-Pfads, über den Alternativen-Link also `nc`; beide Namen
  bleiben abgedeckt.
- 2026-11-13 T2 (Review): auch `proto` mit Passwort (redis AUTH) wählt über den Wächter für Geheimnisse
  (`dialThrough`); `checkOwner` darf zwei Snapshots lesen (Wächter und Besitz), denn beide sind höchstens
  `listenerFresh` alt und ein später hinzugekommener Listener muss die Regel ohnehin erfüllen.
- 2026-11-13 T3: die Prüfung des Prozesses im Container sitzt in `checkPublished` (`checkInside`), das
  `judgeListener` für jeden Port fährt, mit docker-proxy wie ohne; `checkProxy` bleibt die Prüfung des
  Container-Ports aus den Argumenten. Jede lauschende Socket auf dem Container-Port braucht einen gefundenen
  Prozess, sonst Abweisung; das Ergebnis gilt je Container und Port so lange wie der Snapshot, mit dem geurteilt
  wird. Kann der Agent die Deskriptoren fremder Prozesse nicht lesen (ohne root), werden veröffentlichte Ports
  abgewiesen.
- 2026-11-13 T3 (Review): ein docker-proxy gilt nur, wenn Docker Adresse und Port veröffentlicht (`checkProxied`);
  fehlt die Veröffentlichung in der Liste, wird sie einmal frisch gelesen, sonst Abweisung. Eine Container-PID im
  Namespace des Agents gilt als veraltet und wird abgewiesen; der Cache räumt Einträge älter als `listenerTTL`.
- 2026-11-13 T4: `openChecked` je Plattform (Linux `O_PATH` + `reopenChecked` über `/proc/self/fd`, FreeBSD
  `O_PATH` + `openat(…, "", O_EMPTY_PATH)` mit den Werten aus `sys/sys/fcntl.h`, in 13.2 und main gleich;
  `vn_open_vnode` kehrt bei `O_PATH` vor `VOP_OPEN` zurück; Windows wie bisher Stat, Öffnen, Prüfen) ersetzt
  `openNoWait` auf Linux und FreeBSD; `readSmallFile` öffnet über die Naht `openFile`, die der Kontext-Test statt
  `statPath` hält. 11 Dateien statt acht: die Prüfung am Deskriptor und `markerTime` liegen je Plattform. Der Test
  der FIFO-Öffnung ohne Schreiber entfällt mit `openNoWait`; an seine Stelle tritt ein Schreiber, der nur aufwacht,
  wenn der FIFO zum Lesen geöffnet wird.
- 2026-11-13 T4 (Plattform): `freebsd_box.sh` auf FreeBSD 15: die Tests von `openChecked`, `readSmallFile`,
  `readCapped` und den Markern als Box-Nutzer und als root je 15 passed, 0 failed, 0 skipped. Der Lauf selbst ist rot
  (62 passed, 1 failed) durch BBB- und Caddy-Tests, die auf `main` genauso scheitern (R-1442).
