<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-10

## Problem / Motivation
Nachlese-Zeilen aus Reviews von `ci-11`, `kern-monitoring-11`, `-14`, `-30` und `kern-desktop-e2e-1`:
- R-1453: `cicd.html` (DE+EN) nennt in der Zeile des FRP-Pin-Checks weder `scripts/tests/freebsd_box.sh` noch den
  FreeBSD-SHA-256, und die Job-Aufzählung führt `pkg-repo` nicht; Spec `ci-11` Ziel 5 spricht vom SHA-256 des DER,
  die Doku nennt den SHA-256 der Datei `adminhelper-pkg.pub`; Ziel 4 und das Ledger beschreiben den Ablauf von
  `build-pkg.sh` im Release verschieden.
- R-1458: aus `kern-monitoring-30` fünf eindeutige Nits: `fetchExpecting` liest den Body auch ohne `body_match`; die feste
  200-ms-Frist in `sensor_net_test.go` trägt keinen Kommentar (`testing.md`); zwei Docstrings über 100 Zeichen und
  ungleich umbrochene Docstrings in `mattermost.py` und `onlyoffice.py`. Zwei Punkte sind Verhalten und gehen als
  neue Zeilen an Kevin (unten).
- R-1473: Kommentarzeile in `sensor_host.go` mit 122 Zeichen.
- R-1485: `dovecotErrors` überspringt eine Zeile von `doveadm log errors`, die sie nicht kennt, still.
- R-1490: `linuxmuster.py` nennt `SSLDIR` „not verified“. Belegt gegen `linuxmuster-common` `lib/environment.py`
  (`SYSDIR = '/etc/linuxmuster'`, `SSLDIR = SYSDIR + '/ssl'`, Zeile 14 und 24) und `linuxmuster-base7`
  `functions/certs.py:252` (`SSLDIR + '/' + item + '.cert.pem'`, Item `server`).
- R-1492: `findingItem` im Live-E2E wählt den Eintrag per Index und fragt danach `$$` ab; zwischen beiden Aufrufen kann
  sich die Liste ändern.
- R-1495: `lmn_linbo`: ein Image, das zwischen `ReadDir` und `Lstat` verschwindet, bricht den ganzen Lauf ab.
- R-1497: der Test „smbstatus fehlt“ prüft nur `err != nil`, nicht, dass es `ErrUnsupported` (unknown) ist.

## Ziel & Nicht-Ziele
Ziel: die acht Zeilen. Nicht-Ziele: `timeout_s <= 2` mit `auto` an einem stillen Klartext-Server (`sensor_http.go`,
R-1458) und ein Kartenfeld `body_match` für OnlyOffice: beides ändert sichtbares Verhalten und geht als neue
Roadmap-Zeile `neu` an Kevin.

## Betroffene Komponenten & Dateien
Agent: `apps/agent/internal/probe/sensor_host.go`, `sensor_http.go`, `sensor_net_test.go`, `app_samba_test.go`,
`app_mail.go`, `app_mail_test.go`, `app_lmn.go`, `app_lmn_test.go`. Monitoring: `app/catalog/modules/linuxmuster.py`,
`mattermost.py`, `onlyoffice.py`, `tests/test_catalog_onlyoffice.py`, `tests/test_catalog_openldap.py`. Desktop-E2E:
`apps/desktop/e2e/test/specs/monitoring-server-page.live.js`. Doku: `docs/developer/cicd.html` (DE+EN),
`docs/features/ci-11.md`, `tasks/ci-11.md`; `changelog.d/klein-nachlese-10.md`.

## Datenmodell / API / Migrationen
Keine. Sichtbar ändert sich nur der Agent: eine unbekannte Zeile von `doveadm log errors` macht `dovecot_status` zum
Fehler (Check wird `unknown`/Fehler des Laufs statt still zu zählen), ein verschwundenes Image bricht `lmn_linbo` nicht
mehr ab.

## Trade-offs & Alternativen
- R-1485: unbekanntes Zeilenformat ist ein Fehler (der Lauf meldet es), nicht eine Zählung als Warnung: die Zählung
  wäre eine Annahme über ein Format, das `doveadm` ändern kann. Leere Zeilen und die Meldung „no errors“ bleiben
  erlaubt, soweit der Code sie schon kennt.
- R-1495: ein Image, das bei `Lstat` fehlt, zählt weder als Image noch als veraltet; jeder andere Lesefehler bleibt
  ein Fehler des Laufs.
- R-1492: das Element kommt aus `browser.execute` selbst (Element-Referenz) statt aus Index und zweiter Abfrage.
  Lokal nur per ESLint belegt: das Live-Spec fährt die Desktop-Box (R-1135 wartet auf Kevins Ja).

## Risiken & Rollback
Gering; jede Task ist ein eigener Commit. Das Live-Spec (R-1492) läuft erst auf der Desktop-Box.

## Doku-Impact
`cicd.html` DE+EN (FRP-Pin-Check, Job `pkg-repo`); Spec und Ledger von `ci-11` in einzelnen Sätzen. Der Agent-Fix
steht im Changelog-Fragment.

## Offene Fragen
Keine für diese Tasks. Neue Zeilen für Kevin: `timeout_s <= 2` mit `auto` (R-1458), Kartenfeld `body_match` für
OnlyOffice (R-1458).
