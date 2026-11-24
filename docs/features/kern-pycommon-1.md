<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Gemeinsamer Python-Code für Server und Monitoring (kern-pycommon-1)

Roadmap: R-0698. Kevin 2026-11-23: „löse das Problem langfristig mit eigenem [Paket], wenn es sinnvoll ist, und du
mergst auch ohne mich zu fragen“; der Internal-Key-Status bleibt je Dienst (Monitoring 401, Server 403).

## Problem

`apps/server` und `apps/monitoring` tragen Kopien derselben Helfer, die auseinanderlaufen. Nur `core/ssrf.py` hat einen
Paritätstest (`apps/server/tests/test_ssrf_parity.py`). Stand origin/main@cd2f65732:

- `core/pagination.py`: gleicher Code, andere Docstrings.
- `core/ssrf.py`: gleicher Code (Paritätstest), andere Kommentare.
- `core/time.py`: `utcnow_naive`/`iso_z` doppelt. Die SQL-Vorgabe für naive UTC-Spalten ist zweimal verschieden gebaut:
  im Server `utc_now_sql()` mit `func.timezone`, im Monitoring ein eigenes `FunctionElement` mit `@compiles`.
- `core/logging_config.py`: Das Format des Monitorings hat kein `[%(process)d]`.
- `core/database.py`: Der Server liest die Pool-Größe aus `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`, das Monitoring hat 10/20
  fest. Der UTC-Session-Listener existiert zweimal.
- `core/bounds.py`: `storable`/`readable`/`find_unstorable` und `BIGINT_MAX` mit je eigenen Namen.
- `main.py`: `_non_finite_as_null` und `_validation_error` doppelt (`apps/server/app/main.py:279`,
  `apps/monitoring/app/main.py:138`).
- Internal-Key-Vergleich: Server `apps/server/app/core/auth.py:365`, Monitoring
  `apps/monitoring/app/core/auth.py:14`.
- SMTP-Verbindung (TLS-Kontext, `SMTP_CA_FILE`, SMTPS oder STARTTLS, Login):
  `apps/server/app/modules/notifications/sender.py:88`, `apps/monitoring/app/alerter.py:977`.

## Ziel und Nicht-Ziele

Ziel:
- Ein Paket `ah_common` unter `apps/pycommon/` ist die einzige Implementierung dieser Helfer, und beide Dienste
  importieren es.
- Ein Test verhindert neue Kopien. Er schlägt an, wenn `apps/server/app` und `apps/monitoring/app` eine Funktion mit
  gleichem normalisiertem Rumpf definieren.

Nicht-Ziele:
- `ca-issuer`. Er hat keine dieser Kopien.
- Die dienstspezifische Middleware. Server und Monitoring teilen dort keine Logik.
- Fehlertexte und Statuscodes je Dienst, darunter Internal-Key 401/403.
- Ein PyPI-Paket oder eine eigene Versionierung.

## Lieferweg

- **Laufzeit:** Beide Dockerfiles kopieren `apps/pycommon/ah_common/` nach `/app/ah_common/`, neben `/app/app/`. Uvicorn
  und Alembic laufen mit `/app` als Arbeitsverzeichnis (`prepend_sys_path = .`), der Import braucht also kein pip.
- **Build-Kontext:** Das Monitoring-Image wird vom Repo-Root aus gebaut, wie das Server-Image. Das betrifft:
  - `apps/monitoring/Dockerfile` (COPY-Pfade)
  - `.github/workflows/docker.yml`
  - `.github/workflows/ci.yml` (Image-Lock-Matrix)
  - `docker-compose.test.yml`
  - `.dockerignore`
- **Dev und CI:** `requirements-dev.txt` beider Dienste bekommt `-e ../pycommon`, mit `apps/pycommon/pyproject.toml`.
  Ob pip den Pfad relativ zum Aufrufer auflöst, prüft T1 an den echten Einstiegen: `run.sh`, die CI-Jobs mit
  `working-directory` und `worktree-setup.sh`. Trägt der Weg nicht, wird `ah_common` in T1 über die Conftests
  eingebunden; das steht dann in `## Entscheidungen`.
- **Harness:** Kevins Wort 2026-11-23 deckt diese Änderungen; Kevin hat sie ausdrücklich zum Selbst-Mergen freigegeben.
  - `.github/scripts/ci_changes.py`: `apps/pycommon/**` löst Server und Monitoring aus.
  - `ruff`-Pfade in `ci.yml` und `run.sh`.
  - `scripts/dev/review-risk.txt`: `ah_common/ssrf.py` und `ah_common/auth.py` werden Risikopfade.

## Dienst-Module

Wo ein Dienst-Modul viele Importeure hat (etwa `app.core.time` mit 98 Dateien) oder Eigenes trägt, bleibt es als dünne
Fassade, die aus `ah_common` re-exportiert. Sonst wandern die Imports direkt. Tests, die Modul-Globals patchen (etwa
`socket.getaddrinfo` in `ssrf`), patchen danach das `ah_common`-Modul.

## Verhaltensänderungen

- Das Monitoring loggt die PID (`[%(process)d]`) wie der Server. Das sieht man in `docker compose logs`.
- Das Monitoring liest `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` wie der Server. Die Vorgabe bleibt 10/20.
- Die SQL-Vorgabe für naive UTC-Spalten ist eine Implementierung. Ob die Migrationen des Monitorings davon berührt
  sind, prüft T3. Eine Alembic-Revision entsteht dabei nicht: Server-Defaults in bestehenden Revisionen bleiben
  unverändert.

## Risiken und Rollback

- **Build-Kontext:** Ein falscher Kontext oder `.dockerignore` bricht das Monitoring-Image. Die PR-CI (Image-Lock) und
  der Stack-Job auf dem PR prüfen das.
- **Gepatchte Globals:** Ein Test, der eine Kopie gepatcht hat, verliert seine Wirkung still. Jede Task fährt die
  betroffenen Tests beider Dienste, und der Prüfer macht eine Gegenprobe.
- **Rollback:** Jede Task ist ein Commit und einzeln revertierbar. T1 trägt den Lieferweg.

## Doku-Impact

`docs/developer/` (Architektur, DE und EN): Abschnitt zu `apps/pycommon`. `DEVELOPMENT.md`: Dev-Setup. Konfiguration:
`DB_POOL_SIZE`/`DB_MAX_OVERFLOW` auch fürs Monitoring. CHANGELOG `### Changed`.

## Offene Fragen

Keine. Der 401/403-Unterschied bleibt (Kevin).
