<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Proxy-Client übersteht einen zweiten Lifespan — Task-Ledger
Status: erledigt · Branch: feature/monitoring-proxy-client · Review: am Ende
Spec: Roadmap R-0376
Heavy: none — Lifespan-Hygiene im Prozess: in Produktion läuft je uvicorn-Prozess genau ein Lifespan, der neue Zweig ist dort ein No-op; kein Stack-, Gateway-, PKI- oder Install-Pfad, die API ändert sich nicht
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Proxy-Client je Lifespan-Start erneuern  [x]
Komponente: server · Dateien: apps/server/app/modules/monitoring_proxy/router.py, apps/server/app/main.py, apps/server/tests/test_monitoring_proxy_lifespan.py, apps/server/tests/test_schemathesis.py, apps/server/tests/schemathesis_exclude.toml
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped @3bb70370 2026-10-15T15:09:41+02:00
Review: am Ende (Branch-Review)
Änderung: `router.py` bekommt `open_client()`, das einen geschlossenen Modul-Client (`router.py:42`) neu anlegt und einen offenen stehen lässt (sonst überschriebe der Start den Schemathesis-Stub); der Lifespan (`main.py:205`) ruft es nach `_run_startup_tasks()` (`main.py:210`), das Schließen beim Shutdown (`main.py:229-231`) bleibt. Neuer Test `tests/test_monitoring_proxy_lifespan.py` (SPDX-Kopf): zwei Lifespan-Zyklen, der Agent-Report im zweiten wird weitergereicht, Upstream per Transport-Stub ohne Netz. Die Kommentare, die den Stub mit dem geschlossenen Client begründen (`router.py:41`, `test_schemathesis.py:204`, `schemathesis_exclude.toml:49`, `:79`), werden nachgezogen; kein Verhalten der Fixture ändert sich.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_monitoring_proxy_lifespan.py
Doku: keine (intern; in Produktion keine Wirkung)
Beweis: main@63b55121 · Testentwurf als Kopie auf HEAD (`git archive`), `pytest -q -p no:randomly tests/test_monitoring_proxy_lifespan.py` → dreimal `1 failed`, `observed: RuntimeError: Cannot send a request, as the client has been closed.`
Orakel: crash — RuntimeError beim Proxy-Aufruf im zweiten Lifespan
Dedup-Key: ref:server:monitoring_proxy/router.py:module-client
HEAD: 63b55121
Semantik: keine Stelle in docs/ — gesucht: lifespan, monitoring_proxy, Monitoring-Proxy, /api/monitoring, AsyncClient, shutdown in docs/**/*.{md,html}; am nächsten `docs/developer/monitoring.html:54` — „`POST /api/monitoring/agent/{server_id}/report` – öffentlich (X-API-Key), reicht 1:1 an den Service“
