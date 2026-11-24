<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Eine Regel für Konfigurationsfehler in allen drei Diensten (kern-config-1)

Roadmap: R-0699. Kevin 2026-11-24:
- Fail-fast mit klarer Meldung in Server, Monitoring und CA-Issuer.
- Das Monitoring startet ohne `MONITOR_API_KEY` nicht (kein Auto-Schlüssel mehr). Der Server loggt dann einen ERROR
  und läuft weiter.
- Die API-Doku des Servers liegt hinter `SERVER_ENABLE_DOCS`, Vorgabe aus.

## Problem

Stand origin/main@6c21dc81c:

- **Ungültige Zahlen.** Der Server liest seine Zahlen-Variablen mit nacktem `int(...)`
  (`apps/server/app/core/config.py:212` bis `:392`, etwa `SMTP_PORT` in `:333`). Ein Tippfehler bricht den Import mit
  einem `ValueError` ohne Variablennamen ab. Das Monitoring fällt für `SMTP_PORT` (`apps/monitoring/app/core/config.py:79`)
  und `ALERT_LOG_RETENTION_DAYS` (`:97`) still auf die Vorgabe zurück. Dasselbe tun `WEB_IDLE_TIMEOUT_MINUTES` und
  `WEB_SESSION_MAX_HOURS` im Server (`config.py:128`, `:154`), `MONITOR_PUBLIC_RESOLVERS` im Monitoring (`apps/monitoring/app/core/config.py:140`) und
  `LOG_LEVEL` in `ah_common/logging_config.py`. Dieselbe Art Fehler wirkt also je Dienst und Variable entgegengesetzt.
- **Leerer `MONITOR_API_KEY`.** Ist der Schlüssel leer, erzeugt das Monitoring sich einen eigenen und legt ihn unter
  `DATA_DIR/.api_key` ab (`apps/monitoring/app/core/config.py:38`). Der Server sendet weiter den leeren Wert
  (`apps/server/app/core/config.py:244`). Jeder Aufruf über den Monitoring-Proxy endet dann mit 401, ohne dass ein
  Log den Grund nennt.
- **API-Doku.** Der Server liefert `/api/docs` und `/openapi.json` immer aus (`apps/server/app/main.py:268`).
  Monitoring und CA-Issuer schalten beides nur mit `MONITOR_ENABLE_DOCS` bzw. `CA_ENABLE_DOCS` ein
  (`apps/monitoring/app/main.py:122`, `apps/ca-issuer/app/config.py:169`).
- **Logging im CA-Issuer.** Der CA-Issuer ignoriert `LOG_LEVEL` und hat ein eigenes Format
  (`apps/ca-issuer/app/main.py:30`). Server und Monitoring teilen seit R-0698 `ah_common.logging_config`.

## Ziel

- **Eine Regel:** Hat eine Konfigurationsvariable einen ungültigen Wert, bricht der Dienst beim Start ab. Die Meldung
  nennt den Namen der Variablen, den Wert und was erwartet ist. Ausnahme: Bei Geheimnissen nennt sie den Wert nicht.
  Fehlt eine Variable, gilt wie bisher ihre Vorgabe.
- `ah_common/env.py` (neu) stellt dafür `env_int(name, default, *, minimum=None)` und `ConfigError` bereit, für Server
  und Monitoring. `ConfigError` ist ein `ValueError`. Der CA-Issuer bekommt `ah_common` nicht ins Image (sein
  Dockerfile bleibt unberührt) und prüft seine eine Variable selbst.
- **Monitoring ohne Schlüssel:** Der Start bricht mit `ConfigError` ab und verweist auf `scripts/init-secrets.sh`.
  `DATA_DIR/.api_key` wird weder geschrieben noch gelesen.
- **Server ohne Schlüssel:** Der Server loggt beim Start einmal einen ERROR und läuft weiter. Monitoring ist für ihn
  optional.
- **Server-Doku:** `SERVER_ENABLE_DOCS` (`1`/`true`/`yes`) schaltet `/api/docs` und `/openapi.json` ein, die Vorgabe
  ist aus. Tests lesen das Schema über `app.openapi()`.
- **CA-Issuer:** liest `LOG_LEVEL` (unbekannter Wert ⇒ Abbruch) und loggt im Format von `ah_common.logging_config`.

