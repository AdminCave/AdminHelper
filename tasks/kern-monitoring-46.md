<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-46 — Katalog: Check an einer Instanz, Port-Alternativen am Host; einteilige vHost-Namen — Task-Ledger
Status: geplant · Branch: feature/kern-monitoring-46 · Review: am Ende
Spec: docs/features/kern-monitoring-46.md (Roadmap R-1528, R-1548)
Heavy: none — nur Monitoring-Katalog und Abgleich, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Reihenfolge: nach dem Merge von `feature/kern-agent-9` (ändert `module_sync.py`).

## Tasks

### T1 — R-1528: Check an genau einer Instanz, Port-Alternativen an Loopback- und Unit-Zielen  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/model.py, apps/monitoring/app/module_sync.py, apps/monitoring/tests/test_catalog.py, apps/monitoring/tests/test_module_sync.py
Änderung: `Check.instance` (optional, aus dem Dump, wenn nicht gesetzt); die Anlage-Schleifen in `module_sync`
überspringen einen Check mit fremder Instanz. `Target.alternatives` auch für `loopback` und `unit`; `probe_config`
wählt dort nach den Sockets des Inventars (Unit: ihre Sockets; Loopback: außerhalb von Containern). Tests: Hash eines
Checks ohne `instance` unverändert, Anlage nur an der Instanz, Wahl 443/5001 je gesehenem Socket, keiner gesehen,
keine Sockets bekannt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog.py tests/test_module_sync.py
Doku: → T3

### T2 — R-1548: einteilige vHost-Namen sind nicht öffentlich  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/module_sync.py, apps/monitoring/tests/test_module_sync.py
Änderung: `_public_name` verlangt einen Punkt; Test: `intranet` bindet keinen zentralen Check (`not a public name`),
`intranet.example.org` weiter.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py
Doku: → T3

### T3 — Doku und CHANGELOG  [ ]
Komponente: monitoring · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-46.md
Änderung: Entwickler-Doku Katalog: `instance`, `alternatives` an Loopback/Unit, einteilige vHost-Namen; Fragment.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py
Doku: docs/developer/monitoring.html DE+EN · changelog.d/kern-monitoring-46.md
Task-Review: am Ende
Abhängt von: T1, T2

## Entscheidungen
