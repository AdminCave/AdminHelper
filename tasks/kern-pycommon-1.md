<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-pycommon-1 — Task-Ledger
Status: aktiv · Branch: feature/kern-pycommon-1 · Review: pro Task
Spec: docs/features/kern-pycommon-1.md (Roadmap R-0698)
Heavy: linux-full — Build-Kontext und Dockerfiles von server und monitoring, `docker-compose.test.yml`; kein PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Prüfung: `security` zusätzlich bei T2 (ssrf), T8 (Internal-Key) und T9 (SMTP-TLS) sowie, wenn `review.sh risk` es
verlangt. Reihenfolge: T1 zuerst (Lieferweg); T10 nach T2–T9; T11 zuletzt. Harness-Pfade in T1, T2, T8: Kevins Wort
2026-11-23 (Spec, „Lieferweg“).

## Tasks

### T1 — Paket ah_common, Lieferweg und pagination  [x]
Komponente: server · Dateien: apps/pycommon/ah_common/__init__.py, apps/pycommon/ah_common/pagination.py, apps/server/app/core/pagination.py, apps/monitoring/app/core/pagination.py, Dockerfile, apps/monitoring/Dockerfile, docker-compose.test.yml, .github/workflows/docker.yml, .github/workflows/ci.yml, .github/scripts/ci_changes.py, scripts/tests/run.sh, ruff.toml, apps/server/app/modules/audit/router.py, apps/server/app/modules/connections/router.py, apps/server/app/modules/hooks/router.py, apps/server/app/modules/notifications/router.py, apps/server/app/modules/servers/router.py, apps/monitoring/app/routers/alerts.py, apps/monitoring/app/routers/checks.py, apps/monitoring/app/routers/findings.py, apps/monitoring/app/routers/objects.py, apps/server/tests/conftest.py, apps/monitoring/tests/conftest.py, apps/server/tests/test_ci_changes.py, apps/monitoring/Dockerfile.dockerignore, scripts/tests/sse_push_e2e.sh
Evidenz: run.sh[quick] server monitoring: 5 passed, 0 failed, 13 skipped @2cc657913 2026-11-23T21:45:39+01:00
Review: approve (.ah-out/review/kern-pycommon-1/T1.verdict.json)
Änderung: `apps/pycommon/ah_common/` mit `pagination.py` als erstem Modul (SPDX); beide Dienste importieren es (Fassade
oder direkte Imports, Spec „Dienst-Module“). Monitoring-Image aus dem Repo-Root, beide Images kopieren `ah_common`
nach `/app/ah_common/`; `-e ../pycommon` in beiden `requirements-dev.txt` (an `run.sh`, CI-`working-directory` und
`worktree-setup.sh` geprüft, sonst Conftest-Weg, `## Entscheidungen`); `ci_changes.py` und ruff-Pfade nehmen
`apps/pycommon` auf. Mehr als acht Dateien: der Lieferweg ist eine Einheit und nur zusammen prüfbar.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T11

### T2 — ssrf in ah_common  [x]
Komponente: server · Dateien: apps/pycommon/ah_common/ssrf.py, apps/server/app/core/ssrf.py, apps/monitoring/app/core/ssrf.py, apps/server/tests/test_ssrf_parity.py, scripts/dev/review-risk.txt, apps/monitoring/alembic/env.py, apps/monitoring/app/alerter.py, apps/monitoring/app/checkers/http.py, apps/monitoring/tests/test_alembic_logging.py, apps/monitoring/tests/test_alert_bundle.py, apps/monitoring/tests/test_alerter.py, apps/monitoring/tests/test_alerter_dispatch.py, apps/monitoring/tests/test_checker_messages.py, apps/monitoring/tests/test_http_checker.py, apps/monitoring/tests/test_ssrf.py, apps/monitoring/tests/test_ssrf_proxy_route.py, apps/server/app/modules/hooks/script_worker.py, apps/server/app/modules/notifications/schemas.py, apps/server/app/modules/notifications/sender.py, apps/server/tests/shard_weights.toml, apps/server/tests/test_alembic_logging.py, apps/server/tests/test_ci_changes.py, apps/server/tests/test_hooks_http_ssrf.py, apps/server/tests/test_notification_channels.py, apps/server/tests/test_ssrf.py, apps/server/tests/test_ssrf_pin.py, apps/server/tests/test_ssrf_properties.py, apps/server/app/modules/hooks/script_runner.py, apps/server/tests/conftest.py, apps/monitoring/tests/conftest.py, docs/developer/cicd.html, docs/en/developer/cicd.html, apps/server/app/core/config.py
Evidenz: run.sh[quick] server monitoring: 5 passed, 0 failed, 13 skipped @dea6663ce 2026-11-24T01:23:50+01:00
Review: approve (.ah-out/review/kern-pycommon-1/T2.verdict.json)
Änderung: Eine Implementierung in `ah_common/ssrf.py`; die Dienst-Module werden Fassaden oder entfallen, Tests patchen
das `ah_common`-Modul. Der Paritätstest entfällt, weil es nur noch eine Implementierung gibt; `review-risk.txt`
nennt `apps/pycommon/ah_common/ssrf.py`.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T11
Test-Löschung: apps/server/tests/test_ssrf_parity.py::* — ersetzt durch die eine Implementierung in ah_common (und T10)

