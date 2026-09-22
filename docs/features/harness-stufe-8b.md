<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 8b — Generatoren: Schemathesis, Hypothesis, Postgres-Concurrency, pytest-alembic

Roadmap-Zeile R-0005 · Quelle: privates Roadmap-Dokument §Stufe 8 (8b) · Stand 2026-09-18.

## Problem / Motivation

8a hat Verträge zwischen zwei Wahrheiten gepinnt. Was fehlt, sind Tests, die **Eingaben erzeugen**, die kein
Mensch hinschreibt: die API mit schema-generierten Anfragen unter jeder Auth-Rolle (Schemathesis), Escaping-Code mit
allen Zeichen (Hypothesis), ein Lock unter echter Gleichzeitigkeit auf Postgres, und die Migrationskette als
Round-Trip mit Seed-Daten. Drei der Release-Defekte der Historie waren Escaping- und Auth-Fehler dieser Klasse.
Alles VM-frei, Sekunden bis Minuten, ohne LLM.

Stand heute (Exploration 2026-09-18): `hypothesis`, `schemathesis`, `pytest-alembic` sind nirgends installiert
(PyPI: 6.168.0, 4.27.3, 0.12.1); nur `apps/server` hat eine `requirements-dev.txt`, Monitoring und CA-Issuer installieren
`pytest` ad hoc in `run.sh` und `ci.yml`; es gibt keinen TOML-Parser im Server (`tomllib` ist in Python 3.11+ Stdlib) und
keinen Line-Protocol-Parser im Monitoring; `with_for_update()` in `check_engine.py:283-288` ist auf SQLite ein No-op, die
Monitoring-Tests laufen komplett auf SQLite, nur `test_migrations_smoke.py` ist `DATABASE_URL`-gegattert.

## Ziel & Nicht-Ziele

**Ziel.** Ein dep-gated `run.sh`-Schritt `schemathesis` (Server, Monitoring, CA-Issuer; Beispiele: 5 im `quick`-Layer,
20 im PR-CI, 100 im Wochenlauf) mit Auth-Matrix und begründeter Ausschlussliste; Hypothesis mit **genau drei** Zielen
(FRP-TOML-Round-Trip über `tomllib`, Line-Protocol-Round-Trip über einen Test-Parser, `is_private_url` mit injiziertem
Resolver plus URL-Parser-Differential); ein Postgres-Concurrency-Test für `execute_check`, der den `with_for_update`-
Mutanten tötet; pytest-alembic mit den vier eingebauten Tests je Dienst plus einem `insert_into`-Seed je Daten-Migration.
`@example`-Pins werden committet, `.hypothesis/` ist gitignored.

**Nicht-Ziele.** Go-Fuzz, `rapid`, `proptest`, `fast-check`, Hypothesis-State-Machines (zurückgestellt, Roadmap). Kein
JUnit (Stufe 5). Kein Playwright-`live`-Projekt (Stufe 5). Kein GUI-Explorer. Keine Schemathesis-Läufe gegen einen
laufenden Stack — nur `from_asgi` in-process.

## Betroffene Komponenten & Dateien

| Bereich | Dateien |
|---|---|
| Abhängigkeiten | `apps/server/requirements-dev.txt` (+3 Pakete), `apps/monitoring/requirements-dev.txt` (neu), `apps/ca-issuer/requirements-dev.txt` (neu), `scripts/tests/run.sh` (Install-Zeilen), `.github/workflows/ci.yml` (Install-Zeilen), `.gitignore` (`.hypothesis/`) |
| Schemathesis | `apps/server/tests/test_schemathesis.py`, `apps/monitoring/tests/test_schemathesis.py`, `apps/ca-issuer/tests/test_schemathesis.py`, je `schemathesis_exclude.toml`; `scripts/tests/run.sh` (Schritt `schemathesis`, `AH_SCHEMATHESIS_EXAMPLES`), `scripts/tests/heavy.sh` (eine Env-Zeile für den Box-Lauf), `.github/workflows/ci.yml` (Env) |
| Hypothesis | `apps/server/tests/test_frp_toml_roundtrip.py` (Ziel: `app/modules/frp/config_generator.py` + `schemas.py:_reject_toml_breakers`), `apps/monitoring/tests/test_victoria_roundtrip.py` (`app/core/victoria.py:format_line/_esc_tag`), `apps/server/tests/test_ssrf_properties.py` (`app/core/ssrf.py:_resolve`, `is_private_url`) |
| Concurrency | `apps/monitoring/tests/test_check_engine_concurrency.py` (`check_engine.py:execute_check`, Postgres) |
| Alembic | `apps/server/tests/test_alembic_builtin.py` + `conftest.py` (Fixtures `alembic_config`, `alembic_engine`), `apps/monitoring/tests/test_alembic_builtin.py` + `conftest.py` |
| Doku | `DEVELOPMENT.md`, `docs/developer/cicd.html` DE+EN, `CHANGELOG.md` |

