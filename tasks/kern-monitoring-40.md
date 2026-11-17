# Monitoring: benannte SQL-Server-Instanzen — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-40 · Review: am Ende
Spec: docs/features/kern-monitoring-40.md (Roadmap R-1479)
Heavy: none — nur Erkennung und Katalog im Monitoring-Dienst; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1479: mssql findet benannte Instanzen (Schlüssel MSSQL-<name>)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/discovery.py, apps/monitoring/app/module_sync.py, apps/monitoring/app/catalog/modules/mssql.py, apps/monitoring/tests/test_catalog_windows_roles.py, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-40.md, tasks/kern-monitoring-40.md
Änderung: Suffixlose Dienste treffen auch ein Muster des Moduls (`MSSQL$*`); eine Unit-Instanz bekommt den Schlüssel
ohne `$` (`MSSQL$SHOP` → `MSSQL-SHOP`), ihr Dienstname bleibt in der Summary, und `probe_config` nimmt das Ziel aus
der Summary. mssql Version 2, Docstring und Modultabelle nachgezogen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_windows_roles.py tests/test_module_sync.py tests/test_discovery_match.py
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html (Zeile mssql) · changelog.d/kern-monitoring-40.md
Test-Löschung: apps/monitoring/tests/test_catalog_windows_roles.py::test_a_named_sql_server_instance_is_not_taken — gewollte Verhaltensänderung (Kevin 2026-11-17), ersetzt durch einen Test, der die benannte Instanz als MSSQL-SHOP mit Ziel MSSQL$SHOP findet

## Entscheidungen
