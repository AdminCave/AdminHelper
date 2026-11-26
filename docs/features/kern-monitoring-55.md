<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->
# kern-monitoring-55 — Zertifikat der 3CX-Weboberfläche

Roadmap: R-1443

## Problem / Motivation
Das Katalog-Modul `3cx` (`apps/monitoring/app/catalog/modules/threecx.py`) prüft nur die Units des Pakets `3cxpbx`.
Das Zertifikat der Weboberfläche, die 3CX über das nginx des Systems ausliefert (Port 443 bei einer Neuinstallation,
5001 nach einem Upgrade, sonst ein bei der Einrichtung gewählter Port; Quellen der Zeile R-1528), läuft unbemerkt ab.
Der Docstring nennt das als „Not covered“.

## Ziel & Nicht-Ziele
- Ein Check `web_certificate` (Sensor `tls`, Ziel `loopback` mit `alternatives` 443, dann 5001), gebunden nur an die
  Instanz `3CXPhoneSystemMC01.service` (Verwaltungskonsole; `Check.instance`, R-1528), damit er einmal je Host und
  nicht vierzehnmal entsteht. Regeln wie beim Panel-Zertifikat von CloudPanel: `days_left` < 22 warning, < 9
  critical; stündlich.
- Lauscht der Host auf keinem der beiden Ports, bleibt der Check ungebunden mit Grund (`_host_alternative`); ein frei
  gewählter Port ist nicht abgedeckt.
- Nicht: das Alter der Backups (eigenes Modul `3cx_backup`), kein Agent-Code, keine neue Katalog-Mechanik.

## Betroffene Komponenten & Dateien
monitoring: `app/catalog/modules/threecx.py` (Check, Karte, `version` 2, Docstring), `tests/test_catalog_threecx.py`.

## Datenmodell / API / Migrationen
Keine Migration, keine API-Änderung. Die Katalog-Version ändert sich mit dem Modul (gewollt).

## Externe Integrationen
3CX: Port der Weboberfläche laut den Quellen von R-1528 (3CX-Forum, Support-Aussagen); in der offiziellen Doku nicht
verifiziert. Der Sensor `tls` des Agents fragt ohne SNI, wenn kein `server_name` gesetzt ist; ob das nginx von 3CX
dann das Zertifikat der Weboberfläche liefert, ist nicht verifiziert (ein Server-Block auf dem Port ist die übliche
3CX-Konfiguration).

## Trade-offs & Alternativen
- Instanz `3CXPhoneSystemMC01.service` statt `3CXPhoneSystem01.service`: die Konsole ist der Dienst hinter der
  Weboberfläche; ist sie inaktiv, fehlt mit ihrer Instanz auch dieser Check, und der Unit-Check meldet den Ausfall
  ohnehin nicht (inaktiv macht keine Instanz). Empfehlung: Konsole.
- Ein eigenes Modul für die Weboberfläche wurde in kern-monitoring-46 verworfen.

## Risiken & Rollback
Gering: ein Katalog-Eintrag. Rollback: Revert des Commits.

## Doku-Impact
`changelog.d/kern-monitoring-55.md`; der Docstring des Moduls; die Zeile `3cx` der Modul-Tabelle in
`docs/admin/monitoring.html` DE+EN (Spalte Checks). Die Entwickler-Doku nennt den Fall schon (Abschnitt Katalog,
`instance` eines Checks).

## Offene Fragen
Keine aus Kevins Bereich.