## Nicht-Ziele

- **Health-Endpunkte vereinheitlichen.** Der Server hat keinen HTTP-Health-Endpunkt (Compose prüft per TCP), das
  Monitoring hat `/health`, der CA-Issuer `/healthz`. Ein neuer Endpunkt ist ein API-Vertrag und damit Kevins
  Entscheidung. Er bekommt eine eigene Roadmap-Zeile.
- `ah_common` im CA-Issuer-Image.
- Neue Pflichtvariablen außer `MONITOR_API_KEY` im Monitoring.
- JSON-Logs.

## Betroffene Komponenten und Dateien

- **pycommon:** `apps/pycommon/ah_common/env.py` (neu), `apps/pycommon/ah_common/logging_config.py`.
- **server:**
  - `apps/server/app/core/config.py`, `apps/server/app/main.py`.
  - Tests: `test_config_env.py` (neu), `test_web_idle_timeout.py`, `test_web_session_max.py`, `test_logging_config.py`,
    `test_hooks.py`, `test_server_docs.py` (neu).
  - `scripts/tests/sse_push_e2e.sh`: wartet heute auf `/api/docs`.
- **monitoring:**
  - `apps/monitoring/app/core/config.py`.
  - Tests: `conftest.py`, `test_retention.py`, `test_logging_config.py`, `test_central_resolve.py` (Resolver-Liste),
    `test_config_env.py` (neu).
- **ca-issuer:** `apps/ca-issuer/app/main.py`, Test `test_logging.py` (neu).
- **Konfiguration:** `docker-compose.yml` (`SERVER_ENABLE_DOCS` am Server, `LOG_LEVEL` am CA-Issuer), `.env.example`.

## Datenmodell, API, Migrationen

- Keine Migration.
- **API:** `/api/docs` und `/openapi.json` des Servers antworten ohne `SERVER_ENABLE_DOCS` mit 404 (Kevins
  Entscheidung). Web und Desktop lesen das Schema nicht zur Laufzeit. Der OpenAPI-Snapshot bleibt gleich, weil er
  `app.openapi()` liest.

## Trade-offs

- **Gemeinsamer Helfer statt Einzel-`try`.** Ein Helfer in `ah_common` hält die Meldung in beiden Diensten gleich.
  `test_no_python_copies` verlangt das ohnehin.
- **Abbruch beim Import statt in `lifespan`.** Die Zahlen werden heute beim Import gelesen. Ein `ConfigError` dort
  beendet uvicorn, Scheduler und Hook-Worker gleich, mit der Meldung als letzter Zeile des Tracebacks.
  Der Lesezeitpunkt wandert nicht, das hielte den Zug klein.

## Risiken und Rollback

- **Bestehende Installationen mit Tippfehler starten nach dem Update nicht mehr.** Das ist gewollt: Die Meldung nennt
  die Variable, `update.sh` prüft die Dienste nach dem Start.
- **Leerer Schlüssel nach dem Update.** `update.sh` ruft `init-secrets.sh`, das einen leeren `MONITOR_API_KEY` füllt.
  Betroffen sind nur Hand- und Dev-Setups. Die liefen schon vorher mit stillem 401.
- **Testskripte.** Skripte, die den Server starten und auf `/api/docs` warten, laufen in den Timeout
  (`sse_push_e2e.sh`); die Task stellt sie um. Stack-Skripte setzen `MONITOR_API_KEY` schon (`lib_e2e_stack.sh:242`,
  `init-secrets.sh` in `box_serverbox.sh`).
- **Rollback:** Revert des Merge-Commits; keine Daten.

## Doku-Impact

DE und EN, in einer Doku-Task:
- Installation (Callout zum leeren `MONITOR_API_KEY`, Variablentabelle).
- Troubleshooting.
- API-Referenz (`/api/docs` nur mit `SERVER_ENABLE_DOCS`).
- Betrieb/Operations (`LOG_LEVEL` gilt jetzt auch für den CA-Issuer).
- README und DEVELOPMENT.md (`/api/docs`).
- `changelog.d/kern-config-1.md`.

## Offene Fragen

Keine. Die drei Fragen aus Kevins Bereich hat Kevin am 2026-11-24 beantwortet. Die Health-Vereinheitlichung bekommt
eine eigene Zeile.
