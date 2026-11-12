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

### T2 — R-1319: Weiterleiter im Userland ablehnen  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go
Änderung: Lauscht auf dem Port ein Weiterleiter ohne erkennbaren Zielport (rootlesskit, rootlessport, slirp4netns,
pasta/passt als Präfix, kube-proxy, socat), lehnt der Guard nur diesen Port ab (`ErrNotAllowed`); erkannt über den
Prozessnamen und `argv[0]` (`processArgs`, reexec). Tests über die Seams je Name und für reexec.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T7

### T3 — R-1324: Docker-Erkennung schließt geschlossen, sobald ein Docker-Daemon läuft  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_local.go, apps/agent/internal/probe/guard.go, apps/agent/internal/probe/sensor_local_linux_test.go
Änderung: `dockerSocketServes` meldet auch dann „Docker da“, wenn ein Prozess `dockerd` läuft (gopsutil, über eine
Seam); scheitert dann `docker ps`, lehnt `checkPublished` wie heute ab. Tests: Socket fehlt, dockerd läuft →
geschlossen; weder Socket noch dockerd → offen.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T7

### T4 — R-1320, R-1365: Socket-Verbindung an die geprüfte Datei binden  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/sensor_local_linux.go, apps/agent/internal/probe/sensor_local_freebsd.go, apps/agent/internal/probe/sensor_local_linux_test.go, apps/agent/internal/probe/sensor_local_freebsd_test.go, apps/agent/internal/probe/guard_test.go
Änderung: `dialUnix` öffnet den Socket-Pfad einmal (Linux: O_PATH, Verbindung über `/proc/self/fd/N`; FreeBSD:
Verzeichnis-Deskriptor des aufgelösten Pfads und `connectat(2)`), prüft den aufgelösten Pfad dieses Deskriptors
gegen `controlSockets` und vergleicht Gerät und Inode mit den einzelnen Sockets aus `controlSockets` (auch unter
`/var/run`). Tests: ein Zwischenverzeichnis, das nach der Prüfung getauscht wird, führt nicht zum neuen Ziel; ein
zweiter Name derselben Socket-Datei wird abgelehnt (Linux im Test-Verzeichnis, FreeBSD auf der Box).
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T7

### T5 — R-1300: AST-Test erkennt jede Startform  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/allowlist_test.go
Änderung: `commandStarts` erkennt zusätzlich ein `exec.Cmd`-Literal (auch `&exec.Cmd{}`), `syscall.ForkExec`,
`syscall.Exec`, `syscall.StartProcess` und dieselben aus `golang.org/x/sys/unix`; `TestCommandStartsSeesAStart`
nimmt jede Form als Gegenprobe auf.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: keine (reiner Test)

### T6 — R-1321: Meldetext zu not_allowed passt zu jedem Grund  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/probe.py, apps/monitoring/tests/test_probe_checker.py
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

### T8 — R-1365: OPNsense-Testvorlage und VM-Werkzeug nachgeschärft  [ ]
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/opnsense/bootstrap.sh, scripts/vm/tests/test_vm.py
Änderung: `OPNSENSE_CLEAN` quotet den Nutzer (`shlex.quote`); der Clean-Schritt entfernt das beim ersten Boot
erzeugte Web-GUI-Zertifikat, damit jede Lease ein eigenes erzeugt (vorher an der OPNsense-Quelle prüfen); der
Bootstrap pinnt, was er nachlädt, soweit `opnsense-bootstrap` das zulässt, sonst Restrisiko in `tasks/private/`
und `## Entscheidungen`. Tests in `test_vm.py`. Wirkt ab dem nächsten Bake.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Harness, Kommentar im Skript)

## Entscheidungen
