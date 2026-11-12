<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Proben-Wächter: Prüfung nach dem Verbindungsaufbau auch unter FreeBSD

Roadmap: R-1402 (Zug `kern-freebsd-3`; R-1332 fährt wegen Überschneidung mit `feature/arch-monitoring-ui-3` in
`kern-freebsd-4`).

## Problem / Motivation
Seit kern-monitoring-24 prüft der Agent unter Linux nach dem Verbindungsaufbau, welcher Socket die Verbindung
angenommen hat (`checkTaker` in `apps/agent/internal/probe/guard.go`, `peerSocket` über `sock_diag` in
`peer_linux.go`). Auf allen anderen Systemen meldet `osPeerSocket` (`peer_other.go`) `errPeerUnsupported`, und der
Wächter verlässt sich nur auf seine Prüfungen vor dem Verbindungsaufbau. Unter FreeBSD lässt sich die Frage ebenso
beantworten. Einzelheiten unter `tasks/private/`.

## Ziel & Nicht-Ziele
- Ziel: `osPeerSocket` für FreeBSD über die Sysctls `net.inet.tcp.getcred` / `net.inet6.tcp6.getcred`: gibt es einen
  verbundenen Socket mit genau den Enden (lokal = Ziel der Probe, entfernt = Quelle des Agents), ist es
  `peerConnected`; `ENOENT` heißt `peerNone`; jeder andere Fehler weist ab wie unter Linux.
- Nicht-Ziel: Windows (kein gleichwertiger Weg), weitere Weiterleiter (R-1407), Änderung von `redirectTTL` oder der
  Merkregel (R-1409).

## Betroffene Komponenten & Dateien
- `apps/agent/internal/probe/peer_freebsd.go` (neu), `peer_freebsd_test.go` (neu), `peer_other.go` (Build-Tag
  `!linux && !freebsd`).
- Doku: `docs/admin/monitoring.html:465` und EN (Satz „Unter Linux prüft er nach dem Verbindungsaufbau …“),
  `docs/developer/agent.html:164` und EN (`checkTaker`), `changelog.d/kern-freebsd-3.md`.

## Datenmodell / API / Migrationen
Keine. Kein Wire-Format, keine Konfiguration.

## Externe Integrationen
FreeBSD-Kernel, `sys/netinet/tcp_subr.c` (releng/15.0), `tcp_getcred`/`tcp6_getcred`: Eingabe `struct
sockaddr_in[2]` bzw. `sockaddr_in6[2]`, `addrs[0]` lokal, `addrs[1]` entfernt (`in_pcblookup(&V_tcbinfo,
addrs[1]…, addrs[0]…, INPLOOKUP_RLOCKPCB, NULL)`), Ports in Netzwerk-Byte-Reihenfolge, Ausgabe `struct xucred`,
nicht gefunden `ENOENT`, Recht `PRIV_NETINET_GETCRED` (root; in einer Jail erlaubt, `kern_jail.c`
`prison_priv_check`). Ohne `INPLOOKUP_WILDCARD` findet `in_pcblookup` nur verbundene PCBs mit genau diesem
Vier-Tupel (`in_pcb.c`, `in_pcblookup_exact`), nie den Listener. Ein v4-mapped Paar fragt `tcp6_getcred` über
die v4-Tabelle ab. Aufruf über `SYS___SYSCTLBYNAME` (`golang.org/x/sys/unix`, FreeBSD ab 12).
Der Agent läuft unter FreeBSD als root (Cron-Eintrag von root, `service_freebsd.go`).

## Trade-offs & Alternativen
- `sockstat -c` parsen: ein Prozessaufruf je Probe, teurer und weniger genau; verworfen.
- `net.inet.tcp.pcblist` ganz lesen: ganze Tabelle je Probe; verworfen (Kosten, monitoring-no-service-impact).
- getcred: ein Syscall, exakte Abfrage. Empfehlung.

## Risiken & Rollback
- Läuft der Agent wider Erwarten nicht als root, weist der Wächter jede Probe auf eigene Adressen ab (wie unter
  Linux bei einem Fehler von `sock_diag`): sichtbar als rote Checks. Rollback: Revert des Task-Commits.
- Wettlauf: der Socket entsteht beim Server erst mit dem ACK; `checkTaker` fragt bis zu `peerTries` mal.
- Beweis nur auf echtem FreeBSD: die Tests laufen als root auf der Pool-Box, mit einer Gegenprobe über eine
  Umleitung im Paketfilter.

## Doku-Impact
Admin-Doku Monitoring (DE+EN): „Unter Linux“ → „Unter Linux und FreeBSD“; Entwickler-Doku Agent (DE+EN):
`checkTaker` nennt `peer_freebsd.go`; Changelog-Fragment.

## Offene Fragen
- Die root-Tests von `internal/probe` in die Phase `roottests` von `scripts/tests/box_freebsdbox.sh` aufnehmen
  (Harness-Pfad, Kevins Wort). Empfehlung: ja. Bis dahin fährt die Session sie von Hand auf der Box.