Auth-Matrix des Servers (Exploration): Admin-JWT über `POST /api/auth/login` (`admin_user`-Fixture, Passwort aus
`conftest.py`), API-Keys über `hash_api_key` direkt in die DB (`permission` read/read_write, `server_id` NULL oder gebunden),
`X-Internal-Key` gegen `MONITOR_API_KEY` (`notifications/router.py:157-169`). Monitoring: `require_agent` (Agent-Key) und
`require_internal`. CA-Issuer: App aus `build_issuer`, Header `x-client-verify`/`x-client-cert` für `/renew`.

## Datenmodell / API / Migrationen

Keine Änderung an Produktcode oder Schema. Neue Testabhängigkeiten in den Dev-Requirements (pip-compile-Lock mit
Hashes für die `requirements.txt` bleibt unberührt, Dev-Deps sind wie heute ungehasht). Der `schemathesis`-Schritt
läuft **in-process** gegen `app.openapi()` und die Test-DB (Server: Postgres via `pg_engine`/`db_session`-Override;
Monitoring: SQLite-Override; CA-Issuer: Memory-Store).

## Externe Integrationen

Verifiziert 2026-09-18 in der jeweiligen Doku: **Schemathesis 4.x** — `schemathesis.openapi.from_asgi("/openapi.json", app)`,
`@schema.parametrize()`, `schema.include(...)`/`schema.exclude(...)` (name/method/path/tag/operation_id, regex),
`case.call_and_validate(headers=…, checks=[…], excluded_checks=[…])`, Auth-Provider `@schemathesis.auth()`, Beispielzahl über
`@settings(max_examples=N)` oder `schema.config.generation.max_examples`; Checks u. a. `not_a_server_error`,
`response_schema_conformance`, `negative_data_rejection`, `positive_data_acceptance`, `ignored_auth`, `use_after_free`,
`ensure_resource_availability`, `status_code_conformance`, `content_type_conformance`, `missing_required_header`,
`unsupported_method`. **Hypothesis** — `@given`, `@settings(max_examples, deadline, suppress_health_check)`, `@example`
(läuft in der Phase `explicit`, zählt nicht zu `max_examples`), `settings.register_profile`/`load_profile` (`ci` mit
`derandomize`), Datenbank `.hypothesis/examples` (abschaltbar mit `database=None`). **pytest-alembic** — `--test-alembic`
oder `pytest_alembic` im conftest; Tests `test_single_head_revision`, `test_upgrade`, `test_model_definitions_match_ddl`,
`test_up_down_consistency`; Fixtures `alembic_config`, `alembic_engine`; `alembic_runner.migrate_up_before/insert_into/
migrate_up_one`. Zwei Alembic-Verzeichnisse ⇒ je App eigene Fixtures. `st.ip_addresses()` ist in der Doku-Übersicht
genannt, die Signatur wird beim Bau gegen die Strategie-Referenz geprüft (unverifiziert).

## Trade-offs & Alternativen

1. **`requirements-dev.txt` für alle drei Python-Dienste** statt Paketlisten in `run.sh`/`ci.yml`: eine Wahrheit je Dienst,
   dieselbe Install-Zeile überall. Trade-off: zwei neue Dateien, vier Install-Zeilen ändern sich. Empfehlung ja.
2. **Schemathesis als eigener Schritt `schemathesis`** (nicht in den pytest-Schritten versteckt): eigenes SKIP/FAIL,
   eigene Beispielzahl, unter `--strict` Pflicht. Trade-off: ein Schritt mehr in der Summary. Empfehlung ja.
