<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Migrationstest des Zertifikats-Registers trennt now() von timezone('UTC', now()) — Task-Ledger
Status: aktiv · Branch: feature/cert-register-utc-test · Review: pro Task
Spec: Roadmap R-0289
Heavy: none — nur ein Server-Test, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

`Review: pro Task` statt der Kurz-Ledger-Regel `am Ende`: Das Vorhaben ist die Abnahme von Team v3 und soll den
Weg `builder` → `reviewer` → `task-close.sh` samt Urteilsprüfung einmal ganz fahren (Kevin, 2026-10-15).

### T1 — Migrationstest fährt die Register-Revision in einer Session fern von UTC  [ ]
Komponente: apps/server · Dateien: apps/server/tests/test_migrations_smoke.py
Änderung: `test_certificate_register_installs_its_time_and_goes_on_downgrade` (`tests/test_migrations_smoke.py:284`) setzt vor dem ersten Verbindungsaufbau `PGTZ` per `monkeypatch.setenv` auf eine Zone fern von UTC ohne Sommerzeit (`Pacific/Kiritimati`, UTC+14). libpq gibt jeder neuen Verbindung des Tests, auch der von Alembic, diese Session-Zeitzone mit; ein `now()`-Default läge dann 14 h neben `timezone('UTC', now())`. Eine zusätzliche Assertion belegt, dass die Prüfverbindung wirklich in dieser Zone lief, sonst prüfte der Test wieder nichts. Die Abweichungs-Assertion (`:309`, `< 300` s) bleibt unverändert.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_migrations_smoke.py
Doku: keine (nur Test)
Beweis: main@15a6175d · Kopie von HEAD per `git archive`, darin `_UTC_NOW` (`alembic/versions/3f9c2a7e5b1d_add_certificate_register.py:30`) auf `sa.text("now()")` mutiert, `PGTZ=UTC pytest -q -p no:randomly tests/test_migrations_smoke.py::test_certificate_register_installs_its_time_and_goes_on_downgrade` → dreimal `1 passed` (Mutante unentdeckt). Die CI-Postgres `postgres:17-alpine` ohne `TZ` meldet `SHOW TimeZone` = `UTC`. Gegenproben: dieselbe Mutante ohne `PGTZ` (lokale Test-DB `Europe/Berlin`) und mit `PGTZ=Pacific/Kiritimati` → `1 failed`; das Original mit `PGTZ=Pacific/Kiritimati` → `1 passed`.
Orakel: mutation-sample — nach dem Fix fällt die Mutante `now()` durch, auch wenn außen `PGTZ=UTC` gesetzt ist (der Test überschreibt es); das Original bleibt grün
Dedup-Key: ref:server:test_migrations_smoke.py:utc-now-indistinct
HEAD: 15a6175d
Semantik: docs/features/tz-aware-datetimes.md:46-47 — „**Konvention der naiven Spalten:** „naiv, aber UTC“ (`app/core/time.py:5-18`). Den Default schreibt `utc_now_sql()` = `timezone('UTC', now())`“; dazu `apps/server/app/core/time.py:41-42`: „this explicit form stays: it does not depend on the session“
