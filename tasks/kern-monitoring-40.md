# Monitoring: benannte SQL-Server-Instanzen — Task-Ledger
Status: erledigt · Branch: feature/kern-monitoring-40 · Review: am Ende
Spec: docs/features/kern-monitoring-40.md (Roadmap R-1479)
Heavy: none — nur Erkennung und Katalog im Monitoring-Dienst; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1479: mssql findet benannte Instanzen (Schlüssel MSSQL-<name>)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/discovery.py, apps/monitoring/app/module_sync.py, apps/monitoring/app/catalog/modules/mssql.py, apps/monitoring/tests/test_catalog_windows_roles.py, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-40.md, tasks/kern-monitoring-40.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @0af4ef34a 2026-11-17T09:11:39+01:00
Review: am Ende (Branch-Review)
Änderung: Suffixlose Dienste treffen auch ein Muster des Moduls (`MSSQL$*`); eine Unit-Instanz bekommt den Schlüssel
ohne `$` (`MSSQL$SHOP` → `MSSQL-SHOP`), ihr Dienstname bleibt in der Summary, und `probe_config` nimmt das Ziel aus
der Summary. mssql Version 2, Docstring und Modultabelle nachgezogen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_windows_roles.py tests/test_module_sync.py tests/test_discovery_match.py
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html (Zeile mssql) · changelog.d/kern-monitoring-40.md
Test-Löschung: apps/monitoring/tests/test_catalog_windows_roles.py::test_a_named_sql_server_instance_is_not_taken — gewollte Verhaltensänderung (Kevin 2026-11-17), ersetzt durch einen Test, der die benannte Instanz als MSSQL-SHOP mit Ziel MSSQL$SHOP findet

### T2 — Abschlussprüfung: Muster ohne Punkt nur mit `$`, Doku nachgezogen  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/discovery.py, apps/monitoring/tests/test_catalog_windows_roles.py, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/features/kern-monitoring-40.md, tasks/kern-monitoring-40.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @05e33f196 2026-11-17T09:30:36+01:00
Review: am Ende (Branch-Review)
Änderung: Ein Dienst ohne Punkt trifft nur Muster mit `$`; `postgresql-*`, `pm2-*`, `restic*`, `kopia*`, `borg*` nehmen
keinen Windows-Dienst und kein rc.d-Skript (wie auf main). Vier Doku-Stellen und der Risiko-Satz der Spec nennen das
neue Verhalten.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_windows_roles.py tests/test_module_sync.py tests/test_discovery_match.py
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html

## Entscheidungen