### T3 — time in ah_common  [x]
Komponente: server · Dateien: apps/pycommon/ah_common/time.py, apps/server/app/core/time.py, apps/monitoring/app/core/time.py, apps/server/tests/test_utc_timestamp_defaults.py, apps/monitoring/tests/test_core_time.py
Evidenz: run.sh[quick] server monitoring: 5 passed, 0 failed, 13 skipped @fa0a9118e 2026-11-24T02:20:44+01:00
Review: approve (.ah-out/review/kern-pycommon-1/T3.verdict.json)
Änderung: `utcnow_naive`, `iso_z` und eine SQL-Vorgabe für naive UTC-Spalten in `ah_common/time.py`; die Dienst-Module
bleiben Fassaden (98 Importeure) mit ihrem Eigenen (Server: Pydantic-Typ). Bestehende Alembic-Revisionen bleiben
unberührt; T3 prüft, dass das erzeugte SQL beider Dienste gleich bleibt.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T11

### T4 — logging_config in ah_common  [x]
Komponente: server · Dateien: apps/pycommon/ah_common/logging_config.py, apps/server/app/core/logging_config.py, apps/monitoring/app/core/logging_config.py, apps/monitoring/tests/test_logging_config.py, apps/server/tests/test_env_parity.py
Evidenz: run.sh[quick] server monitoring: 5 passed, 0 failed, 13 skipped @763e68296 2026-11-24T04:12:09+01:00
Review: approve (.ah-out/review/kern-pycommon-1/T4.verdict.json)
Änderung: Ein Format mit `[%(process)d]` und dieselbe `LOG_LEVEL`-Auswertung für beide Dienste; der Logger-Präfix
bleibt je Dienst.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T11

### T5 — Engine-Fabrik in ah_common  [x]
Komponente: server · Dateien: apps/pycommon/ah_common/database.py, apps/server/app/core/database.py, apps/monitoring/app/core/database.py, apps/monitoring/app/core/config.py, apps/server/tests/conftest.py, apps/monitoring/tests/test_db_pool_config.py, docker-compose.yml, .env.example, apps/server/tests/test_stream.py
Evidenz: run.sh[quick] server monitoring: 5 passed, 0 failed, 13 skipped @8b18d774b 2026-11-24T06:02:54+01:00
Review: approve (.ah-out/review/kern-pycommon-1/T5.verdict.json)
Änderung: Engine mit `pool_pre_ping`, Pool aus `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` (Vorgabe 10/20) und UTC-Session-Listener
in `ah_common/database.py`; das Monitoring liest die Pool-Variablen jetzt auch.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T11

### T6 — bounds-Helfer in ah_common  [x]
Komponente: server · Dateien: apps/pycommon/ah_common/bounds.py, apps/server/app/core/bounds.py, apps/monitoring/app/core/bounds.py, apps/server/app/modules/hooks/router.py
Evidenz: run.sh[quick] server monitoring: 5 passed, 0 failed, 13 skipped @e2a85c9f8 2026-11-24T06:59:29+01:00
Review: approve (.ah-out/review/kern-pycommon-1/T6.verdict.json)
Änderung: `BIGINT_MAX`, `storable`, `readable`, `find_unstorable` als eine Implementierung; dienstspezifische
Grenzen bleiben in den Dienst-Modulen.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T11

### T7 — Validierungsfehler-Handler in ah_common  [ ]
Komponente: server · Dateien: apps/pycommon/ah_common/errors.py, apps/server/app/main.py, apps/monitoring/app/main.py
Änderung: `_non_finite_as_null` und der `RequestValidationError`-Handler (`apps/server/app/main.py:279`,
`apps/monitoring/app/main.py:138`) als eine Implementierung; beide Apps registrieren sie.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T11

### T8 — Internal-Key-Vergleich in ah_common  [ ]
Komponente: server · Dateien: apps/pycommon/ah_common/auth.py, apps/server/app/core/auth.py, apps/monitoring/app/core/auth.py, scripts/dev/review-risk.txt
Änderung: Der konstante Vergleich eines gelieferten mit dem erwarteten Key (`apps/monitoring/app/core/auth.py:14`,
`apps/server/app/core/auth.py:365`) als eine Funktion; Statuscodes bleiben je Dienst (Server 403, Monitoring 401,
Kevin 2026-11-23). `review-risk.txt` nennt `apps/pycommon/ah_common/auth.py`.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T11

