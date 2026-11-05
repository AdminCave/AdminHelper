<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-deps-2 — Python-Abhängigkeiten der drei Dienste auf aktuell

Zug `tasks/kern-deps-2.md` mit R-1037. R-1038 (ruff 0.17) ist aus dem Zug genommen. Das ruff-Update ändert
`scripts/vm/bootstrap_linux.sh`, einen Harness-Pfad (CLAUDE.md §4), und `.github/workflows/ci.yml`, das Kevin
merged. Der Toolchain-Lockstep verlangt beide Stellen im selben Commit (`ruff.toml:11`). Es fährt in einem eigenen
Zug, sobald Kevin die Harness-Änderung freigibt (offene Frage 1).

## Problem / Motivation

R-1037 (REF, Kevin 2026-11-02: alles auf aktuelle LTS/Stable): Die Locks der drei Dienste hängen hinter PyPI und
unterscheiden sich untereinander. Stand der Locks und von PyPI am 2026-11-04:

| Paket | Server | Monitoring | CA-Issuer | PyPI |
|---|---|---|---|---|
| fastapi | 0.138.0 | 0.138.0 | 0.139.0 | 0.162.0 |
| starlette | 1.3.1 | 1.3.1 | 1.3.1 | 1.10.0 |
| uvicorn | ≥ 0.49 | ≥ 0.49 | ≥ 0.49 | 0.54.0 |
| sqlalchemy | 2.0.50 | 2.0.50 | 2.0.50 | 2.1.8 |
| alembic | 1.18.4 | 1.18.4 | — | 1.20.1 |
| pydantic | 2.13.4 | 2.13.4 | 2.13.4 | 2.14.2 |
| websockets | 16.0 | 16.0 | 16.0 | 17.4 |
| redis | 8.0.0 | — | — | 8.1.0 |
| cryptography | 50.0.1 | — | 50.0.1 | 50.0.2 |
| psycopg(-binary) | 3.3.4 | 3.3.4 | 3.3.4 | 3.3.7 |
| python-multipart | 0.0.32 | — | — | 0.0.33 |
| apscheduler | 3.11.2 | 3.11.2 | — | 3.11.3 |

Dazu die Dev-Pakete: hypothesis 6.168.3 → 6.170.14, schemathesis 4.29.0 → 4.33.0, pytest-alembic → 0.13.2,
testcontainers → 4.15.0, pytest-cov → 7.1.0. `pytest<9.2` (`apps/server/requirements-dev.txt`, R-0916) wartete
auf ein pytest-alembic, das unter pytest 9.2 sammelt.

## Ziel & Nicht-Ziele

Ziel:
- Jeder Dienst steht auf dem aktuellen Release jedes direkten Pakets.
- Die Böden in `requirements.in` stehen auf diesem Release, und gemeinsame Pakete haben in allen drei Diensten
  denselben Boden.
- Jeder Lock ist mit `pip-compile --generate-hashes --upgrade` neu erzeugt, im Python des Dockerfiles (3.14,
  `DEVELOPMENT.md:65`).
- Die Suiten sind grün.

Nicht-Ziele:
- ruff (R-1038, siehe oben).
- Python selbst (3.14/3.15 bleiben), Redis-Server 8 (R-1032, kern-laufzeit-2), Postgres (R-1035).
- Kein Umbau über das hinaus, was ein Release verlangt.

## Betroffene Komponenten & Dateien

- `apps/server/requirements.in`, `requirements.txt`, `requirements-dev.txt`
- `apps/monitoring/requirements.in`, `requirements.txt`, `requirements-dev.txt`
- `apps/ca-issuer/requirements.in`, `requirements.txt`, `requirements-dev.txt`
- Code nur, wo ein Release es verlangt, dazu die OpenAPI-Snapshots (`apps/*/tests/openapi.snapshot.json`), falls
  FastAPI die Ausgabe ändert.
- `THIRD_PARTY_LICENSES.md`, `docs/developer/index.html` (DE nennt „SQLAlchemy 2.0“), `changelog.d/kern-deps-2.md`

## Datenmodell / API / Migrationen

