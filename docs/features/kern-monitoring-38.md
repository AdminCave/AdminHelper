# kern-monitoring-38 — Monitoring-Katalog: Samba AD DC, ONLYOFFICE-Karte, Wiki.js 3, 3CX-Zertifikat, edulution

Roadmap: R-1491, R-1487, R-1488, R-1500, R-1445, R-1443, R-1489

## Problem / Motivation
- **R-1491:** Der Check `replication` von `samba-ad-dc` steht auf einem DC ohne Partner (Regelfall linuxmuster)
  dauerhaft auf `unknown`: ohne eingehende Verbindung meldet `drsValues` (`apps/agent/internal/probe/app_samba.go`)
  kein `last_success_age_s`, und `_rate` (`apps/monitoring/app/checkers/probe.py`) wertet eine Regel ohne Wert als
  `unknown`.
- **R-1487:** smbd, nmbd oder winbind aktiv neben `samba-ad-dc` ist nach Konzept 6.3 selbst ein Befund; der
  Unit-Check bindet nur die Unit seiner Instanz.
- **R-1488:** Die SRV- und `_msdcs`-Einträge des DC prüft niemand; der Katalog kennt den Realm nicht.
- **R-1500:** Die ONLYOFFICE-Karte zeigt beim Gesundheitscheck `status_code`, kritisch wird er aber auch bei 200,
  wenn der Body nicht `true` ist (`body_match`).
- **R-1445:** Wiki.js 3 hat kein `/healthz`; ein Bereitschafts-Check für Tag 3 fehlt.
- **R-1443:** 3CX liefert die Weboberfläche über das nginx des Systems (443, 5001 oder ein eigener Port); ihr
  Zertifikat prüft kein Check, weil jeder Check des Moduls an einer Unit-Instanz hängt.
- **R-1489:** Ein Modul für edulution fehlt; Images, Projektname und Health-Pfad sind nicht belegt.

## Ziel & Nicht-Ziele
- R-1491 (Kevin 2026-11-17): ohne eingehende Verbindung meldet der Agent `last_success_age_s` = 0, der Check ist
  `ok`; die Karte bekommt `partners`. Bei einem DC mit Partnern ändert sich nichts.
- R-1487: eine neue App-Ansicht zählt aktive smbd/nmbd/winbind-Units neben dem DC; mehr als 0 warnt.
- R-1488: eine neue App-Ansicht liest den Realm auf dem Host und fragt die SRV-Einträge über den Resolver des
  Systems; zum Server gehen nur Zahlen (Realm und Namen verlassen den Host nie, Kevin 2026-11-15). Welche Einträge,
  belegt die Task an der Samba-Doku.
- R-1500 (Kevin 2026-11-17): beide Kartenfelder „Health check“ zeigen `body_match` statt `status_code`.
- R-1445, R-1443, R-1489: zuerst an der Quelle belegen (Route, Port, Images, Projektname, Health-Pfad); ohne Beleg
  bleibt die Zeile offen (`[~]` mit Grund, neue Zeile), statt geraten zu werden.
- Nicht: Zeitabweichung gegen Partner, Backups von 3CX, `dbcheck`.

## Betroffene Komponenten & Dateien
agent: `apps/agent/internal/probe/app_samba.go`, `app_samba_test.go`, `sensor_app.go`.
monitoring: `apps/monitoring/app/catalog/modules/{samba_ad_dc,onlyoffice,wikijs,threecx}.py`, ein neues Modul für
edulution, ihre Tests unter `apps/monitoring/tests/`. Doku: `docs/admin/monitoring.html` DE+EN,
`docs/developer/agent.html` DE+EN (neue Ansichten), `changelog.d/kern-monitoring-38.md`.

## Datenmodell / API / Migrationen
Keine Migration. Neue App-Ansichten des Agenten (Felder nur Zahlen); Katalog-Versionen der geänderten Module
steigen, übernommene Instanzen bekommen das Update über `updatable_checks`.

## Externe Integrationen
Samba (`samba-tool`, DNS-Einträge eines AD DC, Samba-Wiki), Wiki.js 3 (Quellen `requarks/wiki`), 3CX v20
(Admin-Doku), edulution (Quellen `edulution-io`). Jede Task belegt ihre Angaben per WebFetch an der offiziellen Quelle.

## Trade-offs & Alternativen
- R-1491: den Check nur bei Partnern anzulegen, bräuchte Partner schon im Scan (verworfen, Kevin 2026-11-17).
- R-1488: Resolver des Systems statt fest 127.0.0.1: prüft, was Clients des DC sehen, und braucht keine Annahme
  über die Listen-Adressen des Samba-DNS.
- R-1443: ein eigenes Modul mit einer einzigen Instanz für die Weboberfläche statt eines Checks an jeder der 14
  Units; die Form wählt die Task nach dem Beleg.

## Risiken & Rollback
Neue Agent-Ansichten laufen als root lokal; nur lesend (`samba-tool`, systemd-Zustand, DNS-Abfragen). Rollback: Revert
der Task-Commits.

## Doku-Impact
`docs/admin/monitoring.html` DE+EN (Zeilen `samba-ad-dc`, `onlyoffice`, `wikijs`, `3cx`, neue Zeilen),
`docs/developer/agent.html` DE+EN (App-Ansichten), CHANGELOG-Fragment.

## Offene Fragen
Keine. R-1491 und R-1500 hat Kevin am 2026-11-17 entschieden (siehe Ziel).
