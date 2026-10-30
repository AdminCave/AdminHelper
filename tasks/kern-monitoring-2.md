<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-2 — Task-Ledger
Status: erledigt · Branch: feature/kern-monitoring-2 · Review: am Ende
Spec: docs/features/kern-monitoring-2.md (Roadmap R-0968)
Heavy: none — nur ein Monitoring-Router und sein Test, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben `origin/main@0c474527`, vor dem Schreiben neu greppen. CHANGELOG umlautfrei in
`changelog.d/kern-monitoring-2.md`.

### T1 — POST /templates lehnt die Maske als SMTP-Passwort mit 422 ab (R-0968)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/templates.py, apps/monitoring/tests/test_alert_secrets.py, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-2.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @65100ae6 2026-10-30T17:45:41+01:00
Review: am Ende (Branch-Review)
Beweis: review kern-monitoring-1 T3 2026-10-29 · feature/kern-monitoring-1@e1f8fe13 apps/monitoring/app/routers/templates.py:188 · Dedup-Key: bug:monitoring:templates.py:create-mask-password
Semantik: docs/admin/monitoring.html:340 „beim Anlegen einer Regel lehnt sie <code>***</code> als Passwort mit 422 ab“ (Templates nicht genannt; die Zeile R-0968 stellt sie gleich)
Änderung: `create_template` (`templates.py:209-215`) antwortet bei `smtp_password == "***"` in einer Alert-Definition mit 422 und dem Text von `POST /alerts` (`alerts.py:60`), bevor etwas angelegt wird. Test zuerst rot: `test_template_post_does_not_store_the_mask_as_password` teilt sich in `""` (201, kein Passwort) und `"***"` (422, kein Template in der DB).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alert_secrets.py
Doku: docs/admin/monitoring.html + docs/en/admin/monitoring.html (Satz zur Maske beim Anlegen), changelog.d/kern-monitoring-2.md

## Entscheidungen
