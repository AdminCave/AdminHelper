<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-1 — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-1 · Review: pro Task
Spec: docs/features/kern-monitoring-1.md (Roadmap R-0921, R-0826, R-0828, R-0917)
Heavy: none — nur apps/monitoring (HTTP-Check, interne Alert-Route, Template-Abgleich), hermetische pytest-Tests; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Für alle Tasks: Zeilenangaben `origin/main@33295e76`, vor dem Schreiben neu greppen; Pfade ohne Präfix unter
`apps/monitoring/app/`. Neue Code-Strings englisch, CHANGELOG umlautfrei in `changelog.d/kern-monitoring-1.md`.
`security` zusätzlich bei T1 (und wo `review.sh risk` es verlangt). Einzelheiten der SEC-Zeile privat.

### T1 — HTTP-Check: höchstens fünf Content-Encoding-Schichten (R-0921)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/http.py, apps/monitoring/tests/test_http_checker.py, changelog.d/kern-monitoring-1.md, docs/developer/monitoring.html, docs/en/developer/monitoring.html
Änderung: `_decoded` (`checkers/http.py:167`) weist mehr als fünf `gzip`/`deflate`-Schichten mit `httpx.DecodingError` ab, bevor es eine Schicht anlegt (wie urllib3); der Check meldet `unknown`. Test zuerst rot: sechs Schichten → abgewiesen, fünf → dekodiert.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_http_checker.py
Doku: changelog.d/kern-monitoring-1.md, docs/developer/monitoring.html:180 + EN

### T2 — HTTP-Check: Redirect ohne Location bekommt eine eigene Meldung (R-0826)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/http.py, apps/monitoring/tests/test_http_checker.py, changelog.d/kern-monitoring-1.md
Änderung: Ein 3xx ohne `Location` (`checkers/http.py:93-94`) meldet `critical` „Redirect without Location header“ statt „Too many redirects (>5)“; `test_http_checker_ends_at_a_redirect_without_location` prüft die Meldung.
Beweis: Code-Lesung origin/feature/monitoring-io@13f340e4 apps/monitoring/app/checkers/http.py:89-90; Test: 302 ohne Location → Meldung ≠ "Too many redirects (>5)"
Dedup-Key: bug:monitoring:http.py:redirect-no-location-text
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_http_checker.py
Doku: changelog.d/kern-monitoring-1.md

### T3 — POST /alerts lehnt das maskierte Passwort ab (R-0828)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/alerts.py, apps/monitoring/tests/test_alert_secrets.py, changelog.d/kern-monitoring-1.md
Änderung: `create_alert_rule` (`routers/alerts.py:42`) antwortet auf `channel_config.smtp_password == "***"` mit 422, statt die Maske zu speichern. Test zuerst rot.
Beweis: Code-Lesung feature/smtp-hardening@0a5e5262 apps/monitoring/app/routers/alerts.py:42-55; Test: POST mit smtp_password "***" → 422, nichts gespeichert
Dedup-Key: bug:monitoring:alerts.py:create-mask-password
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alert_secrets.py
Doku: changelog.d/kern-monitoring-1.md

### T4 — Template-Variablen ohne Steuerzeichen (R-0917)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/template_sync.py, apps/monitoring/tests/test_template_sync.py, changelog.d/kern-monitoring-1.md
Änderung: `_build_variables` (`template_sync.py:80`) ersetzt C0-Steuerzeichen und DEL in `hostname` und `server_name` durch Leerzeichen (die Grenze von `_no_control_characters`, `schemas.py:24`). Test zuerst rot: Zuweisung mit Steuerzeichen im Hostnamen → Check-Name ohne Steuerzeichen.
Beweis: security-Review monitoring-hardening-2 T9 2026-10-28 · template_sync.py:73-83, schemas.py:190-193; Test: hostname "a\nb" → MonitorCheck.name ohne "\n"
Dedup-Key: bug:monitoring:template_sync:substitute_variables
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_template_sync.py
Doku: changelog.d/kern-monitoring-1.md

## Entscheidungen
