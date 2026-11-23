# kern-server-13 — Authentifizierung ohne Server-Kette — Task-Ledger
Status: aktiv · Branch: feature/kern-server-13 · Review: am Ende
Spec: docs/features/kern-server-13.md (Roadmap R-0692)
Heavy: linux-full — Server-API (Authentifizierung jedes Requests, Benutzer-Liste, FRP-Erzeugung)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-0692: User.servers lazy, Listen laden gezielt  [ ]
Komponente: server · Dateien: apps/server/app/modules/users/models.py, apps/server/app/modules/users/router.py, apps/server/app/modules/frp/generate_router.py, apps/server/tests/test_auth_query_count.py, changelog.d/kern-server-13.md
Änderung: `User.servers` auf `lazy="select"`; `list_users` und die Visitor-Schleife der FRP-Erzeugung laden mit `selectinload(User.servers)`. Neuer Test (SPDX), erst rot: `/api/auth/me` eines Benutzers mit Servern, Verbindung und Tunnel fragt keine der Tabellen `servers`, `connections`, `frp_tunnels` ab; `GET /api/users` mit drei solchen Benutzern fragt `servers` genau einmal ab.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_auth_query_count.py tests/test_users.py tests/test_frp_permissions.py tests/test_frp_input_hardening.py tests/test_frp_tunnels.py tests/test_notifications.py
Doku: changelog.d/kern-server-13.md

## Entscheidungen
