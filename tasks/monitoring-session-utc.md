<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: die DB-Session läuft in UTC (R-0218) — Task-Ledger
Status: bereit · Branch: feature/monitoring-session-utc · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-10 (kleines Fund-Paket aus R-0218, Loop-Futter aus Kevins Triage 2026-10-08; Haertung ohne sichtbares Verhalten und ohne Datenmigration; Teststrategie: T2 ja, der Test laeuft im integration-Layer gegen das Berliner Cluster; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0218 (Kurz-Ledger ohne Spec)
Heavy: linux-full — `run.sh integration` auf einer Pool-VM, wie bei R-0209: Der Stack fährt Postgres mit `TZ=Europe/Berlin`, genau den Fall, den der Listener abfängt. `agent_monitoring` fährt die Engine des Monitorings im Container, `stack-pytest` den neuen Test gegen das Postgres des Stacks (T2).
DoD je Task: CLAUDE.md (Tests grün, ruff check und ruff format sauber, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-10 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus einer Zeile, die Kevin am 2026-10-08 als
Loop-Futter triagiert hat. Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der
Aufsicht. Vorab lief ein Explorer (Opus) über `apps/monitoring`, mit der Lehre aus R-0201: Schreibstellen, SQL-Leser
mit Cutoff, Altzeilen in beide Richtungen. Zeilenangaben origin/main@d4515a1e.

Befund, belegt mit Datei:Zeile:
- **Spalten:** Alle 15 Zeitspalten sind `timestamp without time zone` (`apps/monitoring/app/models.py`, nur `DateTime`,
  keine `timezone=True`).
- **Defaults:** Alle sind `server_default=utc_now_sql()`, also `timezone('UTC', now())` (`app/core/time.py:52-54`,
  Modell `models.py:39-316`). DB-seitig tragen alle Spalten das seit der Migration `d9e1f3a5b7c2` (`:33-53`).
  Unabhängig von der Session.
- **Schreibstellen** in Python setzen naive UTC über `utcnow_naive()` (`app/core/time.py:21-24`):
  - `check_engine.py:264`;
  - `routers/agent.py:87` und `:193`;
  - `alerter.py:194`;
  - die Maintenance-Grenzen rechnet `schemas.py:215-227` nach naive UTC.

  Ein aware Wert in einer naiven Spalte kommt heute nicht vor.
- **Leser mit Cutoff** bilden den Cutoff naiv in Python, ohne SQL-`now()`, `interval`, `date_trunc` oder `AT TIME
  ZONE`:
  - Cooldown `alerter.py:292-298`;
  - Retention `scheduler.py:144-149`;
  - Maintenance `maintenance.py:25-28` und `:47-69`.
- **Ausgabe** über `iso_utc` (`time.py:27-36`), unabhängig von der Session.
- **Altzeilen:** Altzeilen aus Ortszeit von vor v0.40 (`created_at`/`updated_at`, alte `sent_at`) bleiben, wie sie sind.
  Die Session schreibt nichts um, und neue Werte sind schon heute unabhängig von ihr. Die Retention löscht weder früher
  noch später, der Cooldown bleibt gleich. Keine Datenmigration nötig; R-0209 und R-0202 haben sich aus demselben Grund
  dagegen entschieden.

Damit ist R-0218 Härtung: Der Listener schützt vor künftigem Code mit einem aware Wert oder einem nackten `now()`. Ohne
ihn läuft das Monitoring als einziger Dienst im Cluster in `Europe/Berlin`.

Nicht im Umfang:
- alembic `env.py:57-62`: eigene Engine ohne Listener; keine Migration schreibt Zeitwerte, Begründung wie bei R-0209.
- `scripts/tests/run.sh` (`test_skip_is_required`): Harness-Pfad, nicht in diesem Branch.

### T1 — Monitoring-Engine: jede Verbindung setzt ihre Session auf UTC (R-0218)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/core/database.py, apps/monitoring/tests/test_db_session_utc.py, apps/monitoring/app/core/time.py, CHANGELOG.md
Evidenz: run.sh[quick] monitoring: 4 passed, 0 failed, 14 skipped · contracts: 1 ok @fdf8e8aa 2026-10-10T09:35:17+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung: Ein `connect`-Listener auf `engine` (`apps/monitoring/app/core/database.py:12-18`), dieselbe Form wie im
Server (`apps/server/app/core/database.py:23-37`, R-0209):
- `insert=True`.
- `autocommit` kurz an, `SET TIME ZONE 'UTC'`, `autocommit` zurück: außerhalb jeder Transaktion, damit ein Rollback
  es nicht zurücknimmt.
- Kein `options=-c TimeZone=UTC`, weil ein `PGTZ` in der Umgebung es überstimmt (in R-0209 gemessen). Der Kommentar
  nennt das.

`time.py`: Der Modul-Docstring (`:5-13`) und der von `utc_now_sql` (`:39-47`) nennen die Session-Zeitzone als
Fehlerquelle. Sie sagen künftig, dass die Session seit R-0218 in UTC läuft und `timezone('UTC', now())` trotzdem die
explizite Form bleibt.

Neuer Test `tests/test_db_session_utc.py` (SPDX-Kopf), nach `apps/server/tests/test_db_session_utc.py`, gegen
`app.core.database.engine`:
- **Gate** nach Monitoring-Art: `DATABASE_URL` beginnt mit `postgres` (wie `test_alembic_builtin.py:39-44`).
- **Ablauf:** `PGTZ=Europe/Berlin` per `monkeypatch.setenv`, `engine.dispose()` davor und danach.
- `SHOW TimeZone` ergibt `UTC`, auch nach einem Rollback auf derselben gepoolten Verbindung.
- Ein aware Wert 12:00Z landet in einer TEMP-Tabelle mit `timestamp`-Spalte als naive `12:00`. Das läuft in einer
  Transaktion, die zurückgerollt wird; nichts bleibt in der DB.
- Rot vor dem Fix (siehe Beweis).

Wo der Test wirklich läuft:
- Auf der Dev-Box überspringt er sich, denn `verify.sh monitoring` setzt kein `DATABASE_URL` (`run.sh:331-333`,
  bewusst). Das `Verify:` unten belegt also nur Lint und den Rest der Suite.
- Den Beweis rot/grün fährt der Bau zusätzlich von Hand gegen die eigene Test-DB: nur diese eine Datei, mit
  `DATABASE_URL` und einem eigenen `DATA_DIR`. Nie die ganze Monitoring-Suite, weil dann `test_migrations_smoke` gegen
  die falsche DB liefe.
- Die PR-CI fährt ihn gegen ihr Postgres (`ci.yml:131`, `DATABASE_URL` des Monitoring-Jobs). Die Box fährt ihn über T2.

CHANGELOG unter `[Unreleased]` → `### Changed`, eine Zeile: Härtung, kein sichtbarer Fehler.
Beweis: origin/main@d4515a1e, Probe gegen AH_TEST_DB, nur gelesen bzw. in einer TEMP-Tabelle mit Rollback, mit der
Engine des Monitorings (`from app.core.database import engine`, eigenes `DATA_DIR`). Ohne `PGTZ` und mit
`PGTZ=Europe/Berlin`: `SHOW TimeZone = Europe/Berlin; aware 12:00Z stored as 2026-10-10 14:00:00`.
Dedup-Key: ref:monitoring:database.py:session-timezone-utc
HEAD: d4515a1e
Semantik: `apps/monitoring/app/core/time.py:7-9`: „Every DateTime column in this service is tz-naive UTC (Postgres
`timestamp without time zone`). Writing or comparing a tz-aware datetime against them makes the result depend on the
container's session timezone“. Die Speicherkonvention ist naive UTC, die Session-Zeitzone des Clusters ist die Quelle
der Abweichung. Unter `docs/` beschreibt keine Stelle die Session-Zeitzone (wie bei R-0209 gesucht).
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: CHANGELOG.md (Changed); die Docstrings in `time.py`

### T2 — `stack_pytest.sh`: der neue Test läuft im integration-Layer gegen das Postgres des Stacks (R-0218)  [x]
Komponente: scripts · Dateien: scripts/tests/stack_pytest.sh, scripts/tests/stack_pytest_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @77815da5 2026-10-10T09:47:44+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung: `stack_pytest.sh` fährt heute drei Tests, die einen echten Dienst brauchen, gegen den Compose-Stack. Dort ist
ein Skip ein Fehler (`:6-15`, `:92`, Summary `:100`). Ein vierter Aufruf `stack_test monitoring-session-utc
apps/monitoring tests/test_db_session_utc.py "DATABASE_URL=$ITEST_DATABASE_URL"` kommt dazu, neben
`monitoring-migrations` (`:92`). Das Postgres des Stacks läuft mit `TZ=Europe/Berlin`. Dort zeigt der Test den echten
Fall und kann sich nicht still überspringen.
- Der Kopfkommentar (`:6`, `:27`) sagt künftig „vier“ statt „drei“.
- `stack_pytest_test.sh`:
  - Der grüne Fall erwartet künftig `stack_pytest: 4 passed, 0 failed` statt `3 passed` (`:86-87`).
  - Die Schleife über die Namen (`:88`) bekommt `monitoring-session-utc`.
  - Die Fake-Läufe dort legen die vierte XML an. Das ist eine bewusst geänderte Erwartung in einem bleibenden
    Shell-Test; der diff-scan wertet `ok`/`bad`-Zeilen nicht als Assertion, sie steht deshalb hier im Text.
- `cicd.html` DE+EN (DE `:118-122`, EN ab `:119`): Der Absatz zählt die Tests von stack-pytest auf
  und bekommt den Session-Test des Monitorings dazu.
Beweis: origin/main@d4515a1e `grep -n 'stack_test' scripts/tests/stack_pytest.sh` → drei Aufrufe (monitoring-migrations,
server-redis, ca-issuer-toctou). Der neue Test aus T1 stünde sonst nur in der PR-CI.
HEAD: d4515a1e
Semantik: `scripts/tests/stack_pytest.sh:13-15`: „In the unit layer each of them skips wherever its service is missing,
and a skip inside a passing suite reads as green. Here the service IS there, so a skip is a failure“. Der neue Test ist
genau so ein Test.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html (stack-pytest)
Abhängt von: T1
