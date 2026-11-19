<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-46 — Katalog: Check an einer Instanz, Port-Alternativen am Host; einteilige vHost-Namen

Roadmap: R-1528, R-1548

## Problem / Motivation
- **R-1528:** Ein Modul mit Unit-Instanzen (3CX: 14 Units, `apps/monitoring/app/catalog/modules/threecx.py`) legt jeden
  Check an jeder Instanz an. Ein Check, der den Host einmal betrifft (das Zertifikat der 3CX-Weboberfläche am nginx des
  Systems, R-1443), hätte sonst 14 Kopien. Dazu wählt `Target.alternatives` (`apps/monitoring/app/catalog/model.py:121`)
  nur an Container-Zielen einen Port; die 3CX-Oberfläche lauscht je nach Setup auf 443 oder 5001.
- **R-1548:** `_public_name` (`apps/monitoring/app/module_sync.py:393`) hält einen einteiligen vHost-Namen (`intranet`)
  für öffentlich; die zentralen Checks für ihn melden nur `unknown`. Kevin 2026-11-18: als nicht öffentlich auslassen.

## Ziel & Nicht-Ziele
- R-1528: ein Katalog-Check mit `instance: "<key>"` wird nur an der Instanz mit diesem Schlüssel angelegt, an keiner
  anderen, auch nicht als „nicht gebunden“. `alternatives` gelten auch für `loopback`- und `unit`-Ziele: gewählt wird
  die erste Alternative, deren Port der letzte Scan am Host lauschen sah (Unit: Sockets dieser Unit; Loopback: Sockets
  außerhalb von Containern). Ohne bekannte Sockets die erste, keine gesehen: nicht gebunden mit Grund.
- R-1548: ein Name ohne Punkt ist nicht öffentlich (`not a public name`).
- Nicht: das 3CX-Zertifikat selbst (R-1443 bleibt zurückgestellt, baut auf diesem Mechanismus); kein Agent-Code.

## Betroffene Komponenten & Dateien
monitoring: `app/catalog/model.py` (`Check.instance`, `Target`-Prüfung), `app/module_sync.py` (`probe_config`,
die beiden Anlage-Schleifen, `_public_name`), Tests `tests/test_catalog.py` bzw. `tests/test_module_sync.py`.
Doku: `docs/developer/monitoring.html` DE+EN (Katalog-Felder), `changelog.d/kern-monitoring-46.md`.

## Datenmodell / API / Migrationen
Keine Migration. `Check.instance` fällt aus `model_dump`, wenn nicht gesetzt (wie `central`), damit
`definition_hash` aller bestehenden Checks gleich bleibt; `Target.alternatives` war schon im Dump.

## Trade-offs & Alternativen
- Instanz-Filter in den Anlage-Schleifen statt eines Bindungsgrunds in `probe_config`: ein Grund erschiene an den
  übrigen 13 Instanzen als „nicht gebunden“.
- Ein eigenes Modul mit einer Instanz für die Weboberfläche (km38-Spec): bräuchte eine eigene Erkennung für einen
  Dienst, den das Paket nur mittelbar (nginx) liefert; verworfen.

## Risiken & Rollback
Gering: neue optionale Felder, bestehende Hashes unverändert (Test). Rollback: Revert.

## Doku-Impact
`docs/developer/monitoring.html` DE+EN: Katalog-Felder `instance` und `alternatives`; Changelog-Fragment.

## Offene Fragen
Keine.
