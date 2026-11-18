# Zentrale Domain-Checks für vHost-Domains — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-43 · Review: pro Task
Spec: docs/features/kern-monitoring-43.md (Roadmap R-1501)
Heavy: none — nur der Monitoring-Dienst (Sensor tls, Katalog, Modul-Bindung); kein Stack-, Gateway-, PKI-, Agent- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Sensor tls: Parameter expiry (R-1501)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/check_configs.py, apps/monitoring/app/central/tls.py, apps/monitoring/tests/test_central_tls.py, apps/monitoring/tests/test_central_config.py, apps/monitoring/app/checkers/central.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @7255feca1 2026-11-18T09:27:50+01:00
Review: approve (.ah-out/review/kern-monitoring-43/T1.verdict.json)
Änderung: `TlsParams` bekommt `expiry: bool = True`. Mit `false` gibt der Sensor tls aus Restlaufzeit und Ablauf
keinen `warning`/`critical`; Name und Kette prüft er weiter (ein abgelaufenes Zertifikat zum letzten Zeitpunkt seiner
Gültigkeit), CAA/ARI unverändert, die Messwerte bleiben. Tests: knappe und abgelaufene Laufzeit mit `expiry: false`
ok, mit Default wie bisher; falscher Name bleibt critical; Schema lehnt Nicht-Bool ab.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_tls.py tests/test_central_config.py
Doku: → T4

### T2 — Katalog: zentrale Checks in Modulen binden (R-1501)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/model.py, apps/monitoring/app/module_sync.py, apps/monitoring/app/routers/checks.py, apps/monitoring/app/routers/findings.py, apps/monitoring/tests/test_catalog.py, apps/monitoring/tests/test_module_sync.py, apps/monitoring/tests/test_checks_crud.py
Änderung: Ein Katalog-`Check` mit `central: true` nennt einen Sensor aus `CENTRAL_SENSORS`, Ziel `vhost`, Params
nach dessen Schema, ein Intervall nicht unter dem Sensor-Minimum, keine Felder, Regeln, Zugangsdaten. `module_sync`
macht daraus eine Zeile `check_type="central"` mit `CentralConfig` (`host` = Instanzname, `port` = vHost-Port für
`tls`); Special-Use-Namen (Spec) werden mit `not a public name` übersprungen; `_update` behält das Intervall der
Zeile. `routers/checks.py`: eine zentrale Modul-Zeile behält Server, Sensor und Host. `GET /catalog` nennt
`central`. Tests: Adopt legt zentrale Zeilen an, Catalog-Sync stumm, Grabstein, gone schaltet ab, interner Name
übersprungen, Plan des Agents ohne zentrale Zeilen, Umbiegen per PUT abgelehnt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog.py tests/test_module_sync.py tests/test_checks_crud.py
Doku: → T4

### T3 — web_domain: dns und tls von außen je Domain (R-1501)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/web_domain.py, apps/monitoring/tests/test_catalog_web.py
Änderung: `web_domain` Version 2 mit zwei zentralen Checks: `dns` (Sensor dns, 15 min) und `outside` (Sensor tls,
`expiry: false`, stündlich, Port des vHosts); Docstring ohne „Domain-Checks von außen“ als Lücke. Tests: Katalog lädt,
Adopt einer vHost-Instanz ergibt vier Checks, zwei davon zentral mit der Domain als Host.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_web.py tests/test_catalog.py
Doku: → T4
Abhängt von: T1, T2

### T4 — Doku DE+EN und CHANGELOG (R-1501)  [ ]
Komponente: monitoring · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-43.md
Änderung: Abschnitt vHosts und Zeile `web_domain` (zentrale Checks dns und tls je Domain, ausgelassene interne
Namen, Ablauf nur vom Agent-Check), Parameter `expiry` beim zentralen Sensor tls, Entwickler-Doku zum zentralen
Katalog-Check; Changelog-Fragment ohne Umlaute.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_web.py
Doku: docs/admin/monitoring.html DE+EN · docs/developer/monitoring.html DE+EN · changelog.d/kern-monitoring-43.md
Task-Review: am Ende
Abhängt von: T3

## Entscheidungen
- 2026-11-18 Kevin: Ablauf meldet nur der Agent-Check `certificate`; der zentrale tls-Check des Moduls läuft mit `expiry: false`.
- 2026-11-18 Kevin: Namen mit Special-Use-Endung bekommen statisch keine zentralen Checks.
- 2026-11-18 Kevin: ohne RDAP; RDAP folgt mit R-1406 nach 0.47.0.
