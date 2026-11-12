# Monitoring: Probe-Ziele, Socket-Pfade, Docker-Erkennung, Meldetext, Testvorlage — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-22 · Review: pro Task
Spec: docs/features/kern-monitoring-22.md (Roadmap R-1319, R-1320, R-1324, R-1321, R-1300, R-1365)
Heavy: linux-full — apps/agent (Probe-Guard) und apps/monitoring (Meldetext); dazu vor dem Merge der FreeBSD-Box-Lauf `bash scripts/tests/freebsd_box.sh` auf der Pool-VM (Socket-Dial unter FreeBSD, T4)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1319: Probe auf eine eigene Host-Adresse nur zu einem Port mit Listener  [?] (Meldung eines Ports ohne Listener: Fehler „no process listens on port N“ (Empfehlung) oder not_allowed?)
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go
Änderung: `checkListener` lehnt ip:port ab, ohne zu verbinden, wenn kein Listener des Snapshots ip:port trägt und
`checkPublished` den Port nicht als Docker-Veröffentlichung kennt; Container-Adressen (`extra`) ausgenommen. Tests
über die Seams: kein Listener → kein Dial; Docker-Veröffentlichung ohne Listener bleibt erlaubt; Listener auf
0.0.0.0 trägt jede eigene Adresse.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T7

### T2 — R-1319: Weiterleiter im Userland ablehnen  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @ecb3f09d1 2026-11-12T10:54:06+01:00
Review: approve (.ah-out/review/kern-monitoring-22/T2.verdict.json)
Änderung: Lauscht auf dem Port ein Weiterleiter ohne erkennbaren Zielport (rootlesskit, rootlessport, slirp4netns,
pasta/passt als Präfix, kube-proxy, socat), lehnt der Guard nur diesen Port ab (`ErrNotAllowed`); erkannt über den
Prozessnamen und `argv[0]` (`processArgs`, reexec). Tests über die Seams je Name und für reexec.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T7

### T3 — R-1324: Docker-Erkennung schließt geschlossen, sobald ein Docker-Daemon läuft  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_local.go, apps/agent/internal/probe/guard.go, apps/agent/internal/probe/sensor_local_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @e58051cf3 2026-11-12T11:06:50+01:00
Review: approve (.ah-out/review/kern-monitoring-22/T3.verdict.json)
Änderung: `dockerSocketServes` meldet auch dann „Docker da“, wenn ein Prozess `dockerd` läuft (gopsutil, über eine
Seam); scheitert dann `docker ps`, lehnt `checkPublished` wie heute ab. Tests: Socket fehlt, dockerd läuft →
geschlossen; weder Socket noch dockerd → offen.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T7

### T4 — R-1320, R-1365: Socket-Verbindung an die geprüfte Datei binden  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/sensor_local_linux.go, apps/agent/internal/probe/sensor_local_freebsd.go, apps/agent/internal/probe/sensor_local_linux_test.go, apps/agent/internal/probe/sensor_local_freebsd_test.go, apps/agent/internal/probe/guard_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @ce89560e9 2026-11-12T11:45:40+01:00
Review: approve (.ah-out/review/kern-monitoring-22/T4.verdict.json)
Änderung: `socketToDial` vergleicht Gerät und Inode des aufgelösten Pfads mit den einzelnen Sockets aus
`controlSockets` (auch unter `/var/run`) und lehnt einen zweiten Namen vor dem Verbinden ab; nach dem Verbinden prüft
`checkPeer` (Linux, FreeBSD) den Namen, den der Server gebunden hat (`getpeername`, `checkPeerName`): relativ,
abstrakt oder in `controlSockets` → `ErrNotAllowed`. Tests: Hardlink auf eine Kontroll-Socket, nach dem Bind
umbenanntes Verzeichnis, relativ gebundener Listener (Linux im Test-Verzeichnis, FreeBSD auf der Box).
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T7