### T9 — SMTP-Verbindung in ah_common  [ ]
Komponente: server · Dateien: apps/pycommon/ah_common/smtp.py, apps/server/app/modules/notifications/sender.py, apps/monitoring/app/alerter.py
Änderung: TLS-Kontext mit `SMTP_CA_FILE`, SMTPS auf 465 oder STARTTLS sonst, Login und Senden als eine Funktion
(`apps/server/app/modules/notifications/sender.py:88`, `apps/monitoring/app/alerter.py:977`); die Fehlerabbildung
bleibt je Dienst.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T11

### T10 — Wächter gegen neue Kopien  [ ]
Komponente: server · Dateien: apps/server/tests/test_no_python_copies.py
Änderung: Ein AST-Test (SPDX) über `apps/server/app` und `apps/monitoring/app`: zwei Funktionen mit gleichem Namen und
gleichem normalisiertem Rumpf (ohne Docstrings) schlagen an; eine kurze Ausnahmeliste mit Begründung.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_no_python_copies.py
Doku: → T11

### T11 — Doku  [ ]
Komponente: scripts · Dateien: docs/developer/index.html, docs/en/developer/index.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, DEVELOPMENT.md, changelog.d/kern-pycommon-1.md
Änderung: `apps/pycommon` in der Architektur (DE+EN) und im Dev-Setup; `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` gelten auch
fürs Monitoring; PID im Monitoring-Log; CHANGELOG `### Changed`. Pfade der Doku-Seiten in der Task frisch prüfen.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- T1 (Lieferweg): Tests finden `ah_common` über eine `sys.path`-Zeile in beiden `tests/conftest.py`, nicht über
  `-e ../pycommon` in `requirements-dev.txt`. pip löst den relativen Pfad gegen das Arbeitsverzeichnis auf (Probe mit
  pip 25.1), und `ci.yml`/`nightly.yml` installieren die Dateien vom Repo-Root aus; ein Editable-Install zeigte dazu
  auf genau einen Worktree. Damit entfällt `apps/pycommon/pyproject.toml`.
- T1: Das Monitoring-Image nimmt seinen Kontext über `apps/monitoring/Dockerfile.dockerignore` (Allowlist wie frps),
  nicht über die Root-`.dockerignore`; die bleibt unverändert.
- T1: `pagination` hatte nur neun Importeure: die Dienst-Module entfallen, die Imports zeigen direkt auf `ah_common`.
- T2: Keine Fassaden für `ssrf`: Tests patchen Modul-Globals (`_resolve`, `socket.getaddrinfo`, `_DNS_*`), über eine
  Fassade griffe das still ins Leere. Beide Dienste und alle Tests importieren `ah_common.ssrf` direkt.
- T2: Der Hook-Worker (`script_runner.py`) bekommt neben `server/` das Verzeichnis, aus dem der Server `ah_common`
  geladen hat, in `PYTHONPATH` (im Image dasselbe `/app`); die Conftests geben `apps/pycommon` über `PYTHONPATH` an
  die Python-Subprozesse der Tests weiter.
- T3: Die gemeinsame SQL-Vorgabe ist das `FunctionElement` des Monitorings (`@compiles`, SQLite `CURRENT_TIMESTAMP`),
  nicht `func.timezone`: die DDL beider Dienste bleibt zeichengleich (vorher/nachher je `CreateTable` über die ganze
  Metadata verglichen). In Statements (`onupdate`, `ON CONFLICT … SET`) rendert der Server `'UTC'` jetzt als Literal
  statt als Bind-Parameter; ein Test fährt das gegen Postgres in einer Berlin-Session. Der Helfer heißt wie bisher
  `iso_utc` (der Plan sagte `iso_z`).
- T4: Die Dienst-Module `app.core.logging_config` bleiben als Re-Export: `test_scheduler_schema_gate.py` patcht
  `configure_logging` dort, und `scheduler_main` importiert es zur Laufzeit von dort.
- T5: `get_db` kommt aus `ah_common.database.session_dependency(SessionLocal)`, sonst bliebe es als identische
  Kopie in beiden Diensten (T10 würde sie melden); `engine`, `SessionLocal` und `Base` bleiben je Dienst (eigene DB,
  eigene Metadaten). Der UTC-Listener heißt öffentlich `set_session_utc`; die Server-Conftest importiert ihn von dort.
- T5: Compose reicht `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` auch dem Monitoring durch, sonst bliebe das Lesen im Betrieb
  wirkungslos; `.env.example` nennt es. Vorgabe weiter 10/20.