3. **Beispielzahlen 5 / 20 / 100** (quick / PR-CI / Wochenlauf auf der Box) über `AH_SCHEMATHESIS_EXAMPLES`: quick bleibt
   unter einer Minute, der Wochenlauf sucht tief. `heavy.sh` setzt die Variable für den Box-Lauf (eine Zeile).
4. **Ausschlussliste mit Begründung** (`schemathesis_exclude.toml`: `operation_id`, `reason`, `until`): Erstläufe rauschen
   (500 vs. Schema); jeder Ausschluss ist ein Eintrag mit Grund, kein `--exclude`-Flag im Skript. Beim Erstlauf werden
   echte Funde als Roadmap-Zeilen triagiert, nicht ausgeschlossen (Roadmap: „Einträge in `seen.md`, Task nur mit Beweis").
5. **Round-Trip statt Regex-Invarianten** für TOML und Line-Protocol: parsen und vergleichen ist die stärkere Aussage;
   für Line-Protocol schreibt der Test einen kleinen Parser (~30 Zeilen), weil es im Produkt keinen gibt und keiner
   nötig ist (YAGNI im Produkt, nicht im Test).
6. **Concurrency-Test Postgres-gegattert** wie der Migrations-Smoke: unter `--strict` Pflicht, sobald `DATABASE_URL` gesetzt
   ist (`test_skip_is_required` in `run.sh`); läuft im PR-CI (Postgres-Service) und im `all`-Layer auf der Box.

## Risiken & Rollback

- **Erstlauf-Rauschen bei Schemathesis:** 500er, fehlende `response_model` (R-0043) — Funde werden triagiert; die Task
  wird `[?]`, wenn mehr als fünf Operationen ausgeschlossen werden müssten.
- **Laufzeit:** Hypothesis-`deadline` 200 ms je Beispiel; der Concurrency-Test braucht einen zweiten DB-Zugriff parallel
  zur Session-Fixture — eigene Engine, kein Anteil an `db_session`.
  **Beim Bau abgewichen:** alle Ziele laufen `deadline=None`. Eine Deadline macht aus einem *langsamen* Beispiel einen
  *fehlgeschlagenen* — auf einer Box mit paralleler Lane misst sie die Last, nicht den Code. Die Laufzeit wird über
  `max_examples` begrenzt, nicht über eine Zeitgrenze je Beispiel.
- **Flakiness:** Hypothesis-Fehlschläge sind reproduzierbar (Datenbank/`@example`-Pins); im CI Profil `ci` mit
  `derandomize=True`.
  **Beim Bau abgewichen:** das Profil heißt `gate` und ist **immer** aktiv, nicht nur in CI (T14). Ein Profil, das nur
  in CI derandomisiert, erzeugt genau den Fund, den lokal niemand nachstellen kann.
- **Rollback:** additiv (Tests, Dev-Deps, ein Schritt), `git revert`.

## Doku-Impact

`DEVELOPMENT.md`: Absatz „Generatoren" (Schritt, Beispielzahl, Ausschlussliste, `.hypothesis/`); `docs/developer/cicd.html`
DE+EN eine Zeile in der Gate-Tabelle aus 8a; `CHANGELOG` Added.

## Offene Fragen (Design-Gate)

1. `requirements-dev.txt` für Monitoring und CA-Issuer einführen (Trade-off 1) — Empfehlung ja.
2. Beispielzahlen 5/20/100 — Empfehlung ja; anpassbar per Env.
3. Concurrency-Test mit `testcontainers` auch lokal ohne `DATABASE_URL` (wie der Server) oder nur gegattert (wie der
   Monitoring-Smoke)? Empfehlung gegattert, weil die Dev-Box ein lokales Postgres hat und `AH_TEST_DB` gesetzt ist.

## Verify-Prinzip

Alle neuen Tests grün auf HEAD. Mutanten-Gegenproben im Wegwerf-Worktree: `_reject_toml_breakers` deaktivieren ⇒ TOML-Round-
Trip rot; Escaping-Zeile in `_esc_tag` entfernen ⇒ Line-Protocol rot; Auth-Dependency einer Route entfernen ⇒ `ignored_auth`
rot; `with_for_update()` entfernen ⇒ Concurrency rot; Schemathesis fehlt ⇒ unter `--strict` `strict-failed: schemathesis (SKIP)`.
