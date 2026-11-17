# Windows-Ansichten: leerer Bestand und Defender im Passivmodus — Task-Ledger
Status: geplant · Branch: feature/kern-monitoring-32 · Review: am Ende
Spec: docs/features/kern-monitoring-32.md (Roadmap R-1475, R-1480)
Heavy: none — nur apps/monitoring (Katalog und Bewertung), kein Stack-, Gateway-, PKI- oder Agent-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1475, R-1480: Regel-Optionen if_absent und unless  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/model.py, apps/monitoring/app/checkers/probe.py, apps/monitoring/tests/test_catalog.py, apps/monitoring/tests/test_probe_checker.py, tasks/kern-monitoring-32.md
Änderung: `Rule` (`model.py:135`) bekommt `if_absent: Literal["ok"] | None` und `unless: {field, value}`; beide fehlen
in der Serialisierung, solange sie nicht gesetzt sind (Hash der übrigen Module bleibt). `unless.field` muss unter den
Feldern des Checks stehen (Prüfung :278). `_rate` (`probe.py:168`) überspringt eine Regel ohne Wert mit `if_absent`
und eine Regel, deren `unless`-Feld den Wert hat. Tests: Serialisierung ohne Optionen unverändert, Validierung,
Bewertung mit und ohne Wert, `unless` gesetzt/nicht gesetzt/fehlend.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog.py tests/test_probe_checker.py
Doku: → T2

### T2 — R-1475, R-1480: Windows-Module nutzen die Optionen  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/windows_ad.py, apps/monitoring/app/catalog/modules/windows_host.py, apps/monitoring/app/catalog/modules/windows_rds.py, apps/monitoring/app/catalog/modules/defender.py, apps/monitoring/tests/test_catalog_windows_server.py, apps/monitoring/tests/test_catalog_windows_roles.py, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-32.md, tasks/kern-monitoring-32.md
Änderung: `if_absent: "ok"` an `oldest_success_age_s` (windows-ad), `min_days_left` (windows-host certs) sowie
`used_pct` und `min_days_left` (windows-rds); `unless: {passive: true}` an der Regel `realtime_on` (defender);
Version je Modul +1, Docstrings mit Quelle (Microsoft Learn, Kompatibilitätsseite). Tests über `ProbeChecker` je Fall
(leerer Bestand ok, Wert weiter bewertet; passiv und Echtzeit aus ok, aktiv und aus kritisch).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_windows_server.py tests/test_catalog_windows_roles.py tests/test_catalog.py
Doku: docs/admin/monitoring.html DE+EN · changelog.d/kern-monitoring-32.md
Abhängt von: T1

## Entscheidungen
