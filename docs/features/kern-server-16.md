# kern-server-16 — Engere Rechte der Datenbank-Rollen

Roadmap: R-0939 (REF; Nachlauf db-roles R-0620; Kevin 2026-11-25: faellig). R-0759 (Audit als Log-Zeile) fuhr nicht
mit: sie aendert sichtbares Verhalten und wartet auf Kevins Antwort (kern-server-17).

## Problem / Motivation

`apps/server/app/db_roles.py` (db-roles, R-0620) laesst drei Rechte weiter als noetig:
- `template1`: der Superuser nimmt `PUBLIC` CONNECT und TEMPORARY auf beiden Dienst-Datenbanken und `postgres`
  (`db_roles.py:181`), nicht auf `template1`. Jede Dienst-Rolle kann sich dort verbinden und temporaere Tabellen
  anlegen.
- `ah_scheduler` bekommt DML auf allen Tabellen von `public` (`db_roles.py:208`, dazu die Default Privileges fuer
  Tabellen, die `ah_server` spaeter anlegt), also auch auf `alembic_version`. Ein Scheduler, der die Revision
  aendert, bringt die naechste Migration durcheinander.
- `ah_ca` darf `enrollment_tokens` und `device_lines` ganz aendern (`CA_TABLE_PRIVILEGES`, `db_roles.py:42`); der
  ca-issuer setzt dort nur `used_at` (`apps/ca-issuer/app/db.py:185`) und `revoked_at`, `revoked_reason`
  (`apps/ca-issuer/app/db.py:264`). `SELECT … FOR UPDATE OF device_lines` (`db.py:311`) braucht UPDATE auf
  mindestens einer Spalte, nicht auf allen.

## Ziel & Nicht-Ziele

Ziel:
- `template1` in der Liste der Datenbanken, denen `setup` CONNECT und TEMPORARY fuer PUBLIC nimmt.
- `grant-ca` (laeuft nach jeder Migration als Eigentuemer `ah_server`) nimmt `ah_scheduler` INSERT, UPDATE und
  DELETE auf `alembic_version`, falls es die Tabelle gibt; SELECT bleibt, denn `scheduler_main` wartet auf die
  Revision.
- `ah_ca` bekommt UPDATE nur auf die Spalten, die der ca-issuer schreibt; `grant-ca` nimmt vorher die Tabellenrechte
  zurueck, in einer Transaktion, damit der ca-issuer zwischen REVOKE und GRANT nicht ohne Rechte dasteht.

Nicht-Ziele: andere Rollen, Spaltenrechte fuer INSERT oder SELECT, R-0759.

## Betroffene Komponenten & Dateien

`apps/server/app/db_roles.py`, `apps/server/tests/test_db_roles.py`, `docs/developer/index.html`,
`docs/en/developer/index.html`, `changelog.d/kern-server-16.md`.

## Datenmodell / API / Migrationen

Keine Migration und kein Schema; nur GRANT/REVOKE beim Start (`db-init`, Entrypoint des Servers).

## Externe Integrationen

PostgreSQL GRANT mit Spaltenliste und die Regel fuer `FOR UPDATE` (UPDATE auf mindestens einer Spalte):
https://www.postgresql.org/docs/current/sql-grant.html, https://www.postgresql.org/docs/current/sql-select.html
(Abschnitt „The Locking Clause“).

## Trade-offs & Alternativen

- `alembic_version` in `setup` statt in `grant-ca`: `setup` laeuft vor der ersten Migration, die die Tabelle erst
  anlegt (die Default Privileges geben `ah_scheduler` dann DML darauf). Nur `grant-ca` laeuft danach.

## Risiken & Rollback

Ein vergessener Schreibzugriff des ca-issuers scheitert an fehlenden Rechten (Enrollment kaputt). Gegenmittel: der
Test faehrt jede Schreibform des ca-issuers als `ah_ca` gegen einen echten Cluster; die PR-CI faehrt den Stack.
Rollback per Revert; der naechste Start setzt die Rechte neu.

## Doku-Impact

`docs/developer/index.html` DE+EN (Datenbank-Rollen), CHANGELOG-Fragment.

## Offene Fragen

Keine.
