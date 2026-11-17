# Monitoring: tag-gebundene Checks ohne Fund-Churn — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-21 · Review: am Ende
Spec: docs/features/kern-monitoring-21.md (Roadmap R-1446)
Heavy: none — nur Vergleich und Übernahme von Funden im Monitoring-Dienst, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1446: fehlendes `tag_checks` macht keinen Fund `changed`  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/discovery.py, apps/monitoring/tests/test_module_sync.py, changelog.d/kern-monitoring-21.md, tasks/kern-monitoring-21.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @dc36e05e2 2026-11-16T22:52:39+01:00
Review: am Ende (Branch-Review)
Änderung: `_seen_again` (`apps/monitoring/app/discovery.py:575`) lässt `tag_checks` aus dem Vergleich, wenn eine
der beiden Zusammenfassungen ihn nicht trägt; der Scan schreibt ihn nach. Tests: übernommener und verworfener Fund
mit alter Zusammenfassung bleiben, wie sie sind (erst rot); ein späterer Tag-Sprung macht den Fund weiter `changed`.
Beweis: kern-monitoring-29 Abschlussprüfung 2026-11-13 · apps/monitoring/app/discovery.py (_instances tag_checks)
Semantik: docs/admin/monitoring.html, Zeile `wikijs`: „Wechselt das Image auf 3, wird der Fund <code>changed</code>“
Dedup-Key: bug:monitoring:discovery:tag-checks-summary-churn
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py tests/test_discovery_match.py tests/test_catalog_wikijs.py
Doku: changelog.d/kern-monitoring-21.md

### T2 — R-1446: ein per Tag entfernter Check kommt zurück  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/module_sync.py, apps/monitoring/tests/test_module_sync.py, docs/features/kern-monitoring-21.md, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-21.md, tasks/kern-monitoring-21.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @7b4f5e21f 2026-11-17T04:24:48+01:00
Review: am Ende (Branch-Review)
Änderung: Variante A (Kevin 2026-11-17): `_adopt` löscht einen nicht mehr passenden tag-gebundenen Check (ohne
Grabstein) statt ihn abzuschalten; bei der Rückkehr legt das Übernehmen ihn neu an. Test: 2 → 3 → 2 übernommen,
`healthz` danach an (erst rot).
Beweis: kern-monitoring-29 Abschlussprüfung 2026-11-13 · apps/monitoring/app/module_sync.py (_adopt)
Dedup-Key: bug:monitoring:discovery:tag-checks-summary-churn
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py
Doku: docs/admin/monitoring.html DE+EN (Zeile `wikijs`) · changelog.d/kern-monitoring-21.md

### T3 — Entwickler-Doku zu T1 und T2  [ ]
Komponente: scripts · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html, tasks/kern-monitoring-21.md
Änderung: Fund der Abschlussprüfung (reviewer branch 2026-11-17 @84f1f88b8): `_adopt` löscht statt abzuschalten, `_same`
vergleicht `tag_checks` nur, wenn beide Zusammenfassungen es tragen; DE+EN.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/monitoring.html DE+EN
Task-Review: am Ende

## Entscheidungen
- T2: Variante A (Kevin 2026-11-17, Frage der Spec). Die Id des entfernten Checks steht weiter in `disabledChecks` der Übernahme-Antwort (Vertrag unverändert: er läuft nicht mehr), der Grund in `skippedChecks`, weil das Übernehmen den Schlüssel neu anzulegen versucht. Von Hand abgeschaltete Altzeilen gibt es nicht: R-1397 ist in keinem Release.
