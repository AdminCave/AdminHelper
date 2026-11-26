# Zertifikat der 3CX-Weboberfläche — Task-Ledger
Status: geplant · Branch: feature/kern-monitoring-55 · Review: am Ende
Spec: docs/features/kern-monitoring-55.md (Roadmap R-1443)
Heavy: none — nur ein Katalog-Eintrag des Monitoring-Dienstes (kein Stack-, Gateway-, PKI- oder Install-Pfad, kein Agent-Code)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — 3CX: Check des Weboberflächen-Zertifikats an einer Instanz (R-1443)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/threecx.py, apps/monitoring/tests/test_catalog_threecx.py, changelog.d/kern-monitoring-55.md
Änderung: Check `web_certificate` (Sensor `tls`, `loopback` mit `alternatives` 443/5001, `instance` `3CXPhoneSystemMC01.service`, stündlich, `days_left` < 22 warning, < 9 critical), Kartenfeld, `version` 2, Docstring; Tests: nur die Konsolen-Instanz bekommt den Check, Port-Wahl 443/5001, ungebunden ohne beide, Regeln.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_threecx.py tests/test_catalog.py
Doku: changelog.d/kern-monitoring-55.md

## Entscheidungen
