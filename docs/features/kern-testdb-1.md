<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring- und CA-Issuer-Tests auf Postgres (kern-testdb-1)

Roadmap: R-0700 (Code-Audit 2026-10-21, X-11).

## Problem

Stand origin/main:

- **Monitoring.** Der gemeinsame Fixture `client_db` (`apps/monitoring/tests/conftest.py`) baut seine Engine auf
  `sqlite://`; 41 Testdateien nutzen ihn. Dazu bauen 33 Testdateien eigene SQLite-Engines (etwa `test_alerter.py`,
  `test_check_engine.py`). Nur vier Tests laufen auf Postgres (`test_migrations_smoke`, `test_alembic_builtin`,
  `test_check_engine_concurrency`, `test_db_session_utc`), und nur, wenn `DATABASE_URL` auf ein Postgres zeigt.
- **CA-Issuer.** `DbTokenStore` und das Inventar werden auf SQLite geprüft (`tests/test_db_token_store.py`,
  `tests/test_inventory.py`, `tests/test_enroll_renew.py`, `tests/test_cli.py`); Postgres nur in einzelnen
  `pg_engine`-Tests über `AH_TEST_DB`.
- **Warum das zählt.** Gerade die Postgres-Härtungen verhalten sich auf SQLite anders oder gar nicht: `FOR UPDATE`
  ist dort ein No-op, NUL-Bytes, INTEGER-Breite und die Session-Zeitzone verhalten sich anders, und der
  Produktionscode hat SQLite-Zweige (etwa `_lock_identity` in `apps/ca-issuer/app/db.py`). Ein grüner Test sagt über
  den Produktionspfad deshalb wenig.

Der Server macht es schon richtig: seine Suite läuft auf Postgres (`DATABASE_URL`, sonst `AH_TEST_DB`, sonst
testcontainers).

## Ziel

- Monitoring- und CA-Issuer-Tests laufen auf Postgres, sobald eine Postgres-URL da ist: `DATABASE_URL` (CI) oder
  `AH_TEST_DB` (Dev-Box, je Worktree eine eigene DB). SQLite bleibt nur der Rückfall ohne beides.
- **Eigene Datenbank je Dienst.** Der Fixture leitet aus der URL eine eigene Datenbank ab (`<db>_mon_unit` bzw.
  `<db>_ca_unit`), legt sie an, wenn sie fehlt, und baut das Schema einmal je Lauf über `metadata.create_all`. Er
  teilt sich die Datenbank weder mit dem Server noch mit den Migrations-Tests, die `DATABASE_URL` selbst nutzen.
- **Isolation je Test:** Nach jedem Test leert ein `TRUNCATE … RESTART IDENTITY CASCADE` alle Tabellen. Ein
  Rollback reicht nicht, weil Hintergrund-Dispatch und `SessionLocal` eigene Transaktionen committen.
- Jeder Test, der heute eine eigene SQLite-Engine baut, nimmt den gemeinsamen Fixture.

## Nicht-Ziele

- Die SQLite-Zweige im Produktionscode entfernen (eigene Zeile, wenn die Suite sie nicht mehr braucht).
- `test_schemathesis.py`: Seine Datenbank setzt `run.sh` je Lauf, ein Harness-Pfad.
- `scripts/tests/run.sh` und `.github/workflows/ci.yml` ändern. CI stellt beiden Jobs schon ein Postgres
  (`DATABASE_URL` im Monitoring-Job, `AH_TEST_DB` im CA-Issuer-Job). Der jetzt veraltete Kommentar im
  Monitoring-Job („The rest of the monitoring suite runs on SQLite“) wird eine zurückgestellte Harness-Zeile.

## Betroffene Komponenten und Dateien

- **monitoring:** `apps/monitoring/tests/conftest.py` (Fixture `db_engine`, `client_db` darauf) und die Testdateien
  mit eigener SQLite-Engine (Liste in den Tasks).
- **ca-issuer:** `apps/ca-issuer/tests/conftest.py` (Fixture `db_engine`) und die vier Testdateien oben.
- **Doku:** `DEVELOPMENT.md` (Abschnitt „Postgres-gegattert“ und die lokalen Python-Tests).

## Datenmodell, API, Migrationen

Keine. Nur Tests.

## Trade-offs

- **`TRUNCATE` je Test statt Datenbank je Test.** Eine Datenbank je Test kostet je Test ein `CREATE DATABASE` und
  `create_all` (Sekunden). Ein Rollback um jeden Test scheitert an den Commits aus eigenen Sessions. `TRUNCATE`
  über alle Tabellen kostet einige Millisekunden.
- **Abgeleitete Datenbank statt `DATABASE_URL` direkt.** Die Migrations-Tests fahren `alembic` gegen
  `DATABASE_URL`; ein `create_all` dort bräche ihre Kette. Auf der Dev-Box zeigt `AH_TEST_DB` auf die Server-DB des
  Worktrees, ein `create_all` des Monitorings dort mischte zwei Schemata.
- **Rückfall SQLite.** Ohne Postgres-URL laufen die Tests weiter, nur nicht gegen Postgres. Das hält Läufe ohne
  Datenbank (Box ohne Postgres) lauffähig.

## Risiken und Rollback

- **Echte Funde.** Ein Test, der auf Postgres rot wird, zeigt entweder eine SQLite-Annahme im Test oder einen
  Fehler im Produktionscode. Eine Test-Annahme passt die Task an. Ein Produktfehler wird eine eigene BUG-Zeile; die
  Datei behält bis dahin ihre SQLite-Engine, die Task nennt das in `## Entscheidungen`.
- **Laufzeit.** Die Monitoring-Suite wird langsamer (Netz statt Speicher, `TRUNCATE` je Test). Der Monitoring-Job hat
  15 Minuten; die Task misst die Laufzeit vorher und nachher.
- **Rechte.** Der Fixture braucht `CREATEDB` für die abgeleitete Datenbank. CI läuft als Superuser; auf der Dev-Box
  legt `worktree-setup.sh` mit derselben Rolle schon Datenbanken an.
- **Rollback:** Revert des Merge-Commits.

## Doku-Impact

`DEVELOPMENT.md`: welche Suite auf welcher Datenbank läuft und woher die URL kommt. Kein CHANGELOG (nur Tests).

## Offene Fragen

Keine aus Kevins Bereich: keine API, kein Verhalten, keine Migration.
