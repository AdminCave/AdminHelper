<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket skip-per-step: die Skip-Regeln von run.sh sehen die Datenbank-URL ihres Schritts (R-0342) — Task-Ledger
Status: bereit · Branch: harness/skip-per-step · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket, Triage Kevin 2026-10-13; test_db_token_store bleibt beim Teilstring wie sein Test; Review am Ende Opus; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0342 (Kurz-Ledger ohne Spec)
Heavy: none — run.sh mit run_flags_test (python3-Shim, Fixture-URLs); kein Stack-, Gateway-, PKI- oder Install-Pfad, keine echte Datenbank.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku DE+EN im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker A für den Chef (adminhelper-ac). Kevin hat die Zeile am 2026-10-13 angenommen.
Zeilenangaben origin/main@fbd1a17e; beim Bau an Symbolen orientieren.

Vorab geprüft:
- `run_py_step` (run.sh :308–323) ruft `scan_test_skips "$log"` (:322) ohne die Step-ID. `test_skip_is_required`
  (:370–381) liest deshalb run.sh's eigenes `DATABASE_URL`.
- Der Server-Schritt gibt seiner Suite `DATABASE_URL="${DATABASE_URL:-${AH_TEST_DB:-}}"` (:670). Auf der Dev-Box und
  im Builder-Profil ist `DATABASE_URL` absichtlich leer und `AH_TEST_DB` gesetzt. Ein Skip der Server-Kopien von
  `test_db_session_utc` und `test_alembic_builtin` bliebe dort unter `--strict` ein stiller test-skip. Der Kommentar
  :356–361 sagt das schon als Grenze.
- Wo die Pflicht-Tests liegen und worauf sie selbst prüfen (Quelltext gelesen):

  | Test | Suite(n) | Gate im Test |
  |---|---|---|
  | `test_migrations_smoke` | monitoring (skipif), server (kein skipif) | `DATABASE_URL` gesetzt |
  | `test_alembic_builtin` | server, monitoring | `DATABASE_URL.startswith("postgres")` |
  | `test_check_engine_concurrency` | monitoring | `DATABASE_URL.startswith("postgres")` |
  | `test_db_session_utc` | monitoring | `DATABASE_URL.startswith("postgres")` |
  | `test_db_session_utc` | server | `DATABASE_URL` gesetzt |
  | `test_db_token_store` | ca-issuer | `"postgres" in AH_TEST_DB` (Teilstring) |
  | `test_auth_token_lifecycle`, `test_stream_redis` | server | ohne URL-Bezug in dieser Zeile |

- run.sh prüft für `test_alembic_builtin`, `test_check_engine_concurrency` und `test_db_session_utc` auf `*postgres*`,
  also irgendwo in der URL. Eine URL `sqlite:///…/postgres/x.db` erfüllt das, der Test skippt dort ehrlich, und
  `--strict` meldete ein falsches `strict-failed`.
- `test_db_token_store` prüft selbst per Teilstring. Dort bleibt `*postgres*`, denn die Regel spiegelt den Test.

### T1 — Die Skip-Regeln bekommen die Step-ID und sehen die URL, die der Schritt seiner Suite gibt  [x]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/run_flags_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @fc8dbfd3 2026-10-13T16:35:46+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `run_py_step` reicht seine ID weiter: `scan_test_skips "$id" "$log"` → `test_skip_is_required "$id" "$line"`.
- `test_skip_is_required` rechnet die URL des Schritts aus:
  - `server-pytest`: `${DATABASE_URL:-${AH_TEST_DB:-}}`, derselbe Ausdruck wie im Schritt (:670); ein Kommentar
    verweist auf ihn;
  - alle anderen Schritte: `${DATABASE_URL:-}` wie heute.
  - Die Regeln für `test_migrations_smoke`, `test_alembic_builtin`, `test_check_engine_concurrency` und
    `test_db_session_utc` lesen diese URL. `test_db_token_store` (AH_TEST_DB), `test_auth_token_lifecycle` und
    `test_stream_redis` bleiben, wie sie sind.
- Der Kommentar :325–361 nennt die Regel je Schritt statt der Grenze.
- Fälle in run_flags_test, mit `DATABASE_URL=` (leer) und `AH_TEST_DB=postgresql://x@localhost/y` (Platzhalter):
  - Schritt `server pytest`, Skip von `test_db_session_utc` → rc 1, `strict-failed: …test_db_session_utc… (test-skip)`;
  - Schritt `server pytest`, Skip von `test_alembic_builtin` → rc 1, ebenso;
  - Schritt `monitoring pytest`, derselbe Skip von `test_db_session_utc` → rc 0, `1 test-skips`, kein
    `strict-failed`. Monitoring bekommt AH_TEST_DB nicht.
  - Die bestehenden Fälle bleiben unverändert.
- cicd.html DE+EN, Absatz „test-skips“ (:88–97): ein Satz, dass die Vorbedingung die URL ist, die der Schritt seiner
  Suite gibt; der Server-Schritt nimmt `DATABASE_URL`, sonst `AH_TEST_DB`.
Rot vorher: Auf main endet der erste Fall mit rc 0 und einem stillen test-skip.
Beweis: origin/main@fbd1a17e, run.sh :322 `scan_test_skips "$log"`, :378 `*test_db_session_utc*) case
"${DATABASE_URL:-}" in …`, :670 `export DATABASE_URL="${DATABASE_URL:-${AH_TEST_DB:-}}"`. Fund: Bau skip-rules,
Worker B, 2026-10-13.
Dedup-Key: ref:scripts:run.sh:skip-rules-per-step
HEAD: fbd1a17e
Semantik: docs/developer/cicd.html:92–93 „Vorbedingungen sind das, worauf der Test selbst pr&uuml;ft“ (HTML-Quelle).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html (Absatz „test-skips“)

### T2 — Die drei Postgres-Regeln prüfen den Anfang der URL wie ihre Tests  [x]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/run_flags_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d157b2d7 2026-10-13T16:57:29+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `test_alembic_builtin`, `test_check_engine_concurrency` und `test_db_session_utc`: `*postgres*` wird `postgres*`.
  Das ist das `startswith("postgres")` ihrer Tests.
- `test_db_token_store` behält `*postgres*`, weil sein Test per Teilstring prüft. Ein Kommentar sagt, warum.
- Fälle in run_flags_test, Schritt `monitoring pytest`, `DATABASE_URL="sqlite:///$WORK/postgres/x.db"`:
  - Skip von `test_db_session_utc` → rc 0, `1 test-skips`, kein `strict-failed`;
  - Skip von `test_alembic_builtin` → ebenso.
Rot vorher: Auf main endet der erste Fall mit rc 1 und `strict-failed: …test_db_session_utc… (test-skip)`.
Beweis: origin/main@fbd1a17e, run.sh :376–378 `case "${DATABASE_URL:-}" in *postgres*)`;
apps/monitoring/tests/test_db_session_utc.py :26–29 `not DB_URL.startswith("postgres")`.
Dedup-Key: ref:scripts:run.sh:skip-rules-per-step
HEAD: fbd1a17e
Semantik: wie T1.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; cicd.html nennt die drei Regeln nicht einzeln)
Abhängt von: T1
