<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server: die DB-Session läuft in UTC (R-0209) — Task-Ledger
Status: erledigt · Branch: feature/db-session-utc · Commit-Granularität: pro Task · Review: am Ende (feature-review; app/core/database.py trägt jede DB-Verbindung des Servers ⇒ Reviewer Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-07 (kleines Fund-Paket aus der von Kevin am 2026-10-07 angenommenen Zeile R-0209; Listener nach dem SQLAlchemy-Rezept statt options, weil PGTZ die options überstimmt (gemessen); alembic und ca-issuer aus dem Umfang; Heavy linux-full, gefahren von der Aufsicht am Gate; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0209 (Kurz-Ledger ohne Spec)
Heavy: linux-full — nur `run.sh integration` auf einer Pool-VM: der Stack fährt postgres mit `TZ=Europe/Berlin`, genau den Fall, den dieser Fix abfängt, und die Unit-Suite nutzt fast durchweg die Engine aus `tests/conftest.py`, nicht die der App; erst der echte Stack fährt jeden Request über die geänderte Engine.
DoD je Task: CLAUDE.md (Tests grün, ruff check und ruff format sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-07 von Worker A für die Aufsicht (adminhelper-ac). Messungen auf AH_TEST_DB (Default-Session-TZ
Europe/Berlin), SQLAlchemy 2 + psycopg 3, nur gelesen bzw. in TEMP-Tabellen:
- `connect_args={"options": "-c TimeZone=UTC"}`, wie die Roadmap-Zeile ihn nennt, setzt die Session auf UTC — aber
  **nicht**, wenn die Umgebung `PGTZ` setzt: mit `PGTZ=Europe/Berlin` und den `options` meldet `SHOW TimeZone`
  `Europe/Berlin`. Der Weg aus der Zeile hält also nur, solange niemand `PGTZ` setzt.
- Der `connect`-Listener aus der SQLAlchemy-Doku (PostgreSQL-Dialekt, „Setting Alternate Search Paths on Connect“:
  `SET` mit kurz eingeschaltetem `autocommit`, „so that … it will not be reverted when the DBAPI connection has a
  rollback“) setzt UTC auch gegen `PGTZ=Europe/Berlin`, hält über einen Rollback und eine Pool-Wiederverwendung, und
  ein aware Wert 12:00Z landet in einer `timestamp`-Spalte als `12:00`. Ohne Listener: `Europe/Berlin`.
Wirkung (geprüft): `utc_now_sql()` liefert unabhängig von der Session naive UTC und bleibt; `timestamptz`-Defaults
(`func.now()` in audit/notifications) speichern einen Zeitpunkt, die Session ändert nichts daran; die Ausgabe geht
seit R-0064 über `iso_utc` und ist in UTC mit `Z`, unabhängig von der Session; die drei Vergleiche auf
`timestamptz`-Spalten (`audit/service.py:69`, `notifications/service.py:221`, `notifications/outbox.py:45`) nutzen
aware Zeitpunkte; keine Abfrage gruppiert nach Tag (`date_trunc`, `::date` gibt es im Server nicht). Die 12-h-Reserve
im Blacklist-Cleanup bleibt nötig: sie gilt Zeilen, die vor R-0201 in Session-Ortszeit geschrieben wurden; die Session
schreibt keine Zeile um. Sie kann frühestens gehen, wenn diese Zeilen abgelaufen sind (Refresh-Token 7 Tage) — eine
eigene Zeile später, nicht hier.
Nicht im Umfang: alembic `env.py` — keine Migration schreibt heute Zeitwerte (die Defaults wertet die App-Session beim
Insert aus), und eine künftige Datenmigration, die Altzeilen aus Ortszeit umrechnet (`col::timestamptz`), braucht die
Session-TZ des Clusters, nicht UTC; der ca-issuer (`apps/ca-issuer/app/db.py:74`) schreibt nur naive Python-Werte
(`_now_naive`) und vergleicht naiv, die Session-TZ berührt ihn nicht; das Monitoring hat eine eigene DB und Engine.

### T1 — `database.py`: jede Verbindung der Server-Engine setzt ihre Session auf UTC (R-0209)  [x]
Komponente: server · Dateien: apps/server/app/core/database.py, apps/server/tests/test_db_session_utc.py (neu, SPDX), apps/server/app/core/time.py, CHANGELOG.md
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped · contracts: 1 ok @83fbf503 2026-10-07T09:52:46+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Ein `connect`-Listener auf `engine` (`database.py:14`) nach dem Rezept der SQLAlchemy-Doku, mit
`insert=True`: `autocommit` kurz an, `SET TIME ZONE 'UTC'`, `autocommit` zurück — außerhalb jeder Transaktion, damit
ein Rollback es nicht zurücknimmt, und nach libpq, damit `PGTZ` es nicht überstimmt (Kommentar: warum kein
`options=-c TimeZone=UTC`). Neuer Test `tests/test_db_session_utc.py` (SPDX-Kopf wie die übrigen Tests) gegen die
Engine der App (`app.core.database.engine`, die in den Tests auf `DATABASE_URL` zeigt): `PGTZ=Europe/Berlin` per
`monkeypatch.setenv`, `engine.dispose()` davor und danach (frische Verbindungen lesen die Umgebung neu); dann
`SHOW TimeZone` ⇒ `UTC`, auch nach einem Rollback auf derselben gepoolten Verbindung; und ein aware Wert 12:00Z in eine
TEMP-Tabelle mit `timestamp`-Spalte ⇒ naive `12:00` (in einer Transaktion, die zurückgerollt wird — nichts bleibt in
der Test-DB). `time.py`: der Docstring von `utc_now_sql()` nennt, dass die Session seit R-0209 in UTC läuft und
`timezone('UTC', now())` trotzdem die explizite Form bleibt. CHANGELOG `[Unreleased]` → Fixed.
Rot vorher: ohne Listener meldet `SHOW TimeZone` unter `PGTZ=Europe/Berlin` `Europe/Berlin`, und 12:00Z landet als
14:00 (gemessen, siehe oben) — auch in der CI, deren DB in UTC läuft, weil der Test die Ortszeit über `PGTZ` setzt.
Beweis: main@a6e544dc · Probe auf AH_TEST_DB: `create_engine(AH_TEST_DB)` ohne Listener unter `PGTZ=Europe/Berlin` ⇒
`SHOW TimeZone` = `Europe/Berlin`; mit dem Listener ⇒ `UTC`, aware 12:00Z ⇒ `2026-10-07 12:00:00`
Dedup-Key: ref:server:db:session-timezone-utc
HEAD: a6e544dc
Semantik: `apps/server/app/core/time.py`, Docstring von `utc_now_sql()`: „A bare func.now() coerces in the session TZ,
and the stack runs the postgres container with TZ=Europe/Berlin — so server_default=func.now() stored Berlin local
time while the application writes UTC“ — die Speicherkonvention F7 ist naive UTC, die Session-TZ des Clusters ist die
Quelle der Abweichung. Unter `docs/` beschreibt keine Stelle die Session-Zeitzone (gesucht: Europe/Berlin,
Session-Zeitzone, TimeZone in docs/developer, docs/en/developer, docs/admin/installation.html, DEVELOPMENT.md).
Verify: bash scripts/dev/verify.sh server --strict
Doku: CHANGELOG.md (Fixed) · apps/server/app/core/time.py (Docstring)
