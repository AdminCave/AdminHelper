# klein-nachlese-24 — Nachlese aus drei Pruefungen

Roadmap R-1777, R-1778, R-1838 (alle REF, Dauerauftrag). R-1791 faehrt nicht mit: `feature/arch-monitoring-neu-p1c`
aendert dieselben Dateien, die Zeile wartet in `klein-nachlese-25`.

## Problem
- R-1777 (Agent, FreeBSD-Platten): `disks_test.go` laesst einen Fehlschlag bis zum 30-s-Timeout haengen statt sofort
  rot zu werden; `boundedStats` fragt einen doppelten Mountpfad nur einmal, die Warnung in `disks_freebsd.go` zaehlt
  aber `len(bounded)-len(answered)` und meldet "network mount(s)" auch fuer lokale und doppelte Eintraege. Die
  Klammer in `docs/developer/agent.html` Zeile 224 hat `klein-doku-11` schon richtiggestellt; die Task prueft das und
  laesst die Doku sonst unberuehrt. `tasks/kern-agent-24.md:20` (Cross-Build von Hand) ist abgeschlossene Historie und
  bleibt.
- R-1778 (Server, Hooks): Der Kommentar an `_failure_notice_locks` nennt event-getriebene Hooks "web worker", aber
  `server.startup`-Hooks laufen im Scheduler-Prozess (`scheduler_main.py`); gleiches in
  `docs/features/kern-server-15.md`. Der Glockentext `(details in the server log)` (kein Test haelt ihn bisher) stimmt fuer Schedule- und
  `server.startup`-Hooks nicht: sie loggen im Scheduler-Dienst.
- R-1838 (Doku): `docs/admin/monitoring.html` und EN sagen, der Status-Check von `nextcloud-aio` brauche Port 8000 im
  Scan. `_lacks_port` bindet ihn aber auch, wenn der Scan am Container gar keine TCP-Ports sah.

## Ziel & Nicht-Ziele
Die Fundstellen stimmen mit dem Code ueberein; je Fund hoechstens eine kleine Aenderung. Nicht-Ziel: Umbau des
Hook-Loggings oder der Platten-Abfrage.

## Betroffene Komponenten & Dateien
`apps/agent/internal/monitor/{disks_test,disks_bounded,disks_freebsd}.go`,
`apps/server/app/modules/hooks/script_runner.py` (+ Test), `docs/features/kern-server-15.md`,
`docs/admin/monitoring.html`, `docs/en/admin/monitoring.html`, `changelog.d/klein-nachlese-24.md`.

## Datenmodell / API / Migrationen
Keine. Der Glockentext ist ein Anzeigetext, keine API-Form.

## Trade-offs
Glockentext: neutral "details in the log" statt Dienstname, damit er fuer beide Dienste stimmt (Empfehlung);
Alternative waere der Dienstname je Hook-Art, mehr Code fuer ein Nit.

## Risiken & Rollback
Gering; je Task ein Commit, einzeln zurueckzunehmen.

## Doku-Impact
`monitoring.html` DE + EN (R-1838), `kern-server-15.md` (Kommentar-Satz); Changelog-Fragment.

## Offene Fragen
Keine.
