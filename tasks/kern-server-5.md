<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-server-5 — Task-Ledger
Status: aktiv · Branch: feature/kern-server-5 · Review: am Ende
Spec: docs/features/kern-server-5.md (Roadmap R-1000, R-1010, R-1001)
Heavy: linux-full — Server-Auth (Refresh) und FRP-Ausgabe hinter dem Gateway; der Stack-Test prüft Login und Refresh
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben `origin/main@8c4fe2f5`, vor dem Bauen neu greppen. Neue Code-Strings englisch, CHANGELOG umlautfrei.
`security` bei T1 und T2; Details zu R-1000 und R-1010 nur in `tasks/private/`.

### T1 — Refresh ohne Zertifikat zählt gegen das Rate-Limit (R-1000)  [ ]
Komponente: server · Dateien: apps/server/app/modules/users/auth_router.py, apps/server/tests/test_cert_user_binding.py, docs/admin/benutzer.html, docs/en/admin/users.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-server-5.md
Änderung: Im `except` von `refresh_token` (`auth_router.py:276`) zählt `_check_rate_limit(ip)` den abgewiesenen Refresh im Zähler des Logins, vor `audit.record`; über dem Limit antwortet er `429`. Test: sechs Refreshs ohne Zertifikat aus einer IP, der sechste `429`, höchstens fünf `auth.refresh_failed`; ein Refresh mit Zertifikat zählt nicht.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_cert_user_binding.py tests/test_auth.py
Doku: docs/admin/benutzer.html, docs/en/admin/users.html (Login-Rate-Limit), docs/developer/api-reference.html, docs/en/developer/api-reference.html (Refresh), changelog.d/kern-server-5.md (neutral)

### T2 — Namensprüfung für Altzeilen in Bulk-ZIP und CLI vervollständigen (R-1010)  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/generate_router.py, apps/server/app/cli.py, apps/server/tests/test_frp_input_hardening.py, apps/server/tests/test_cli.py, changelog.d/kern-server-5.md
Änderung: Das Bulk-ZIP (`generate_router.py:217`, `:236`) lässt Server- und Benutzernamen aus, die die API heute als Pfad-Bestandteil abweist (`servers/schemas._validate_server_name`), mit einer Warnung wie `name_refused`. `create_admin` (`cli.py:51`) prüft den Namen wie `UserCreate` (Länge, `_USERNAME_PATTERN`). Tests: Altzeile mit abgewiesenem Namen fehlt im ZIP, die übrigen bleiben; CLI weist einen solchen Namen mit Exit 1 ab und legt nichts an.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_input_hardening.py tests/test_cli.py
Doku: changelog.d/kern-server-5.md (neutral)

### T3 — Namensauflösung: Fehlerpfad unter der Runden-Sperre, Docstring zur TTL (R-1001)  [ ]
Komponente: server · Dateien: apps/server/app/core/middleware.py, apps/server/tests/test_ip_filter.py
Änderung: `_NameResolver._run` (`middleware.py:183`) leert `_networks` nach einem unerwarteten Fehler unter `self._round`, so dass eine laufende Runde außer der Reihe ihr Ergebnis behält; der Klassen-Docstring nennt die TTL je Instanz (Standard `_NAME_TTL`). Test: hält ein anderer Thread `_round`, wartet das Leeren auf ihn.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ip_filter.py tests/test_identity_source.py
Doku: keine (internes Verhalten, fail-closed bleibt)

## Entscheidungen
