<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-4 — Agent: Härtung von Probe-Wächter und Dateizugriff der Fühler

Zug der Kern-Session (Roadmap R-1425, R-1426, R-1427, R-1428, R-1430). Einzelheiten zu den Zeilen stehen nur in
`tasks/private/`.

## Problem
- **R-1425:** Ansichten und Fühler, die dem lokalen Dienst ein Geheimnis mitschicken (`bbb_meetings` in
  `app_bbb.go`, `http` mit Zugangsdaten in `sensor_http.go`), urteilen über das Ziel auf einem Listener-Snapshot,
  der bis `listenerTTL` alt sein darf (`guard.go`). Das Ziel soll unmittelbar vor dem Versand frisch geprüft werden.
- **R-1426:** Die Listen der Weiterleiter (`forwarders`, `forwarderNames` in `guard.go`) und der Aktivatoren in
  `judgeListener` sind unvollständig.
- **R-1427:** Bei einem von Docker veröffentlichten Port prüft der Wächter nur den Container-Port
  (`checkProxy`, `checkPublished`), nicht den Prozess, der im Container lauscht.
- **R-1428:** `readSmallFile` (`sensor_local.go`) und `readCapped` (`app_bbb.go`) prüfen den Pfad und öffnen ihn
  danach erneut per Name; `countFailMarkers` (`app_bbb.go`) liest Metadaten pfadbasiert. Der Weg soll dem von
  `openRegular` (`app_wordpress_linux.go`) folgen: erst als Pfad öffnen, am Deskriptor prüfen, dann diesen
  Deskriptor zum Lesen öffnen.
- **R-1430:** Der Doc-Kommentar von `ldapReplication` (`app_ldap.go`) soll die Invariante der Ansicht festhalten.

## Ziel & Nicht-Ziele
- Ziel (R-1425): Vor dem Versand eines Geheimnisses urteilt der Wächter auf einem höchstens `listenerFresh` alten
  Snapshot und verlangt, dass der Listener auf Adresse und Port noch zum aufgelösten Ziel gehört (dieselbe Regel,
  mit der `resolve` ihn gefunden hat). Gemeinsam für `http` mit Geheimnis und `bbb_meetings`; ohne Geheimnis bleibt
  alles wie heute.
- Ziel (R-1426): weitere Weiterleiter und Super-Server mit eigenem Listener werden abgewiesen; Namen, die nur als
  ganzes Wort eindeutig sind, kommen nach `forwarderNames`.
- Ziel (R-1427): Unter Linux ermittelt der Wächter für einen veröffentlichten Port den Prozess, der im
  Netz-Namespace des Containers auf dem Container-Port lauscht, und beurteilt ihn wie einen Listener des Hosts
  (`neverProbed`, `checkForwarder`). Kann er ihn nicht ermitteln, weist er ab (fail-closed, wie überall im Wächter).
- Ziel (R-1428): `readSmallFile` und `readCapped` öffnen unter Linux nur noch über einen Pfad-Deskriptor und lesen
  genau die geprüfte Datei; `countFailMarkers` liest die mtime am Verzeichnis-Deskriptor ohne Links zu folgen.
  FreeBSD bekommt denselben Weg über `O_PATH`/`O_EMPTY_PATH`, sofern die Konstanten aus den FreeBSD-Quellen belegt
  sind; Windows bleibt unverändert (kein Geräteöffnen per Pfad im selben Sinn).
- Ziel (R-1430): Doc-Kommentar nennt: nur Search, feste Attribute, die `namingContexts` der Root-DSE werden Base der
  `contextCSN`-Suchen (Scope base), sonst fließt nichts aus Antworten in Folgeanfragen.
- Nicht-Ziel: Container-Adressen als Ziel (`contained`) per Namespace prüfen — gleiche Technik, aber eigene Zeile,
  falls gewünscht.
- Nicht-Ziel: neue Ansichten, Änderungen am Server oder an der Wire-Form.

## Betroffene Komponenten & Dateien
Nur `apps/agent` (Komponente `agent`), Paket `internal/probe/`: `guard.go`, `guard_test.go`, `target.go`,
`target_linux.go`, `sensor_http.go`, `app_bbb.go`, `app_bbb_test.go`, `sensor_local.go`, `sensor_local_linux.go`,
`sensor_local_freebsd.go`, `sensor_local_*_test.go`, `app_ldap.go`, dazu eine neue Linux-Datei für die
Namespace-Listener (SPDX-Header). Doku: `docs/developer/agent.html`, `docs/admin/monitoring.html` (DE+EN),
`changelog.d/kern-agent-4.md`.

