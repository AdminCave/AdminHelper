<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-pycommon-1 — Task-Ledger
Status: geplant · Branch: feature/kern-pycommon-1 · Review: pro Task
Spec: docs/features/kern-pycommon-1.md (Roadmap R-0698)
Heavy: linux-full — Build-Kontext und Dockerfiles von server und monitoring, `docker-compose.test.yml`; kein PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Prüfung: `security` zusätzlich bei T2 (ssrf), T8 (Internal-Key) und T9 (SMTP-TLS) sowie, wenn `review.sh risk` es
verlangt. Reihenfolge: T1 zuerst (Lieferweg); T10 nach T2–T9; T11 zuletzt. Harness-Pfade in T1, T2, T8: Kevins Wort
2026-11-23 (Spec, „Lieferweg“).

## Tasks

### T1 — Paket ah_common, Lieferweg und pagination  [ ]
Komponente: server, monitoring · Dateien: apps/pycommon/pyproject.toml, apps/pycommon/ah_common/__init__.py, apps/pycommon/ah_common/pagination.py, apps/server/app/core/pagination.py, apps/monitoring/app/core/pagination.py, apps/server/requirements-dev.txt, apps/monitoring/requirements-dev.txt, Dockerfile, apps/monitoring/Dockerfile, .dockerignore, docker-compose.test.yml, .github/workflows/docker.yml, .github/workflows/ci.yml, .github/scripts/ci_changes.py, scripts/tests/run.sh, ruff.toml
Änderung: `apps/pycommon/ah_common/` mit `pagination.py` als erstem Modul (SPDX); beide Dienste importieren es (Fassade
oder direkte Imports, Spec „Dienst-Module“). Monitoring-Image aus dem Repo-Root, beide Images kopieren `ah_common`
nach `/app/ah_common/`; `-e ../pycommon` in beiden `requirements-dev.txt` (an `run.sh`, CI-`working-directory` und
`worktree-setup.sh` geprüft, sonst Conftest-Weg, `## Entscheidungen`); `ci_changes.py` und ruff-Pfade nehmen
`apps/pycommon` auf. Mehr als acht Dateien: der Lieferweg ist eine Einheit und nur zusammen prüfbar.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T11

### T2 — ssrf in ah_common  [ ]
Komponente: server, monitoring · Dateien: apps/pycommon/ah_common/ssrf.py, apps/server/app/core/ssrf.py, apps/monitoring/app/core/ssrf.py, apps/server/tests/test_ssrf_parity.py, scripts/dev/review-risk.txt
Änderung: Eine Implementierung in `ah_common/ssrf.py`; die Dienst-Module werden Fassaden oder entfallen, Tests patchen
das `ah_common`-Modul. Der Paritätstest entfällt, weil es nur noch eine Implementierung gibt; `review-risk.txt`
nennt `apps/pycommon/ah_common/ssrf.py`.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T11
Test-Löschung: apps/server/tests/test_ssrf_parity.py::* — ersetzt durch die eine Implementierung in ah_common (und T10)

### T3 — time in ah_common  [ ]
Komponente: server, monitoring · Dateien: apps/pycommon/ah_common/time.py, apps/server/app/core/time.py, apps/monitoring/app/core/time.py
Änderung: `utcnow_naive`, `iso_z` und eine SQL-Vorgabe für naive UTC-Spalten in `ah_common/time.py`; die Dienst-Module
bleiben Fassaden (98 Importeure) mit ihrem Eigenen (Server: Pydantic-Typ). Bestehende Alembic-Revisionen bleiben
unberührt; T3 prüft, dass das erzeugte SQL beider Dienste gleich bleibt.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T11

### T4 — logging_config in ah_common  [ ]
Komponente: server, monitoring · Dateien: apps/pycommon/ah_common/logging_config.py, apps/server/app/core/logging_config.py, apps/monitoring/app/core/logging_config.py
Änderung: Ein Format mit `[%(process)d]` und dieselbe `LOG_LEVEL`-Auswertung für beide Dienste; der Logger-Präfix
bleibt je Dienst.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T11

### T5 — Engine-Fabrik in ah_common  [ ]
Komponente: server, monitoring · Dateien: apps/pycommon/ah_common/database.py, apps/server/app/core/database.py, apps/monitoring/app/core/database.py, apps/monitoring/app/core/config.py
Änderung: Engine mit `pool_pre_ping`, Pool aus `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` (Vorgabe 10/20) und UTC-Session-Listener
in `ah_common/database.py`; das Monitoring liest die Pool-Variablen jetzt auch.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T11

### T6 — bounds-Helfer in ah_common  [ ]
Komponente: server, monitoring · Dateien: apps/pycommon/ah_common/bounds.py, apps/server/app/core/bounds.py, apps/monitoring/app/core/bounds.py
Änderung: `BIGINT_MAX`, `storable`, `readable`, `find_unstorable` als eine Implementierung; dienstspezifische
Grenzen bleiben in den Dienst-Modulen.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T11

### T7 — Validierungsfehler-Handler in ah_common  [ ]
Komponente: server, monitoring · Dateien: apps/pycommon/ah_common/errors.py, apps/server/app/main.py, apps/monitoring/app/main.py
Änderung: `_non_finite_as_null` und der `RequestValidationError`-Handler (`apps/server/app/main.py:279`,
`apps/monitoring/app/main.py:138`) als eine Implementierung; beide Apps registrieren sie.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T11

### T8 — Internal-Key-Vergleich in ah_common  [ ]
Komponente: server, monitoring · Dateien: apps/pycommon/ah_common/auth.py, apps/server/app/core/auth.py, apps/monitoring/app/core/auth.py, scripts/dev/review-risk.txt
Änderung: Der konstante Vergleich eines gelieferten mit dem erwarteten Key (`apps/monitoring/app/core/auth.py:14`,
`apps/server/app/core/auth.py:365`) als eine Funktion; Statuscodes bleiben je Dienst (Server 403, Monitoring 401,
Kevin 2026-11-23). `review-risk.txt` nennt `apps/pycommon/ah_common/auth.py`.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: → T11

### T9 — SMTP-Verbindung in ah_common  [ ]
Komponente: server, monitoring · Dateien: apps/pycommon/ah_common/smtp.py, apps/server/app/modules/notifications/sender.py, apps/monitoring/app/alerter.py
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
