# kern-monitoring-24 — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-24 · Review: pro Task
Spec: docs/features/kern-monitoring-24.md (Roadmap R-1374, R-1370, R-1376, R-1381, R-1382)
Heavy: linux-full — apps/agent (Probe-Guard) und apps/monitoring; Windows-Teil prüft der PR-CI-Job agent-windows
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1374: Probe auf eine eigene Adresse nur zu einem Port mit Listener  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/probe/sensor_proto_test.go, apps/agent/internal/probe/sensor_net_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @cb5f09310 2026-11-12T17:55:51+01:00
Review: approve (.ah-out/review/kern-monitoring-24/T1.verdict.json)
Änderung: `checkListener` lehnt ip:port ohne Verbindung ab (`no process listens on port N`), wenn kein Listener des
Snapshots ip:port trägt und `checkPublished` den Port nicht als Docker-Veröffentlichung kennt; Container-Adressen
(`extra`) ausgenommen. Tests über die Seams: kein Listener → kein Dial; Veröffentlichung ohne Listener bleibt erlaubt;
Listener auf der unspezifizierten Adresse trägt jede eigene Adresse; `extra` ohne Listener erlaubt.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T7

### T2 — R-1376, R-1370: Weiterleiter an Unix-Sockets und weitere Weiterleiter-Programme  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/probe/sensor_local_linux.go, apps/agent/internal/probe/sensor_local_freebsd.go, apps/agent/internal/probe/sensor_local_linux_test.go, apps/agent/internal/probe/sensor_local_freebsd_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @38f908dcb 2026-11-12T18:06:26+01:00
Review: approve (.ah-out/review/kern-monitoring-24/T2.verdict.json)
Änderung: Beide `checkPeer` prüfen den Gegenprozess zusätzlich mit der Weiterleiter-Regel (samt exe/argv[0] wie
`checkForwarder`). `forwarders` nimmt weitere reine Weiterleiter auf (systemd-socket-proxyd, sslh, rinetd, redir;
Kernel-Namen auf 15 Zeichen gekürzt, vor dem Bau an den Quellen prüfen). Tests über die Seams je Plattform.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T7

### T3 — R-1370: Gegenstelle nach dem Verbindungsaufbau prüfen (Linux)  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/probe/peer_linux.go, apps/agent/internal/probe/peer_other.go, apps/agent/internal/probe/peer_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @3570e556e 2026-11-12T18:31:25+01:00
Review: approve (.ah-out/review/kern-monitoring-24/T3.verdict.json)
Änderung: `Guard.DialContext` prüft nach dem connect und vor dem ersten Byte per `sock_diag`-Exakt-Lookup, dass die
angenommene Verbindung zu ip:port gehört (keine Listener-Antwort, exakte Socket-ID); sonst Verbindung hart schließen,
`ErrNotAllowed`. Ausnahmen wie T1 (`extra`, Docker-Veröffentlichung). Neue Dateien mit SPDX-Header; Seam
`peerSocket`; Unit-Tests mit Fake (Listener-Antwort, nicht gefunden, fremde ID, Erfolg) und ein echter Linux-Test
(Positivfall; Negativfall im eigenen Netz-Namespace, wenn der Kernel ihn erlaubt — sonst Test im CI-Job belegen).
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T7
Abhängt von: T1

### T4 — R-1370: Weiterleitung über den Windows-Dienst iphlpsvc abweisen  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_windows.go, apps/agent/internal/probe/guard_other.go, apps/agent/internal/probe/guard_windows_test.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/probe/sensor_local_windows.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @1ef015051 2026-11-12T18:39:30+01:00
Review: approve (.ah-out/review/kern-monitoring-24/T4.verdict.json)
Änderung: Unter Windows lehnt `checkListener` einen Port ab, dessen Listener-PID die PID des Dienstes `iphlpsvc`
ist (Dienst-PID über den Service Control Manager, gecacht mit `listenerTTL`). Neue Dateien mit SPDX-Header. Der
Windows-Test legt im CI-Job agent-windows (Admin) eine Portweiterleitung mit netsh an, belegt sie und prüft die
Ablehnung durch den echten Guard; Seam-Test plattformunabhängig.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T7