### T5 — R-1300: AST-Test erkennt jede Startform  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/allowlist_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @78c87c465 2026-11-12T11:03:35+01:00
Review: approve (.ah-out/review/kern-monitoring-22/T5.verdict.json)
Änderung: `commandStarts` erkennt zusätzlich ein `exec.Cmd`-Literal (auch `&exec.Cmd{}`), `syscall.ForkExec`,
`syscall.Exec`, `syscall.StartProcess` und dieselben aus `golang.org/x/sys/unix`; `TestCommandStartsSeesAStart`
nimmt jede Form als Gegenprobe auf.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: keine (reiner Test)

### T6 — R-1321: Meldetext zu not_allowed passt zu jedem Grund  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/probe.py, apps/monitoring/tests/test_probe_checker.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @9a29a4136 2026-11-12T10:57:14+01:00
Review: approve (.ah-out/review/kern-monitoring-22/T6.verdict.json)
Beweis: apps/monitoring/app/checkers/probe.py:44 (`"not_allowed": ("unknown", "Target is no address of this host; the agent refused it")`), kern-monitoring-19 T3 2026-11-11 · Dedup-Key: BUG:monitoring:app/checkers/probe.py:_NOT_RUN
Änderung: Der Text wird „The agent refused the target“; den Grund trägt weiter das `error` des Agents. Test zuerst
rot: eine Ablehnung wegen Sperrliste nennt keine fremde Adresse.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_probe_checker.py
Doku: → T7

### T7 — Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-monitoring-22.md
Änderung: Probe-Ziel (Listener-Pflicht, Weiterleiter, Docker-Erkennung, Meldetext) in Admin- und Entwicklerdoku,
neutral; `changelog.d/kern-monitoring-22.md`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende

### T8 — R-1365: OPNsense-Testvorlage und VM-Werkzeug nachgeschärft  [x]
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/opnsense/bootstrap.sh, scripts/vm/tests/test_vm.py, scripts/vm/opnsense/forget-webgui-cert.php
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @c2a677e12 2026-11-12T11:38:30+01:00
Review: approve (.ah-out/review/kern-monitoring-22/T8.verdict.json)
Änderung: `OPNSENSE_CLEAN` quotet den Nutzer (`shlex.quote`); der Clean-Schritt entfernt das beim ersten Boot
erzeugte Web-GUI-Zertifikat, damit jede Lease ein eigenes erzeugt (vorher an der OPNsense-Quelle prüfen); der
Bootstrap pinnt, was er nachlädt, soweit `opnsense-bootstrap` das zulässt, sonst Restrisiko in `tasks/private/`
und `## Entscheidungen`. Tests in `test_vm.py`. Wirkt ab dem nächsten Bake.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Harness, Kommentar im Skript)

## Entscheidungen
- T5: Der AST-Test meldet jeden Wert vom Typ exec.Cmd (Literal, new, Nullwert, Feld), nur ein Zeiger darauf gilt nicht als Start; dazu die Windows-Starts (CreateProcess, CreateProcessAsUser, ShellExecute). Ein roher syscall.Syscall mit SYS_EXECVE bleibt eine genannte Grenze.
- T3: Läuft ein dockerd, ohne dass der Standard-Socket antwortet (rootless, eigener -H), lehnt der Guard jede TCP-Probe auf eigene Adressen ab (fail-closed); Doku in T7.
- T8: Das Core-Archiv, das opnsense-bootstrap lädt, lässt sich nicht pinnen (nur Release-Zweig, kein Commit, kein Hash); Restrisiko in der privaten Notiz. Das Web-GUI-Zertifikat entfernt der Clean-Schritt per PHP aus config.xml und den Backups, geprüft in php:8.3-cli; auf OPNsense wirkt es erst beim nächsten Bake.
- T4: Statt O_PATH/connectat (Advisor: unter Go nicht sauber ohne eigenen Dial) bindet der Guard die Verbindung über zwei Prüfungen an die Datei: Inode-Abgleich vor dem Verbinden, Name des Servers (getpeername, nicht RemoteAddr) danach; kein Schreiben vor der Prüfung. Grenzen: ein Dienst, der seine Socket nach dem Bind umbenennt, und ein relativ oder abstrakt gebundener Server (abgelehnt).
