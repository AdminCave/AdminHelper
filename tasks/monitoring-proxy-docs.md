<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Entwickler-Doku zum Monitoring-Proxy folgt der Allowlist — Task-Ledger
Status: bereit · Branch: feature/monitoring-proxy-docs · Review: am Ende
Spec: Roadmap R-0382
Heavy: none — Doku und ein statischer Test; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Doku-Präfixe und Modulpfad richtig, Abgleich als Test  [x]
Komponente: server · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/server.html, docs/en/developer/server.html, apps/server/tests/test_monitoring_proxy_allowlist.py, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @3fa1ea93 2026-10-15T16:28:17+02:00
Review: am Ende (Branch-Review)
Änderung: `monitoring.html:56` (DE+EN) nennt die Präfixe aus `_ALLOWED_PATH_PREFIXES` (`apps/server/app/modules/monitoring_proxy/router.py:45-52`: `checks`, `alerts`, `status`, `templates`, `maintenance`, `agent`) statt `log` und `metrics`; `server.html:67` (DE+EN) nennt `modules/monitoring_proxy/router.py`. `test_monitoring_proxy_allowlist.py` bekommt einen Abgleich: die in beiden `monitoring.html` genannten Präfixe sind genau `_ALLOWED_PATH_PREFIXES` (die Datei pinnt schon Allowlist gegen Routen, ihr Docstring nennt dieselbe `log`/`metrics`-Drift). Der neue Abgleich ist vor der Doku-Korrektur rot; das zeigt der builder.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_monitoring_proxy_allowlist.py
Doku: docs/developer/monitoring.html + docs/en/developer/monitoring.html, docs/developer/server.html + docs/en/developer/server.html
Beweis: main@c18098a4 · `grep -n "log</code>, <code>metrics" docs/developer/monitoring.html docs/en/developer/monitoring.html` → je ein Treffer in Zeile 56; `grep -n "modules/monitoring_proxy.py" docs/developer/server.html docs/en/developer/server.html` → je ein Treffer in Zeile 67; Soll: `router.py:45-52`
Orakel: contract — Abgleich Doku ↔ `_ALLOWED_PATH_PREFIXES`
Dedup-Key: bug:docs:monitoring.html:proxy-prefixes
HEAD: c18098a4
Semantik: docs/ ist hier selbst der Fehler; das Soll steht im Code (`router.py:44` „Allowed path prefixes for the monitoring proxy (SSRF protection)“) und in `.claude/rules/docs.md` — „Falsche Doku ist ein Bug“
