# kern-monitoring-26 — Probe-Guard des Agents: weitere Weiterleiter, klarere Abweisung nach dem connect

Roadmap: R-1407, R-1409 (Agent). Einzelheiten nur in `tasks/private/`.

## Problem / Motivation
- **R-1407:** Der Guard erkennt Weiterleiter-Programme an ihrem Prozessnamen (`forwarders`, `forwarderNames` in
  `apps/agent/internal/probe/guard.go`). Die Liste kennt weitere reine TCP-Weiterleiter nicht, unter Linux, FreeBSD und
  Windows. Super-Server, die Sockets für andere Dienste halten (xinetd, inetd), behandelt der Guard bei TCP nicht wie
  die Socket-Aktivierung durch systemd.
- **R-1409:** Findet der exakte Lookup nach dem connect (`checkTaker`, `peer_linux.go`) die Socket der Verbindung
  nicht, gilt die Verbindung als umgeleitet: der Port bleibt `redirectTTL` (1 h) gesperrt, und die Meldung nennt eine
  andere Socket. Zwei harmlose Fälle enden genauso: eine volle Accept-Queue des Listeners, und ein Dienst, der die
  Verbindung sofort zurücksetzt. Der Check wird rot mit falscher Ursache und bleibt eine Stunde gesperrt.

## Ziel & Nicht-Ziele
Ziel: Die Liste der Weiterleiter und Aktivatoren deckt die bekannten Programme ab. Nach dem connect unterscheidet
der Guard „umgeleitet“ von „Queue voll“ und „Verbindung schon beendet“; nur „umgeleitet“ wird gemerkt. Kosten wie
heute: kein Prozess-Start, höchstens ein weiterer Netlink- bzw. sysctl-Lookup, nur wenn der erste nichts fand.

Nicht-Ziele: Konfigurationen von Proxys auswerten; frps (R-1375: seine Ports gelten als eigener Dienst); der Cache der
`iphlpsvc`-PID (Nit aus kern-monitoring-24 T4, nicht angreifersteuerbar); FreeBSD-Queue-Stand (getcred liefert ihn
nicht).

## Betroffene Komponenten & Dateien
- Agent (`apps/agent/internal/probe/`): `guard.go` (`forwarders`, `forwarderNames`, `judgeListener`, `checkTaker`,
  `peerState`), `peer_linux.go` (`judgePeer`: Queue-Stand des Listeners aus `inet_diag_msg`), Tests in
  `guard_test.go` und `peer_linux_test.go`.
- Doku: `docs/developer/agent.html` und `docs/en/developer/agent.html` (Absatz „Wächter“), `changelog.d/kern-monitoring-26.md`.

## Datenmodell / API / Migrationen
Keine. Das Ergebnis einer abgewiesenen Probe bleibt `not_allowed`; nur der Fehlertext ändert sich.

## Externe Integrationen
- `sock_diag` / `inet_diag` (Linux, `linux/inet_diag.h`): für eine Socket im Zustand LISTEN tragen `idiag_rqueue`
  die aktuelle Länge der Accept-Queue und `idiag_wqueue` ihr Maximum (Kernel `tcp_diag_get_info`). Vor dem Bau im
  Kernel-Quelltext gegenlesen.
- `net.inet.tcp.getcred` (FreeBSD): findet nur die verbundene Socket mit genau beiden Enden; dieselbe Frage mit
  vertauschten Enden findet die eigene Client-Socket.
- Prozessnamen der neuen Weiterleiter: aus den Paketen bzw. Programmdokumentationen; nicht auf jeder Plattform
  verifiziert, als Präfix gehalten.

## Trade-offs & Alternativen
- Weiterleiter: Namensliste erweitern (empfohlen, wie bisher) statt Ziele aus Konfigurationen lesen (teuer, je
  Programm anders, nicht vollständig).
- Super-Server: als Aktivator werten wie systemd (Listener nur beim Super-Server → abweisen), statt deren
  Konfigurationen zu lesen.
- Queue voll / Verbindung beendet: abweisen ohne Merken, mit eigener Meldung (empfohlen). Alternative „durchlassen“
  verwirft die Umleitungsprüfung genau dann, wenn sie nichts sieht, und ist deshalb verworfen.
- Eigene Client-Socket erst im letzten Versuch prüfen: ein zusätzlicher Lookup nur im seltenen Fall.

## Risiken & Rollback
- Ein harmloses Programm, dessen Name mit einem neuen Präfix beginnt, wird nicht mehr geprüft (`not_allowed`).
  Fail-closed, im Fehlertext sichtbar.
- Eine Umleitung auf einen Dienst, der sofort zurücksetzt, wird nicht gemerkt: jede Probe verbindet erneut, bis zu
  einmal je Probe-Intervall. Einzelheiten und Bewertung privat.
- Rollback: Revert des Merge-Commits; kein Daten- oder Formatwechsel.

## Doku-Impact
`docs/developer/agent.html` DE+EN, Absatz „Wächter“: Super-Server wie Socket-Aktivierung, die zwei neuen
Abweisungsgründe nach dem connect. Dazu `changelog.d/kern-monitoring-26.md`.

## Offene Fragen
Keine aus Kevins Bereich: beide Zeilen sind angenommen (Kevin 2026-11-13), frps folgt R-1375.
