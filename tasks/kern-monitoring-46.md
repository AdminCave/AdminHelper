<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-46 — Katalog: Check an einer Instanz, Port-Alternativen am Host; einteilige vHost-Namen — Task-Ledger
Status: bereit · Branch: feature/kern-monitoring-46 · Review: am Ende
Spec: docs/features/kern-monitoring-46.md (Roadmap R-1528, R-1548)
Heavy: none — nur Monitoring-Katalog und Abgleich, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Reihenfolge: nach dem Merge von `feature/kern-agent-9` (ändert `module_sync.py`).

## Tasks

### T1 — R-1528: Check an genau einer Instanz, Port-Alternativen an Loopback- und Unit-Zielen  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/model.py, apps/monitoring/app/module_sync.py, apps/monitoring/tests/test_catalog.py, apps/monitoring/tests/test_module_sync.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @4bc3811d1 2026-11-18T23:56:57+01:00
Review: am Ende (Branch-Review)
Änderung: `Check.instance` (optional, aus dem Dump, wenn nicht gesetzt); die Anlage-Schleifen in `module_sync`
überspringen einen Check mit fremder Instanz. `Target.alternatives` auch für `loopback` und `unit`; `probe_config`
wählt dort nach den Sockets des Inventars (Unit: ihre Sockets; Loopback: außerhalb von Containern). Tests: Hash eines
Checks ohne `instance` unverändert, Anlage nur an der Instanz, Wahl 443/5001 je gesehenem Socket, keiner gesehen,
keine Sockets bekannt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog.py tests/test_module_sync.py
Doku: → T3

### T2 — R-1548: einteilige vHost-Namen sind nicht öffentlich  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/module_sync.py, apps/monitoring/tests/test_module_sync.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @564242602 2026-11-18T23:57:58+01:00
Review: am Ende (Branch-Review)
Änderung: `_public_name` verlangt einen Punkt; Test: `intranet` bindet keinen zentralen Check (`not a public name`),
`intranet.example.org` weiter.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py
Doku: → T3

### T3 — Doku und CHANGELOG  [x]
Komponente: monitoring · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-46.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @15ecec468 2026-11-18T23:58:39+01:00
Review: am Ende (Branch-Review)
Änderung: Entwickler-Doku Katalog: `instance`, `alternatives` an Loopback/Unit, einteilige vHost-Namen; Fragment.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py
Doku: docs/developer/monitoring.html DE+EN · changelog.d/kern-monitoring-46.md
Task-Review: am Ende
Abhängt von: T1, T2

### T4 — Doku: Nits der Abschlussprüfung  [x]
Komponente: monitoring · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-46.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @c3aa26617 2026-11-19T00:04:37+01:00
Review: am Ende (Branch-Review)
Änderung: „nennt sie nicht“/„does not name them“ (zwei Felder); Changelog ohne 3CX-Beispiel (kein 3CX-Modul, R-1443).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py
Doku: docs/developer/monitoring.html DE+EN · changelog.d/kern-monitoring-46.md
Task-Review: am Ende

### T5 — Prototyp-Test ruft _update mit sockets  [x]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_rule_model_prototype.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @36109cba4 2026-11-19T00:54:31+01:00
Review: am Ende (Branch-Review)
Änderung: T2 gab `_update` den Parameter `sockets`; `test_today_a_catalog_update_overwrites_the_admins_rule_and_the_merge_keeps_it` rief es noch ohne ihn (TypeError, nur im ganzen Monitoring-Lauf sichtbar). Der Aufruf gibt `None` (keine vollständigen Sockets) mit.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_rule_model_prototype.py tests/test_module_sync.py
Doku: keine (nur Test)

## Entscheidungen
- Nit 1 der Abschlussprüfung (`_belongs` nur beim Anlegen) bleibt: noch kein Katalog-Check nutzt `instance`; Roadmap-Zeile.
