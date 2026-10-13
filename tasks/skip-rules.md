<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Skip-Regeln: run.sh kennt test_db_session_utc, die Kommentare zählen richtig — Task-Ledger
Status: bereit · Branch: harness/skip-rules · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket aus R-0277, R-0278, Triage 2026-10-10 auf Kevins Delegation; cicd.html :40 DE/EN mit in T2, weil dieselbe falsche Aussage; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0277, R-0278 (Kurz-Ledger ohne Spec)
Heavy: none — eine Regel in `scripts/tests/run.sh` mit hermetischem Test und ein Kommentar in `.github/workflows/ci.yml`; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker B im Auftrag der Aufsicht (adminhelper-ac). Die Zeilen hat die Aufsicht auf Kevins Wort am
2026-10-10 angenommen. Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht.
Zeilenangaben origin/main@75ed3e09. `scripts/tests/run.sh` ist ein Harness-Pfad, `.github/workflows/ci.yml` ein
Gate-Pfad. Den PR merged Kevin oder die Aufsicht auf sein Wort.

### T1 — run.sh: ein Skip von test_db_session_utc mit Postgres-URL ist unter --strict rot (R-0277)  [x]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/run_flags_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b3ae4057 2026-10-13T08:33:14+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung:
- `test_skip_is_required` (`run.sh:362-372`) bekommt eine Regel `*test_db_session_utc*`. Ist `DATABASE_URL` ein Postgres
  (`*postgres*`), ist der Skip Pflicht-rot. Die Form ist die von `test_alembic_builtin` und
  `test_check_engine_concurrency` (`:368-369`).
- Die Regel deckt beide Tests dieses Namens:
  - Monitoring (`apps/monitoring/tests/test_db_session_utc.py:26-29`) skippt, solange `DATABASE_URL` nicht mit
    `postgres` beginnt.
  - Server (`apps/server/tests/test_db_session_utc.py:22-25`) skippt nur ohne `DATABASE_URL`. Mit einer Postgres-URL
    skippt er nie zu Recht.
- Der Kommentarblock über der Funktion (`:325-351`) nennt jede Regel mit Grund. Er bekommt einen Eintrag für
  `test_db_session_utc`: Die Session-Zeitzone ist eine Einstellung von Postgres, ein Skip bei Postgres-URL ist ein Loch.
- `:834`, „The three tests that skip wherever their Postgres or Redis is missing“: Es sind heute mehr
  (`stack_pytest.sh`). Der Satz nennt keine Zahl mehr.
- `run_flags_test.sh`, nach dem Muster `:306-310` (pytest-Attrappe mit `SHIM_SKIP`, `--step "monitoring pytest"`):
  - `DATABASE_URL=postgresql://…` und ein Skip von `tests/test_db_session_utc.py` → rc 1, die Zeile
    `strict-failed: …test_db_session_utc… (test-skip)`.
  - Mit `DATABASE_URL=sqlite:///…` ist derselbe Skip kein Fehler (rc 0, als test-skip gezählt).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; die Regeln stehen im Kommentar von `run.sh`)
Beweis: origin/main@75ed3e09:
- `git grep -n test_db_session_utc -- scripts/tests/run.sh` → kein Treffer.
- `test_skip_is_required` (`:362-372`) kennt `test_migrations_smoke`, `test_auth_token_lifecycle`, `test_stream_redis`,
  `test_db_token_store`, `test_check_engine_concurrency` und `test_alembic_builtin`.
- Die Skip-Bedingungen der beiden Tests stehen oben.
Metrik: Tests mit Postgres-Bedingung, deren Skip unter `--strict` nicht auffällt: 2 (beide `test_db_session_utc`) → 0, wo
`DATABASE_URL` selbst gesetzt ist (CI-Service, Stack). Ohne sie nimmt der Server-Schritt `AH_TEST_DB` (`run.sh:667`), das
die Regel nicht sieht; dort bleibt es für die Server-Kopie bei 1 (Review am Ende).
Orakel: mutation-sample — die neue Regel gestrichen: der neue Fall in `run_flags_test.sh` rot.
Dedup-Key: ref:scripts:run.sh:test_skip_is_required-session-utc
HEAD: 75ed3e09
Semantik: `run.sh:325-330`: „Tests that MUST NOT skip once their precondition is met. Each guards a path nothing else
covers, and a skip inside an otherwise passing suite is invisible: "N passed" quietly means "N minus this one".“

### T2 — ci.yml und cicd.html: der Postgres-Service des Monitorings dient mehr als dem Migrations-Smoke (R-0278)  [x]
Komponente: scripts · Dateien: .github/workflows/ci.yml, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped · contracts: 7 ok @7ea0ef39 2026-10-13T08:07:19+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung:
- `ci.yml:115-116` sagt zum Service `postgres` des Jobs `monitoring`: „Only consumed by tests/test_migrations_smoke.py
  (alembic upgrade head against a fresh DB); all other monitoring tests stay DB-free.“
- Heute lesen vier Tests des Monitorings `DATABASE_URL`:
  - `test_migrations_smoke.py`
  - `test_alembic_builtin.py`
  - `test_check_engine_concurrency.py`
  - `test_db_session_utc.py`
- Der Kommentar nennt künftig, wozu der Service da ist: die Tests, die ein echtes Postgres brauchen, und ihre Rolle.
  Das sind die Migrationskette, die Zeilensperre (FOR UPDATE) und die Session-Zeitzone.
- Der Kommentar nennt keine Zahl, die wieder veraltet. Nur der Kommentar ändert sich, nicht der Job.
- `docs/developer/cicd.html:40` macht dieselbe Aussage: „Monitoring-`pytest` (Postgres-Service für den
  Migrations-Smoke-Test)“. EN `:40` sagt dasselbe. Beide Seiten nennen künftig die Tests mit echtem Postgres (wie oben),
  in derselben Zeile der Tabelle.
Verify: bash scripts/dev/verify.sh scripts --strict   und   python3 scripts/dev/doc-smoke.py --paths --env --strict
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html (Zeile `ci.yml` der Tabelle)
Beweis: origin/main@75ed3e09:
- `ci.yml:115-116` wie oben zitiert.
- `git grep -ln DATABASE_URL -- apps/monitoring/tests` → die vier genannten Tests. Außerdem
  `test_service_process_checker.py`, dort nur in einem Kommentar (`:110`).
Metrik: falsche Aussagen über die Nutzer des Services im Kommentar: 1 → 0.
Dedup-Key: ref:ci:ci.yml:monitoring-postgres-comment
HEAD: 75ed3e09
Semantik: `docs/developer/cicd.html:117-131` (DE, EN `:115-129`) beschreibt die Tests mit echtem Dienst:
„Im PR-CI laufen der Migrations-Smoke, `test_db_session_utc` und `test_stream_redis` weiter gegen die Service-Container
ihrer Jobs“. Der Kommentar in `ci.yml` und die Tabellenzeile `:40` müssen dazu passen.
