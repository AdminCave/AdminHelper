<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-config-1 — Task-Ledger
Status: aktiv · Branch: feature/kern-config-1 · Review: pro Task
Spec: docs/features/kern-config-1.md (Roadmap R-0699)
Heavy: linux-full — `docker-compose.yml`, Server-API (`/api/docs`), `apps/ca-issuer`; kein Install- oder PKI-Datenpfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — ah_common.env und fail-fast im Server  [x]
Komponente: server · Dateien: apps/pycommon/ah_common/env.py (neu, SPDX), apps/pycommon/ah_common/logging_config.py, apps/server/app/core/config.py, apps/server/tests/test_config_env.py (neu, SPDX), apps/server/tests/test_web_idle_timeout.py, apps/server/tests/test_web_session_max.py, apps/server/tests/test_logging_config.py, apps/monitoring/tests/test_logging_config.py, apps/server/tests/test_env_parity.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @09669d33c 2026-11-24T11:36:57+01:00
Review: approve (.ah-out/review/kern-config-1/T1.verdict.json)
Änderung: R-0699. Neu in `ah_common/env.py`: `env_int(name, default, *, minimum=None)` und `ConfigError(ValueError)`. Die Meldung nennt Variable, Wert und Erwartung. Alle Zahlen-Variablen in `apps/server/app/core/config.py` laufen darüber (`SMTP_PORT` bis `NOTIFICATION_RETENTION_DAYS`). `WEB_IDLE_TIMEOUT_MINUTES`, `WEB_SESSION_MAX_HOURS` und ein unbekanntes `LOG_LEVEL` (`ah_common.logging_config`) brechen ab statt zurückzufallen. Die Fallback-Tests werden zu Abbruch-Tests, auch der des Monitorings, weil `logging_config` geteilt ist; T3 fährt ihn.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_config_env.py tests/test_web_idle_timeout.py tests/test_web_session_max.py tests/test_logging_config.py tests/test_env_parity.py tests/test_no_python_copies.py
Doku: → T5

### T2 — Server: Doku hinter SERVER_ENABLE_DOCS, ERROR bei leerem MONITOR_API_KEY  [x]
Komponente: server · Dateien: apps/server/app/main.py, apps/server/tests/test_server_docs.py (neu, SPDX), apps/server/tests/test_hooks.py, scripts/tests/sse_push_e2e.sh, docker-compose.yml, .env.example
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @2eb19d1df 2026-11-24T11:42:19+01:00
Review: approve (.ah-out/review/kern-config-1/T2.verdict.json)
Änderung: R-0699. `docs_url` und `openapi_url` nur mit `SERVER_ENABLE_DOCS` (`1`/`true`/`yes`), wie im Monitoring. Ist `MONITOR_API_KEY` leer, loggt die `lifespan` beim Start einmal einen ERROR mit Verweis auf `scripts/init-secrets.sh`, der Server läuft weiter. `test_hooks` liest das Schema über `app.openapi()`. `sse_push_e2e.sh` wartet auf einen Endpunkt ohne Doku-Schalter. `SERVER_ENABLE_DOCS` wird in Compose an den Server durchgereicht und steht in `.env.example`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_server_docs.py tests/test_hooks.py tests/test_openapi_snapshot.py tests/test_env_parity.py tests/test_schemathesis.py
Doku: → T5

### T3 — Monitoring: fail-fast und kein Auto-Schlüssel  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/core/config.py, apps/monitoring/tests/conftest.py, apps/monitoring/tests/test_config_env.py (neu, SPDX), apps/monitoring/tests/test_retention.py, apps/monitoring/tests/test_central_resolve.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @5bb6c3919 2026-11-24T11:45:13+01:00
Review: approve (.ah-out/review/kern-config-1/T3.verdict.json)
Änderung: R-0699. `SMTP_PORT`, `ALERT_LOG_RETENTION_DAYS` (Minimum 1), `DB_POOL_SIZE` und `DB_MAX_OVERFLOW` laufen über `env_int`. Ein Eintrag in `MONITOR_PUBLIC_RESOLVERS`, der keine IP ist, bricht ab (`ConfigError`). Ein leerer `MONITOR_API_KEY` bricht mit Verweis auf `scripts/init-secrets.sh` ab; `DATA_DIR/.api_key` wird weder geschrieben noch gelesen. `conftest.py` setzt einen Test-Schlüssel.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_config_env.py tests/test_retention.py tests/test_central_resolve.py tests/test_logging_config.py tests/test_require_agent.py
Doku: → T5

