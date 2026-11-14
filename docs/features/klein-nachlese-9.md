<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-9

## Problem / Motivation
Nachlese-Zeilen aus Reviews von `kern-monitoring-11`, `-14`, `-20`, `-30` und `-31`, nur Monitoring-Katalog und Doku:
- R-1471/R-1472: `UnixSocketParams.path` begrenzt auf 107 *Zeichen*, der Agent (`maxSocketPath`) auf 107 *Bytes*; ein
  Mehrbyte-Pfad geht am Server durch und scheitert beim Agent als `invalid`.
- R-1482: Docstring `windows_host.py` „no search of its own“ ist missverständlich (`wuaRead` sucht offline selbst).
- R-1486: Docstring `postfix.py` hat eine Zeile über 100 Zeichen; der smtp-Ausfall (Probe `status: error`) und das
  Loopback-Ziel sind nicht getestet.
- R-1498: Docstring `samba_member.py` nennt nicht, dass ein älteres Samba nur die drei `smbstatus`-Zahlen weglässt.
- R-1457: `dnsmasq --test` liest unter Debian `/etc/dnsmasq.d` nicht mit (Docstring und Doku unter „Nicht abgedeckt“);
  `docs/developer/agent.html` DE+EN zählt die Konfigurationstests der Dienst-Ansichten nicht auf.
- R-1459: Doku und Changelog-Fragment: ein älterer Agent lässt den OpenLDAP-Zertifikats-Check `unknown` (fehlendes
  `lifetime_pct`), nicht `invalid`.
- R-1496: Spec `kern-monitoring-11` auf die Entscheidungen nachziehen (`dovecot_status`, Watchdog-Adresse, Geräte-Import,
  `postfix_queue_age`, `samba_trust`).

## Ziel & Nicht-Ziele
Ziel: die Zeilen, mit Test, wo Verhalten wechselt (R-1471/R-1472, R-1486). Nicht-Ziele: Regeln, Schwellen, Agent-Code.

## Betroffene Komponenten & Dateien
`apps/monitoring/app/catalog/sensors.py`, die Modul-Docstrings (`postfix`, `samba_member`, `windows_host`, `dnsmasq`),
Tests `test_catalog_sensors.py`, `test_catalog_mail.py`; Doku `docs/{,en/}admin/monitoring.html`,
`docs/{,en/}developer/agent.html`, `docs/features/kern-monitoring-11.md`, `changelog.d/`.

## Datenmodell / API / Migrationen
Keine. Der Katalog lehnt einen Socket-Pfad über 107 Bytes mit „at most 107 bytes“ ab (vorher „characters“); ein Pfad
aus Mehrbyte-Zeichen, der in Zeichen passte und in Bytes nicht, wird nun am Server abgewiesen statt am Agent.

## Externe Integrationen
Keine neuen. Die Aussage zu `dnsmasq --test` (Debian bindet `/etc/dnsmasq.d` erst über den Dienst ein) stammt aus dem
Review von `kern-monitoring-31`; nicht auf einem Debian-Host geprüft.

## Trade-offs & Alternativen
Eigener `field_validator` statt `max_length` (zählt Zeichen); kein zweites Feld.

## Risiken & Rollback
Gering; ein Revert je Task.

## Doku-Impact
Admin-Handbuch und Agent-Entwicklerdoku DE+EN, Spec `kern-monitoring-11`, Changelog-Fragment.

## Offene Fragen
Keine. Aus dem Zug herausgenommen (eigene Züge): Agent-Go (`klein-nachlese-10`), Windows-Agent und Schwellen
(`klein-nachlese-11`); Harness-Zeilen R-1449, R-1451, R-1452, R-1454 stehen auf `blockiert`.
