# Monitoring: tag-gebundene Checks ohne Fund-Churn — Task-Ledger
Status: geplant · Branch: feature/kern-monitoring-21 · Review: am Ende
Spec: docs/features/kern-monitoring-21.md (Roadmap R-1446)
Heavy: none — nur Vergleich und Übernahme von Funden im Monitoring-Dienst, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1446: fehlendes `tag_checks` macht keinen Fund `changed`  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/discovery.py, apps/monitoring/tests/test_discovery_match.py, changelog.d/kern-monitoring-21.md, tasks/kern-monitoring-21.md
Änderung: `_seen_again` (`apps/monitoring/app/discovery.py:575`) lässt `tag_checks` aus dem Vergleich, wenn eine
der beiden Zusammenfassungen ihn nicht trägt; der Scan schreibt ihn nach. Tests: übernommener und verworfener Fund
mit alter Zusammenfassung bleiben, wie sie sind (erst rot); ein späterer Tag-Sprung macht den Fund weiter `changed`.
Beweis: kern-monitoring-29 Abschlussprüfung 2026-11-13 · apps/monitoring/app/discovery.py (_instances tag_checks)
Semantik: docs/admin/monitoring.html, Zeile `wikijs`: „Wechselt das Image auf 3, wird der Fund <code>changed</code>“
Dedup-Key: bug:monitoring:discovery:tag-checks-summary-churn
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_discovery_match.py tests/test_catalog_wikijs.py
Doku: changelog.d/kern-monitoring-21.md

### T2 — R-1446: ein per Tag abgeschalteter Check kommt zurück  [?] (Variante A: Check bei Tag-Wechsel löschen und bei Rückkehr neu anlegen, oder B: Spalte tag_off per Migration?)
Komponente: monitoring · Dateien: apps/monitoring/app/module_sync.py, apps/monitoring/tests/test_module_sync.py, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-21.md, tasks/kern-monitoring-21.md
Änderung: nach Kevins Antwort (Spec, Offene Fragen); Test: 2 → 3 → 2 übernommen, `healthz` danach an (erst rot).
Beweis: kern-monitoring-29 Abschlussprüfung 2026-11-13 · apps/monitoring/app/module_sync.py (_adopt)
Dedup-Key: bug:monitoring:discovery:tag-checks-summary-churn
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py
Doku: docs/admin/monitoring.html DE+EN (Zeile `wikijs`) · changelog.d/kern-monitoring-21.md