### T5 — R-1381: Delegationsprüfung je Adresse einmal, RDAP folgt Weiterleitungen  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/central/dns.py, apps/monitoring/app/central/rdap.py, apps/monitoring/tests/test_central_dns.py, apps/monitoring/tests/test_central_rdap.py, apps/monitoring/app/central/fetch.py, apps/monitoring/tests/test_central_fetch.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @fa81b76ad 2026-11-12T17:58:39+01:00
Review: approve (.ah-out/review/kern-monitoring-24/T5.verdict.json)
Änderung: Ein Lauf der Delegationsprüfung fragt jede Adresse höchstens einmal und nutzt die Antwort für alle
Nameserver, die sie teilen. RDAP folgt 301/302/303/307/308 auf eine https-URL, höchstens 3-mal, jedes Ziel wieder
über `fetch.get` (Adressregel je Ziel). Tests: viele Nameserver auf einer Adresse ohne „name server spacing“;
Weiterleitung gefolgt; http-Ziel, private Zieladresse und Schleife enden `unknown`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_dns.py tests/test_central_rdap.py tests/test_central_fetch.py
Doku: → T7

### T6 — R-1382: NAT64-Präfix der Umgebung erkennen (RFC 7050)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/central/net.py, apps/monitoring/tests/test_central_net.py, apps/monitoring/tests/conftest.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @b368287af 2026-11-12T18:11:37+01:00
Review: approve (.ah-out/review/kern-monitoring-24/T6.verdict.json)
Änderung: `effective_address` packt eingebettetes IPv4 auch aus den Präfixen aus, die der System-Resolver für
`ipv4only.arpa` (AAAA, 192.0.0.170/171) liefert, in allen Längen nach RFC 6052 §2.2; Ergebnis gecacht, Fehler der
Erkennung lassen nur das Well-Known-Prefix. Tests: jede Präfixlänge, u-Oktett, kein DNS64, mehrere Präfixe.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_net.py
Doku: → T7

### T7 — Doku und Changelog  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-24.md
Änderung: „Nur dieser Host“ DE+EN: Listener-Pflicht samt Meldung, Prüfung der Gegenstelle (Linux), Windows-Dienst,
weitere Weiterleiter, Unix-Sockets; zentrale Checks: RDAP-Weiterleitungen, NAT64-Präfix. Neutral, ohne Angriffspfad.
Changelog-Fragment.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-24.md
Task-Review: am Ende

## Entscheidungen
- 2026-11-12: `docs/admin/monitoring.html` überschneidet sich mit offenen Branches (arch-monitoring-module-3,
  klein-nachlese-3); die Doku-Task kommt zuletzt und nimmt vorher `origin/main` auf.
- 2026-11-12 (Kevin): Proxys auf Anwendungsebene vor gesperrten Diensten sind hingenommenes Restrisiko; T2 nimmt
  reine L4-Weiterleiter auf, die Doku nennt die Grenze neutral.
- 2026-11-12 (T1): Ein Listener oder eine Docker-Veröffentlichung auf `0.0.0.0` trägt nur IPv4-Ziele, `::` beide;
  gesperrte Prozesse auf einer Wildcard sperren beide Familien. Ein Fehlgriff wird auf einem höchstens 1 s alten
  Snapshot bestätigt (Funde des Task-Prüfers, Nit des security-Prüfers).
- 2026-11-12 (T5): Das Verify nimmt `tests/test_central_fetch.py` mit, weil `HttpAnswer.location` neu ist.
- 2026-11-12 (T6): Die gelernten NAT64-Präfixe prüft `is_global_address`, nicht `effective_address`: nur so
  verschärfen sie die Regel, statt eine Adresse über ihr eingebettetes IPv4 global zu machen. Ein gescheiterter
  Lookup behält die zuletzt gelernten Präfixe (Fund des security-Prüfers).
- 2026-11-12 (T3): Die Prüfung nach dem connect heißt `checkTaker` (`checkPeer` prüft Unix-Sockets); der Seam
  heißt `peerSocket`. Scheitert `sock_diag`, wird abgewiesen; ohne `sock_diag` (nicht Linux) entfällt die Prüfung.
  Eine Weiterleitung ins eigene Netz zeigt sich als Listener-Antwort; das belegt der echte Linux-Test ohne eigenen
  Netz-Namespace. Eine erkannte Umleitung merkt sich der Guard je (ip, port) eine Stunde (`redirectTTL`) und weist
  den Port dann vor dem connect ab, damit der Dienst dahinter keine Verbindungen je Probe-Intervall zählt; ein
  `sock_diag`-Fehler wird nicht gemerkt, er kann vorübergehend sein.
- 2026-11-12 (T4): Der Seam heißt `serviceForwarder`; `queryService` meldet einen fehlenden Dienst als `errNoService`
  (kein Prozess), jeder andere Fehler des Dienst-Managers weist ab. Die Windows-Tests (Seam, TTL, echte
  netsh-portproxy) laufen nur im CI-Job agent-windows; lokal belegt sind Cross-vet und der plattformunabhängige
  Seam-Test.