### T4 — CA-Issuer: LOG_LEVEL und gemeinsames Log-Format  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/main.py, apps/ca-issuer/tests/test_logging.py (neu, SPDX), docker-compose.yml
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @dab86e6cb 2026-11-24T11:48:12+01:00
Review: approve (.ah-out/review/kern-config-1/T4.verdict.json)
Änderung: R-0699. Der CA-Issuer liest `LOG_LEVEL` (ein unbekannter Wert bricht mit Variable und Wert ab) und loggt im Format von `ah_common.logging_config` (`%(asctime)s %(levelname)-8s [%(process)d] %(name)s %(message)s`, nach stderr). `ah_common` kommt nicht ins Image. Compose reicht `LOG_LEVEL` an den CA-Issuer durch.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_logging.py
Doku: → T5

### T5 — Doku DE+EN und CHANGELOG  [x]
Komponente: scripts · Dateien: docs/admin/installation.html, docs/en/admin/installation.html, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/admin/betrieb.html, docs/en/admin/operations.html, README.md, DEVELOPMENT.md, changelog.d/kern-config-1.md (neu), docs/developer/monitoring.html, docs/en/developer/monitoring.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @160ce0c05 2026-11-24T12:14:20+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: R-0699. Die Doku folgt der Spec: Abbruch bei ungültigem Wert, `MONITOR_API_KEY` ist Pflicht fürs Monitoring (Callout und Tabelle), `/api/docs` nur mit `SERVER_ENABLE_DOCS`, `LOG_LEVEL` auch für den CA-Issuer. Dazu das CHANGELOG-Fragment (umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende

### T6 — Doku: Web-Timeouts brechen bei ungültigem Wert ab  [x]
Komponente: scripts · Dateien: docs/admin/installation.html, docs/en/admin/installation.html, DEVELOPMENT.md, changelog.d/kern-config-1.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @055da2432 2026-11-24T12:31:59+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: R-0699, Fund der Abschlussprüfung. Die Tabellenzeilen zu `WEB_IDLE_TIMEOUT_MINUTES` und `WEB_SESSION_MAX_HOURS` versprechen noch den Rückfall auf 30/24; seit T1 bricht der Start ab. Dazu, in derselben Korrekturrunde: Der Startbefehl des Monitorings in `DEVELOPMENT.md` setzt `MONITOR_API_KEY`, und das CHANGELOG-Fragment nennt die nicht mehr gelesene `DATA_DIR/.api_key` als löschbar.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende

### T7 — Server-Tests: Schema ohne /openapi.json, Log-Zählung mit Schlüssel  [ ]
Komponente: server · Dateien: apps/server/tests/test_bounds.py, apps/server/tests/test_log_hygiene.py
Änderung: R-0699, Fund der PR-CI (#649, Shard 2/4). `test_bounds` holte das Schema über `app.openapi_url`, das ohne `SERVER_ENABLE_DOCS` jetzt `None` ist; es rendert `app.openapi()` wie die Route über `JSONResponse`. `test_log_hygiene` zählt die WARNING+-Zeilen der `lifespan`, und ein leerer `MONITOR_API_KEY` loggt seit T2 einen eigenen ERROR; der Test setzt einen Schlüssel.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_bounds.py tests/test_log_hygiene.py tests/test_server_docs.py
Doku: keine (nur Tests)

## Entscheidungen
- 2026-11-24: Health-Endpunkte bleiben außerhalb des Zugs (neuer API-Vertrag, Kevins Bereich); eigene Roadmap-Zeile.
- 2026-11-24: Der CA-Issuer bekommt `ah_common` nicht ins Image; seine eine Variable prüft er selbst, sein Dockerfile bleibt unberührt.
