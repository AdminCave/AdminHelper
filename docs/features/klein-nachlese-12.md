<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-12 — Spec

## Problem
Nits aus der Nachlese von kern-monitoring-28 und kern-monitoring-35:
- **R-1505, R-1510:** `cachedVhosts` (`apps/agent/internal/probe/web_vhost_cert.go`) merkt 60 s lang auch einen Fehler, der
  nur aus dem `ctx` des ersten Aufrufers stammt (Zeitlimit, Abbruch); Wartende am Mutex ignorieren ihren eigenen `ctx`.
- **R-1507:** `execx.RunCapped` beendet bei Frist oder Ausgabegrenze nur den Kindprozess (`runuser`); das darunter
  laufende `php` bleibt als Waise.
- **R-1509:** `uniqueVhosts` (`web_vhosts.go`) bevorzugt den TLS-Block; die App hängt je Block am ersten Namen, bei
  abweichender Namensreihenfolge landet sie auf einem Alias. Ein Test fehlt.
- **R-1514:** `errWPDBServer` (`app_wordpress_cron.go`) erreicht keinen Aufrufer (der Treiber macht `ErrInvalidConn`
  daraus, `wpDBError` meldet „connection fails“); der Docstring von `_before_app_checks`
  (`apps/monitoring/tests/test_module_sync.py`) stimmt für wordpress v3 nicht mehr.
- **R-1511:** Doku nennt `127.0.0.1`/Loopback als Ziel eines vHost-Checks; `resolve` nimmt die Adresse, auf der der
  Webserver am Port lauscht.
- **R-1512:** `web_domain` fährt Zertifikats- und Reload-Check je als eigenen Lauf der View `web_vhost_cert`: zwei
  Handshakes je Domain und Stunde; die Spec von kern-monitoring-28 versprach einen.
- **R-1506** fällt weg: `servedVhost` gleicht Name und Port in `sensor_http.go`/`sensor_tls.go` bereits ab (Test in
  `sensor_net_test.go`); die Zeile ist `abgelehnt`.

## Ziel / Nicht-Ziele
Je Zeile das beschriebene Verhalten beheben bzw. die Doku berichtigen. R-1512: **Doku anpassen**, nicht die Checks
zusammenlegen (das änderte Katalog-Version und bestehende Instanzen). Keine neuen Funktionen.

## Betroffene Dateien
`apps/agent/internal/probe/{web_vhost_cert,web_vhosts,app_wordpress_cron}.go` samt Tests, `apps/agent/internal/execx/`,
`apps/monitoring/tests/test_module_sync.py`, `docs/{developer,admin}/…` DE+EN, `docs/features/kern-monitoring-28.md`.

## Datenmodell / API / Migrationen
Keine.

## Doku-Impact
`docs/developer/agent.html`, `docs/developer/monitoring.html`, `docs/admin/monitoring.html` je DE+EN
(Zieladresse des vHost-Checks, zwei Handshakes); `docs/features/kern-monitoring-28.md` (Last). Die Agent-Tasks sind intern.

## Risiken & Rollback
`execx` ist Plattform-Code (Prozessgruppe nur Unix; Windows-Build mit Build-Tags prüfen, `GOOS=windows go vet`).
Rollback je Task-Commit.

## Offene Fragen
Keine.
