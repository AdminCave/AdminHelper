# Zertifikat der 3CX-Weboberfläche — Task-Ledger
Status: erledigt · Branch: feature/kern-monitoring-55 · Review: am Ende
Spec: docs/features/kern-monitoring-55.md (Roadmap R-1443)
Heavy: none — nur ein Katalog-Eintrag des Monitoring-Dienstes (kein Stack-, Gateway-, PKI- oder Install-Pfad, kein Agent-Code)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — 3CX: Check des Weboberflächen-Zertifikats an einer Instanz (R-1443)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/threecx.py, apps/monitoring/tests/test_catalog_threecx.py, changelog.d/kern-monitoring-55.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @ebe327409 2026-11-26T20:02:19+01:00
Review: am Ende (Branch-Review)
Änderung: Check `web_certificate` (Sensor `tls`, `loopback` mit `alternatives` 443/5001, `instance` `3CXPhoneSystemMC01.service`, stündlich, `days_left` < 22 warning, < 9 critical), Kartenfeld, `version` 2, Docstring; Tests: nur die Konsolen-Instanz bekommt den Check, Port-Wahl 443/5001, ungebunden ohne beide, Regeln.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_threecx.py tests/test_catalog.py
Doku: changelog.d/kern-monitoring-55.md

### T2 — Admin-Doku: Modul-Tabelle nennt den Zertifikats-Check von 3CX (R-1443)  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/features/kern-monitoring-55.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @2ef1dc0de 2026-11-26T20:10:56+01:00
Review: am Ende (Branch-Review)
Änderung: Zeile `3cx` der Modul-Tabelle (Spalte Checks, DE+EN) um den Check `web_certificate` ergänzen; Doku-Impact der Spec berichtigen (Fund der Abschlussprüfung).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/monitoring.html DE+EN
Task-Review: am Ende

## Entscheidungen
