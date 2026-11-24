<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-pycommon-2 — Task-Ledger
Status: aktiv · Branch: feature/kern-pycommon-2 · Review: pro Task
Spec: docs/features/kern-pycommon-2.md (Roadmap R-1740)
Heavy: linux-full — Laufzeit-Imports von Server und Monitoring ändern sich (Images mit ah_common); kein PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Prüfung: `security` zusätzlich bei T2 (Risikopfade notifications, alerter) und wenn `review.sh risk` es verlangt.

## Tasks

### T1 — NUL-Middleware und query_params in ah_common (R-1740)  [x]
Komponente: server · Dateien: apps/pycommon/ah_common/middleware.py, apps/pycommon/ah_common/query_params.py, apps/server/app/core/middleware.py, apps/server/app/core/query_params.py, apps/monitoring/app/core/middleware.py, apps/monitoring/app/core/query_params.py, apps/server/app/main.py, apps/monitoring/app/main.py, apps/server/tests/test_no_python_copies.py
Evidenz: run.sh[quick] server monitoring: 5 passed, 0 failed, 13 skipped @abd230453 2026-11-24T20:24:06+01:00
Review: approve (.ah-out/review/kern-pycommon-2/T1.verdict.json)
Änderung: `NulByteMiddleware` mit `_nul_rejected` und das Modul `query_params` liegen einmal in `ah_common` (neue Dateien
mit SPDX); beide `main.py` importieren von dort, die Dienst-`query_params.py` entfallen, die Dienst-`middleware.py`
behalten nur ihre eigenen Klassen. Die Wächter-Ausnahmen für middleware und query_params fallen weg. Neun Dateien:
Wächter und beide Dienste sind nur zusammen grün.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T3

### T2 — Mail-Renderer in ah_common (R-1740)  [x]
Komponente: server · Dateien: apps/pycommon/ah_common/mail_template.py, apps/server/app/modules/notifications/mail_template.py, apps/monitoring/app/mail_template.py, apps/monitoring/app/notify_config.py, apps/monitoring/app/alerter.py, apps/monitoring/tests/test_notify_config.py, apps/monitoring/tests/test_mail_template_parity.py, apps/monitoring/tests/fixtures/mail_template_parity.json, apps/server/tests/test_no_python_copies.py, apps/monitoring/tests/test_alerter.py, apps/server/tests/test_notify_mail_template.py
Evidenz: run.sh[quick] server monitoring: 5 passed, 0 failed, 13 skipped @86cdee5bc 2026-11-24T22:21:01+01:00
Review: approve (.ah-out/review/kern-pycommon-2/T2.verdict.json)
Änderung: Der Renderer (`Template`, `Mail`, `DEFAULT`, `PLACEHOLDERS`, `LOGO_CID`, `format_time`, `unknown`, `compose`)
liegt einmal in `ah_common/mail_template.py` (SPDX); das Server-Modul behält `load`/`applied`/`using`/`current` und
re-exportiert den Renderer, das Monitoring importiert `ah_common.mail_template` direkt. `_KNOWN` im Wächter wird leer.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T3
Test-Löschung: apps/monitoring/tests/test_mail_template_parity.py::* — ersetzt durch die eine Implementierung in ah_common; Fixture-Fälle und format_time prüft apps/server/tests/test_notify_mail_template.py; apps/monitoring/tests/fixtures/mail_template_parity.json::* — Fixture des geloeschten Paritaetstests; dieselben Faelle liegen in apps/server/tests/fixtures/mail_template_parity.json

### T3 — Doku: gemeinsamer Code, Changelog (R-1740)  [ ]
Komponente: scripts · Dateien: docs/developer/index.html, docs/en/developer/index.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/server.html, docs/en/developer/server.html, changelog.d/kern-pycommon-2.md
Änderung: Die Liste des gemeinsamen Codes nennt NUL-Prüfung, Query-Prüfung und Mail-Renderer; `server.html` verliert
den Satz über zwei Renderer-Kopien (DE+EN). Changelog-Fragment.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