Keine Migration. Der API-Vertrag soll gleich bleiben, und die OpenAPI-Snapshot-Tests zeigen jede Änderung. Ändert
FastAPI nur die Form der Ausgabe (Reihenfolge, Titel, neue Standardfelder), zieht die Task den Snapshot nach und
nennt den Unterschied unter `## Entscheidungen`. Ändert sich das Verhalten einer Route, ist das Kevins Bereich: die
Task bekommt `[?]`.

## Externe Integrationen

- **SQLAlchemy 2.1** (docs.sqlalchemy.org/en/21/changelog/migration_21.html):
  - greenlet kommt nur noch mit dem Extra `[asyncio]` (Server und Monitoring haben es; der CA-Issuer nutzt
    kein async, greenlet fällt aus seinem Lock).
  - Autoflush läuft auch vor `text()`.
  - `Select.filter_by()` sucht in allen FROM-Entitäten (kein Treffer im Code, `grep filter_by(`).
  - `mapped_column.default` und `insert_default` schließen sich aus (kein Treffer).
  - `postgresql://` meint jetzt psycopg 3 (wir nennen `+psycopg` ausdrücklich, `apps/ca-issuer/app/db.py:153`
    schreibt den Treiber um).
- **FastAPI 0.143–0.162** (GitHub-Releases, Abschnitte „Breaking Changes“):
  - 0.143: OpenTelemetry nur noch auf Opt-in.
  - 0.145: `openapi_prefix` und `**extra` sind weg; 0.146: `root_path` ist veraltet (kein Treffer).
  - 0.147–0.150, 0.162: Formulare, also fehlende Bool-Felder und leere Werte (kein `Form(` im Code).
  - 0.151: JSON-`null` und ein weggelassener Wert im Body werden unterschieden. 35 Stellen nutzen
    `exclude_unset`/`model_fields_set`; die PATCH-Tests zeigen, ob sich das Verhalten ändert.
  - 0.155: `**extra` an Request-Parametern ist weg.
- starlette 1.10, websockets 17, uvicorn 0.54: Release-Notes beim Bau lesen; wir importieren `websockets` nicht
  selbst.

## Trade-offs & Alternativen

- **Ein Dienst je Task** statt eines großen Commits: jede Suite für sich, jeder Lock einzeln zurücknehmbar.
  Alternative: Server zuerst allein und die anderen später; das ließe die Drift zwischen den Diensten stehen, die die
  Zeile beheben will.
- **`pytest<9.2`:** Die Server-Task hebt die Grenze, wenn pytest-alembic 0.13.2 unter pytest 9.2 sammelt; sonst
  bleibt sie mit neuem Datum im Kommentar.
- **`THIRD_PARTY_LICENSES.md`** ändert auch `feature/kern-web-4` (#378), aber dort den Abschnitt `apps/web/`
  (Zeile ~194), hier die Python-Tabelle (Zeilen 50–80). Die Abschnitte sind disjunkt, der Basis-Merge vor dem PR
  zeigt einen Konflikt sofort.

## Risiken & Rollback

- SQLAlchemy 2.1 ist eine Minor mit Brüchen; die Suiten der Dienste (Postgres) und die Alembic-Tests sind der Beweis.
- FastAPI 0.151 (null und weggelassen) kann PATCH-Semantik verschieben; die PATCH-Tests und die OpenAPI-Snapshots
  zeigen das.
- Der Stack (Gateway, mTLS, SSE über Redis) zeigt sich erst im Sammellauf: `Heavy: linux-full`.
- Rollback: ein Commit je Dienst, Revert genügt.

## Doku-Impact

`THIRD_PARTY_LICENSES.md` (Versionen, die fastapi-Notiz), `docs/developer/index.html` („SQLAlchemy 2.1“; EN sagt
„SQLAlchemy 2“ und bleibt), `changelog.d/kern-deps-2.md` (`### Changed`).

## Offene Fragen

1. **R-1038 (ruff 0.17.3):** Das Update ändert `scripts/vm/bootstrap_linux.sh` (Harness-Pfad) und
   `.github/workflows/ci.yml` (Merge durch Kevin). Darf ein eigener Zug `ci-5` beides als eigene Task ändern?
   - Empfehlung: ja. Der Lockstep erzwingt alle vier Stellen gemeinsam, und Kevin merged ihn ohnehin.