## Datenmodell / API / Migrationen
Keine. Kein neues Feld, keine Migration, kein Vertrag zwischen Server und Agent.

## Externe Integrationen
- FreeBSD `open(2)` (https://man.freebsd.org/cgi/man.cgi?query=open&sektion=2): `O_PATH` und `O_EMPTY_PATH` stehen
  in der Manpage von 13.2 und 15.1; ab welcher Version genau, sagt die Manpage nicht (nicht verifiziert). `fstat`
  ist auf einem `O_PATH`-Deskriptor erlaubt; zum Lesen öffnet `openat(fd, "", O_EMPTY_PATH | …)`. Ob ein Öffnen
  eines Geräts mit `O_PATH` die Treiber-Routine aufruft, sagt die Manpage nicht (nicht verifiziert).
  `golang.org/x/sys` v0.49.0 führt für FreeBSD weder `O_PATH` noch `O_EMPTY_PATH`; die Werte kommen aus
  `sys/sys/fcntl.h` der FreeBSD-Quellen und werden vor dem Bau dort nachgelesen.
- Linux `proc(5)`: `/proc/<pid>/net/tcp{,6}` zeigt die Sockets des Netz-Namespace von `<pid>`,
  `/proc/<pid>/fd/` die Socket-Inodes eines Prozesses, `/proc/<pid>/ns/net` den Namespace.
- Docker Engine API (`docker inspect`): `State.Pid` des Containers.

## Trade-offs & Alternativen
- R-1425: (a) frischer Snapshot plus Zugehörigkeitsregel im Wächter, oder (b) die annehmende Socket nach dem
  Connect per Inode/PID der cgroup der Unit zuordnen. **Empfehlung (a):** nutzt Snapshot, `resolve` und
  `checkTaker` wie sie sind; das Fenster schrumpft auf `listenerFresh` (1 s) und `checkTaker` belegt danach, dass
  die Verbindung von einer Socket auf genau Adresse und Port angenommen wurde. (b) ist enger, braucht aber je
  Plattform eine eigene Zuordnung von der Peer-Socket zum Prozess.
- R-1427: (a) Listener im Container-Namespace ermitteln und beurteilen, oder (b) jeden veröffentlichten Port
  abweisen, dessen Ziel nicht feststeht. **Empfehlung (a):** (b) würde Container-Proben grundsätzlich brechen. Ein
  nicht ermittelbarer Prozess wird wie bisher abgewiesen.
- R-1428 FreeBSD: ohne belegte Konstanten bleibt FreeBSD auf dem heutigen Weg; die Task hält das dann in
  `## Entscheidungen` fest und legt eine Folgezeile an.

## Risiken & Rollback
- Strengere Prüfung kann Proben ablehnen, die heute durchgehen (etwa ein Container-Port, dessen Prozess nicht
  ermittelbar ist, oder ein kurz nach einem Neustart wechselnder Listener). Das ist gewollt (fail-closed) und zeigt
  sich als `not_allowed` bzw. Fehler der Probe, nie als falsches `ok`.
- Jede Task ist einzeln rücknehmbar (`git revert`).
- Heavy: `linux-full` im Sammellauf (Agent-Monitoring mit Docker auf echten Boxen).

## Doku-Impact
`docs/developer/agent.html` (Abschnitt Wächter, Fühler) und `docs/admin/monitoring.html` (Abschnitt „Nur dieser
Host“) DE+EN: Weiterleiter- und Super-Server-Liste, Prüfung veröffentlichter Docker-Ports, frische Prüfung vor dem
Versand von Zugangsdaten, Dateizugriff der Fühler. Gebündelt in der Doku-Task; dazu `changelog.d/kern-agent-4.md`
(`### Security`, neutral).

## Offene Fragen
Keine aus Kevins Bereich: alle Änderungen härten bestehendes Verhalten fail-closed, ohne API, Migration oder neue
Funktion. Die Empfehlungen oben trifft die Session; sie stehen im Ledger unter `## Entscheidungen`.
