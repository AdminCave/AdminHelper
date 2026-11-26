# Server: engere Rechte der Datenbank-Rollen — Task-Ledger
Status: geplant · Branch: feature/kern-server-16 · Review: am Ende
Spec: docs/features/kern-server-16.md (Roadmap R-0939)
Heavy: linux-full — Rechte der Dienst-Rollen im Stack (db-init, Server-Entrypoint, ca-issuer)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- R-0759 verschoben in kern-server-17 (2026-11-26): Audit als Log-Zeile ist sichtbares Verhalten, Frage an Kevin.

### T1 — template1, alembic_version, Spaltenrechte des ca-issuers (R-0939)  [ ]
Komponente: server · Dateien: apps/server/app/db_roles.py, apps/server/tests/test_db_roles.py, docs/developer/index.html, docs/en/developer/index.html, changelog.d/kern-server-16.md
Änderung: `setup` nimmt PUBLIC CONNECT/TEMPORARY auch auf `template1`; `grant-ca` nimmt `ah_scheduler` die Rechte auf
`alembic_version` und gibt `ah_ca` UPDATE nur auf `enrollment_tokens.used_at` und `device_lines.revoked_at`,
`revoked_reason` (REVOKE und GRANT in einer Transaktion). Tests gegen den Cluster: jede Schreibform des ca-issuers
geht, eine andere Spalte nicht; der Scheduler schreibt `alembic_version` nicht; keine Dienst-Rolle verbindet sich
mit `template1`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_db_roles.py
Doku: docs/developer/index.html, docs/en/developer/index.html, changelog.d/kern-server-16.md
