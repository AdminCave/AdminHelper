# Monitoring-Katalog: Samba AD DC, ONLYOFFICE-Karte, Wiki.js 3, 3CX-Zertifikat, edulution — Task-Ledger
Status: bereit · Branch: feature/kern-monitoring-38 · Review: pro Task
Spec: docs/features/kern-monitoring-38.md (Roadmap R-1491, R-1487, R-1488, R-1500, R-1445, R-1443, R-1489)
Heavy: linux-full — neue App-Ansichten in apps/agent (Sammellauf)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1491, R-1487: Agent — DC ohne Partner, Units neben dem DC  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/app_samba.go, apps/agent/internal/probe/app_samba_test.go, apps/agent/internal/probe/sensor_app.go, docs/developer/agent.html, docs/en/developer/agent.html, tasks/kern-monitoring-38.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @5cc45df0b 2026-11-17T06:21:33+01:00
Review: approve (.ah-out/review/kern-monitoring-38/T1.verdict.json)
Änderung: `drsValues` meldet ohne eingehende Verbindung `last_success_age_s` = 0 (Kevin 2026-11-17). Neue Ansicht
`samba_dc_units`: Zahl der aktiven Units smbd, nmbd, winbind neben dem DC (`side_units_active`), nur der Zustand.
Tests: Einzel-DC (erst rot), je Unit aktiv/inaktiv.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: docs/developer/agent.html DE+EN

### T2 — R-1488: Agent — SRV-Einträge des DC  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/app_samba.go, apps/agent/internal/probe/app_samba_test.go, apps/agent/internal/probe/sensor_app.go, docs/developer/agent.html, docs/en/developer/agent.html, tasks/kern-monitoring-38.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @196955fa8 2026-11-17T06:31:01+01:00
Review: approve (.ah-out/review/kern-monitoring-38/T2.verdict.json)
Änderung: Neue Ansicht `samba_dns`: Realm auf dem Host lesen, die an der Samba-Doku belegten SRV-Einträge (dazu
`_msdcs`) über den Resolver des Systems fragen; Felder nur Zahlen (`srv_checked`, `srv_missing`). Realm und Namen
verlassen den Host nie. Tests mit einem Resolver-Stub.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: docs/developer/agent.html DE+EN
Abhängt von: T1

### T3 — R-1491, R-1487, R-1488: Katalog samba-ad-dc  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/samba_ad_dc.py, apps/monitoring/app/catalog/sensors.py, apps/monitoring/tests/test_catalog_directory.py, apps/monitoring/tests/test_catalog_sensors.py, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-38.md, tasks/kern-monitoring-38.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @8b6946d14 2026-11-17T06:33:41+01:00
Review: approve (.ah-out/review/kern-monitoring-38/T3.verdict.json)
Änderung: Checks `side_units` (warn bei > 0) und `dns` (warn bei `srv_missing` > 0), Karte mit `partners`,
Ansichten `samba_dc_units` und `samba_dns` samt Feldern in `sensors.py` zulassen; Docstring und Admin-Doku ohne die erledigten „Nicht abgedeckt“ und ohne „DC ohne Partner bleibt unknown“ (gilt nur für ältere Agenten), Version + 1.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_directory.py tests/test_catalog_sensors.py
Doku: docs/admin/monitoring.html DE+EN · changelog.d/kern-monitoring-38.md
Abhängt von: T2

### T4 — R-1500: ONLYOFFICE-Karte zeigt body_match  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/onlyoffice.py, apps/monitoring/tests/test_catalog_onlyoffice.py, changelog.d/kern-monitoring-38.md, tasks/kern-monitoring-38.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @53b9bab7b 2026-11-17T06:23:03+01:00
Review: approve (.ah-out/review/kern-monitoring-38/T4.verdict.json)
Änderung: beide Kartenfelder „Health check“ auf `body_match` (Kevin 2026-11-17).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_onlyoffice.py
Doku: changelog.d/kern-monitoring-38.md (die Admin-Doku nennt die Kartenfelder nicht)

### T5 — R-1445: Wiki.js 3 Bereitschafts-Check  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/wikijs.py, apps/monitoring/tests/test_module_sync.py, apps/monitoring/tests/test_catalog_wikijs.py, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-38.md, tasks/kern-monitoring-38.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @e268a16ee 2026-11-17T06:38:40+01:00
Review: approve (.ah-out/review/kern-monitoring-38/T5.verdict.json)
Änderung: Route und Tags von Wiki.js 3 an den Quellen belegen; dann ein Check mit `image_tags` 3, 3.*. Ohne
veröffentlichtes Image oder belegte Route: `[~]` mit Grund.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py tests/test_catalog_wikijs.py
Doku: docs/admin/monitoring.html DE+EN · changelog.d/kern-monitoring-38.md

### T6 — R-1443: 3CX-Zertifikat der Weboberfläche  [~] (braucht einen neuen Mechanismus (Check an genau einer Unit-Instanz, Port 443/5001/frei): R-1528, R-1443 zurueckgestellt)
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/threecx.py, apps/monitoring/tests/test_catalog_threecx.py, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-38.md, tasks/kern-monitoring-38.md
Änderung: Port und Dienst der Weboberfläche an der 3CX-Doku belegen; ein TLS-Check an genau einer Instanz (eigenes
Modul oder Ziel, nach dem Beleg). Braucht es einen neuen Katalog-Mechanismus: `[~]` und eigene Zeile.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_threecx.py
Doku: docs/admin/monitoring.html DE+EN · changelog.d/kern-monitoring-38.md

### T7 — R-1489: Modul edulution  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/edulution.py, apps/monitoring/tests/test_catalog_edulution.py, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-38.md, tasks/kern-monitoring-38.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @949411ef8 2026-11-17T06:42:31+01:00
Review: approve (.ah-out/review/kern-monitoring-38/T7.verdict.json)
Änderung: erst Images, Projektname und Health-Pfad an den Quellen belegen (Kevin 2026-11-16), dann das Modul und seine Testdatei (beide neu, SPDX-Header per `reuse annotate`).
Ohne Beleg: `[~]` mit Grund.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_edulution.py
Doku: docs/admin/monitoring.html DE+EN · changelog.d/kern-monitoring-38.md
