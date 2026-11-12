# kern-monitoring-24 — Probe-Guard des Agents und Adressregel der zentralen Checks nachziehen

Roadmap: R-1374, R-1370, R-1376 (Agent), R-1381, R-1382 (Monitoring-Dienst). Abgespalten: R-1401 (rebaseline,
überlappt `feature/arch-monitoring-ui-3`), R-1402 (FreeBSD-Gegenstück zu T3, braucht eine FreeBSD-VM).

## Problem / Motivation
- **R-1374:** Eine Probe auf eine eigene Adresse des Hosts verbindet heute auch zu einem Port, auf dem kein Prozess
  lauscht. Der Guard kann dann nicht prüfen, wer die Verbindung annimmt.
- **R-1370:** Der Guard prüft den Listener vor dem Verbindungsaufbau. Was danach mit der Verbindung geschieht
  (Weiterleitung im Kernel, Weiterleitung über einen Windows-Systemdienst, weitere Weiterleiter-Programme), sieht er
  nicht.
- **R-1376:** Die Probe an einen Unix-Socket prüft den Prozess dahinter, aber nicht, ob er ein Weiterleiter ist.
- **R-1381:** Zwei Nits der zentralen Checks: die Delegationsprüfung (`dns.py`) fragt eine Adresse, die mehrere
  Nameserver teilen, je Nameserver erneut und läuft so in die Abstandsgrenze; RDAP (`rdap.py`) folgt keiner
  Weiterleitung der Registry (RFC 7480 §5.2).
- **R-1382:** Die Adressregel der zentralen Checks packt eingebettetes IPv4 nur aus dem Well-Known-Prefix
  `64:ff9b::/96` aus; ein NAT64-Präfix des Betreibers (RFC 6052) kennt sie nicht.

## Ziel & Nicht-Ziele
Ziel: Eine Probe erreicht nur den Prozess, den der Guard geprüft hat. Die zentralen Checks bewerten Adressen auch in
IPv6-only-Umgebungen mit eigenem NAT64-Präfix richtig. Die Kosten bleiben klein: ein Netlink-Lookup je Verbindung,
keine Prozess-Starts, keine neuen Rechte.

Nicht-Ziele: Konfigurationen von Proxys auswerten (nginx, haproxy); Verbindungen, die eBPF vor dem connect umschreibt;
FreeBSD-Gegenstück zu T3 (R-1402); `rebaseline` (R-1401).

## Betroffene Komponenten & Dateien
- Agent (`apps/agent/internal/probe/`): `guard.go`, `guard_test.go`, neu `peer_linux.go` und `peer_other.go`
  (Lookup nach dem connect), `sensor_local_linux.go`, `sensor_local_freebsd.go` samt Tests, `listen_gopsutil.go` bzw.
  eine neue `guard_windows.go` (Windows-Dienst-PID).
- Monitoring (`apps/monitoring/app/central/`): `dns.py`, `rdap.py`, `net.py`, `resolve.py` samt Tests.

## Datenmodell / API / Migrationen
Keine. Neue Meldung im Check-Ergebnis: `no process listens on port N` (Kevin 2026-11-12, Check rot).

## Externe Integrationen
- Linux `sock_diag` (man 7 sock_diag, `SOCK_DIAG_BY_FAMILY` mit `inet_diag_req_v2`) über `golang.org/x/sys/unix`;
  vor dem Bau die man-Page lesen.
- Windows Service Control Manager (`svc.Status.ProcessId`, schon genutzt in `sensor_local_windows.go`).
- RFC 7050 (Erkennung des NAT64-Präfixes über `ipv4only.arpa`, AAAA, 192.0.0.170/171), RFC 6052 §2.2 (Präfixlängen
  32/40/48/56/64/96, u-Oktett Bits 64–71), RFC 7480 §5.2 (RDAP-Weiterleitungen).

## Trade-offs & Alternativen
- T3: Lookup über `/proc/net/tcp{,6}` statt `sock_diag` ist ohne Netlink möglich, liest aber je Verbindung alle
  Sockets als Text. Conntrack-Abfragen brauchen `CAP_NET_ADMIN`. Empfehlung: `sock_diag`, Exakt-Lookup.
- T4: Die Weiterleitungstabelle des Windows-Dienstes steht nur undokumentiert in der Registry; die netsh-Ausgabe ist
  lokalisiert. Empfehlung: die PID des Dienstes mit der PID am Listener vergleichen. Teilt sich der Dienst einen
  Prozess mit anderen, gilt die Sperre auch für diese (fail-closed).
- T6: Ein Präfix per Konfiguration statt Erkennung lässt die Voreinstellung offen. Empfehlung: RFC-7050-Erkennung
  über den System-Resolver, gecacht. Ein erkanntes Präfix kann die Regel nur verschärfen: eine gefälschte Antwort
  erzeugt höchstens falsche „nicht öffentlich“-Ergebnisse.

## Risiken & Rollback
- T1 und T3 können legitime Probes ablehnen (Port ohne Listener; Verbindung, deren Gegenstelle der Lookup nicht
  findet). Beides ist gewollt fail-closed und als Meldung sichtbar. Rollback: Revert des Task-Commits.
- T3 hängt am Kernel-Interface; ein Kernel ohne `inet_diag` lehnt jede TCP-Probe auf eine eigene Adresse ab.
  Das trägt die Meldung.

## Doku-Impact
`docs/admin/monitoring.html` und `docs/en/admin/monitoring.html`, Abschnitt „Nur dieser Host“ (Listener-Pflicht,
weitere Weiterleiter, Unix-Sockets); die Abschnitte der zentralen Checks zu RDAP und Adressregel. Dazu
`changelog.d/kern-monitoring-24.md`.

## Offene Fragen
- Restrisiko Proxys auf Anwendungsebene vor gesperrten Diensten: an Kevin (Gate).
