<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-26 — FreeBSD-Dienste: Liste gecacht, Abfrage alle 15 min

Roadmap: R-1706 (REF).

## Problem
Der Kern-Sammler `services` startet unter FreeBSD je Lauf (alle 5 min) `service -e` und danach je eingeschaltetem
rc.d-Skript `service <name> status` (`apps/agent/internal/monitor/rcservice.go`, `rcServiceHealth`). Gemessen am
2026-11-27 auf einer Pool-Box (FreeBSD 15.1, 2 vCPU, 31 eingeschaltete Skripte): 2,2 s und 2,2–2,5 CPU-Sekunden je
Lauf, davon `service -e` allein 0,77 s, jeder `status` etwa 0,05 s.

## Ziel & Nicht-Ziele
Ziel (Kevin 2026-11-28, „Liste cachen“): die Liste aus `service -e` bleibt im Report-State, bis sich eine Datei ändert,
aus der rc(8) die Einschaltung liest; den Dienst-Block (`systemd`: `all_services`, `enabled_inactive`, `counts`) fragt
der Agent unter FreeBSD höchstens alle 15 min neu ab und schickt dazwischen den zuletzt gelesenen. Nicht-Ziele: die
beobachteten Dienste (`watched`, je Lauf wenige Aufrufe) bleiben je Lauf; Linux und Windows bleiben unverändert; kein
Lesen von Pidfiles (nur 5 von 31 Skripten setzen `pidfile=`).

## Betroffene Komponenten & Dateien
`apps/agent/internal/monitor/rcservice.go`, `services_freebsd.go`, `services_linux.go`, `services_windows.go`,
`report.go`, `reportstate.go`, `cycle.go`, Tests `rcservice_test.go`,
`reportstate_test.go` (der Pfad mit den echten `rcConfPaths` nur auf der FreeBSD-Box); Doku
`docs/developer/agent.html`, `docs/en/developer/agent.html`, `changelog.d/kern-agent-26.md`.

## Datenmodell / API
Kein Wire-Format ändert sich: der Report trägt denselben Block, unter FreeBSD bis zu 15 min alt. Neu im lokalen
Report-State (`report-state.json`) ein Feld für den FreeBSD-Cache: Zeitpunkt der letzten Abfrage, Stempel der
rc.conf-Dateien, Skriptliste, letzter Block. Ein State ohne das Feld (älterer Agent) fragt sofort neu ab. Der Cache
überlebt einen verlorenen Push wie `updates` (`Cycle.Done`), sonst fragte jeder Lauf ohne Server neu ab.

## Stempel
`service -e` liest die Einschaltung aus `/etc/defaults/rc.conf`, `/etc/rc.conf`, `/etc/rc.conf.local`, den
`rc.conf.d`-Verzeichnissen und den Skripten in `/etc/rc.d` und `local_startup` (`/usr/local/etc/rc.d`). Der Stempel
ist mtime und Größe dieser Dateien und die mtime der Verzeichnisse samt Einträgen von `rc.conf.d`; ein `pkg install`
oder `sysrc` ändert so den Stempel und damit die Liste beim nächsten fälligen Lauf. Eine fehlende Datei zählt als
eigener Wert. Ein gescheitertes `service -e` oder ein Status-Aufruf ohne Antwort setzt keinen Cache: der nächste Lauf
fragt neu.

## Trade-offs
- Ganzen Block 15 min halten statt nur die Liste: Kevins Wahl; ein gestoppter Dienst erscheint in
  `enabled_inactive` bis zu 15 min später. Beobachtete Dienste (`watched`) melden einen Ausfall weiter im nächsten Lauf.
- Stempel aus mtime statt Inhalt-Hash: billig (stat statt lesen); eine Änderung mit gleicher mtime und Größe übersähe
  er, das ist bei rc.conf-Schreibern (sysrc, Editoren) nicht zu erwarten.

## Risiken & Rollback
Ein falscher Stempel hält eine veraltete Liste höchstens bis zu einer Dateiänderung; der Status selbst wird alle 15 min
neu gefragt. Rollback: Revert, der State-Eintrag wird von älteren Agenten ignoriert.

## Doku-Impact
`docs/developer/agent.html` DE+EN (FreeBSD-Spalte von `collectServiceHealth`); Changelog-Fragment.
