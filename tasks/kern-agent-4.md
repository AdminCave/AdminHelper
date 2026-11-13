<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent: Härtung von Probe-Wächter und Dateizugriff der Fühler — Task-Ledger
Status: aktiv · Branch: feature/kern-agent-4 · Review: pro Task
Spec: docs/features/kern-agent-4.md (Roadmap R-1425, R-1426, R-1427, R-1428, R-1430)
Heavy: linux-full — Wächter und Fühler des Agents (`apps/agent`), Docker-Ports auf echten Boxen; kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Jede Task: `security` parallel zum `reviewer` (SEC-Zug).

### T1 — R-1426: weitere Weiterleiter und Super-Server im Wächter  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go
Änderung: `forwarders`/`forwarderNames` um die Namen aus der Zeile ergänzen (ganze Namen dort, wo ein Präfix fremde
Programme träfe); Super-Server mit eigenem Listener in `judgeListener` wie die Aktivatoren behandeln. Tabellentests
je Name, dazu Negativtests für Namen, die nicht treffen dürfen.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T6

### T2 — R-1425: frische Zielprüfung vor dem Versand eines Geheimnisses  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/probe/target.go, apps/agent/internal/probe/target_linux.go, apps/agent/internal/probe/sensor_http.go, apps/agent/internal/probe/app_bbb.go, apps/agent/internal/probe/app_bbb_test.go
Änderung: Der Wächter bekommt eine Option für Verbindungen mit Geheimnis: `control` urteilt dann auf einem höchstens
`listenerFresh` alten Snapshot und verlangt, dass der Listener auf Adresse und Port die Regel erfüllt, mit der
`resolve` das Ziel gefunden hat. `bbbMeetings` und `fetch` mit Zugangsdaten nutzen sie. Tests: Listenerwechsel
zwischen `resolve` und Versand wird abgewiesen, ohne Geheimnis unverändert.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T6

### T3 — R-1427: Prozess hinter einem veröffentlichten Docker-Port prüfen  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/probe/sensor_local.go, apps/agent/internal/probe/netns_linux.go, apps/agent/internal/probe/netns_other.go, apps/agent/internal/probe/netns_linux_test.go
Änderung: `publication` trägt die PID des Containers (`State.Pid`); neue Naht `containerListeners` (Linux:
`/proc/<pid>/net/tcp{,6}` im Namespace des Containers, Inode → Prozess über `/proc/*/fd` der Prozesse desselben
Namespace; sonst nicht unterstützt). `checkPublished` und `checkProxy` beurteilen den Prozess auf dem Container-Port
wie einen Listener des Hosts; nicht ermittelbar → abweisen. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T6

### T4 — R-1428: Dateien der Fühler über einen Pfad-Deskriptor öffnen  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_local.go, apps/agent/internal/probe/sensor_local_linux.go, apps/agent/internal/probe/sensor_local_freebsd.go, apps/agent/internal/probe/sensor_local_windows.go, apps/agent/internal/probe/sensor_local_linux_test.go, apps/agent/internal/probe/sensor_local_freebsd_test.go, apps/agent/internal/probe/app_bbb.go, apps/agent/internal/probe/app_bbb_unix_test.go
Änderung: gemeinsamer Helfer nach dem Muster `openRegular`: als Pfad öffnen, `fstat` regulär und
`refuseKernelFile` am Pfad-Deskriptor, dann genau diesen zum Lesen öffnen (Linux `/proc/self/fd`, FreeBSD
`O_EMPTY_PATH` mit Werten aus `sys/sys/fcntl.h`, Windows wie bisher). `readSmallFile` und `readCapped` nutzen ihn;
`countFailMarkers` liest die mtime per `Fstatat(…, AT_SYMLINK_NOFOLLOW)` am Verzeichnis. Tests: Gerät, FIFO und
Link-Tausch werden nie zum Lesen geöffnet.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T6

### T5 — R-1430: Invariante der LDAP-Ansicht im Doc-Kommentar  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/app_ldap.go
Änderung: Doc-Kommentar von `ldapReplication` nennt: nur Search, feste Attribute, die `namingContexts` der
Root-DSE werden Base der `contextCSN`-Suchen (Scope base), sonst fließt nichts aus Antworten in Folgeanfragen.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (nur Code-Kommentar)

### T6 — Doku: Wächter und Dateizugriff der Fühler  [ ]
Komponente: scripts · Dateien: docs/developer/agent.html, docs/en/developer/agent.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-agent-4.md
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
