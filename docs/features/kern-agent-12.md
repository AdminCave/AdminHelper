# kern-agent-12 — Unix-Socket-Tests des Agents unter FreeBSD ohne Rennen

Roadmap: R-1610 (BUG)

## Problem / Motivation
`TestDialUnixNamesTheProcessServingTheSocket` (`apps/agent/internal/probe/sensor_local_freebsd_test.go`)
war auf der OPNsense-Box als Box-User rot: Der Wächter wurde nur einmal nach der uid gefragt statt
zweimal. Auf der FreeBSD-Box war der Test grün. Der Test-Server schließt jede angenommene Verbindung
sofort. Unter FreeBSD trennt `uipc_close` dabei auch die Client-Seite (`unp_disconnect` setzt
`unp_conn` auf NULL), und ein späteres `getpeername` liefert die namenlose Adresse (`sun_noname`).
`checkPeer` liest den Namen per `getpeername`, bevor es den Wächter fragt. Schließt der Server
zuerst, lehnt `checkPeerName` ab („bound no absolute path“). Ob das passiert, hängt vom Scheduler ab.
LOCAL_PEERCRED ist beim Connect gecacht und bleibt lesbar. Quelle: FreeBSD `sys/kern/uipc_usrreq.c`
(`uipc_peeraddr`, `unp_disconnect`).

## Ziel & Nicht-Ziele
Ziel: Die Test-Server halten jede Verbindung offen, bis der Client sie schließt. Das gilt für alle drei
Accept-Schleifen der Datei. Nicht-Ziel: Produktivcode. Ein echter Dienst, der sofort schließt, wird
weiterhin abgelehnt (fail-closed, gewollt). Linux ist nicht betroffen: Dort behält die Client-Seite
ihren Peer-Verweis.

## Betroffene Komponenten & Dateien
`apps/agent/internal/probe/sensor_local_freebsd_test.go`.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
FreeBSD AF_UNIX (https://github.com/freebsd/freebsd-src/blob/main/sys/kern/uipc_usrreq.c).

## Trade-offs & Alternativen
Ein Retry im Produktivcode bei `sun_noname` würde das Symptom verschieben. Ein fail-closed-Abbruch bei
einer getrennten Verbindung ist richtig.

## Risiken & Rollback
Nur Testcode. Rollback: Revert des Task-Commits.

## Doku-Impact
Keine (nur Testcode).

## Offene Fragen
Keine.
