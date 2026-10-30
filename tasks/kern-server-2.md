<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-server-2 — Task-Ledger
Status: aktiv · Branch: feature/kern-server-2 · Review: am Ende
Spec: docs/features/kern-server-2.md (Roadmap R-0900, R-0887)
Heavy: linux-full — Server-Auth hinter dem Gateway; der Stack-Test 15b (enforced) prüft den direkten Login
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben `origin/main@b61444fd`, vor dem Schreiben neu greppen. Neue Code-Strings englisch, CHANGELOG umlautfrei.
Baut erst nach dem Merge von feature/api-contracts (`auth_router.py`); T2 nach dem Merge von feature/kern-web-2
(`docs/admin/benutzer.html`). `security` bei T1 und T2.

### T1 — Login, Refresh und Bootstrap unter MTLS_ENFORCE nur mit Zertifikat (R-0900)  [ ]
Komponente: server · Dateien: apps/server/app/core/identity.py, apps/server/app/modules/users/auth_router.py, apps/server/tests/test_cert_user_binding.py, scripts/tests/integration_stack_test.sh, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-server-2.md
Änderung: Neue Prüfung in `app/core/identity.py` (neben `require_cert_user`, `:203`): unter `config.MTLS_ENFORCE` und ohne verifizierte Identität `403`. `login` ruft sie im auditierten `try` (`auth_router.py:175`), `refresh_token` vor jeder Token-Prüfung (`:232`), `bootstrap` vor dem Setup-Token (`:367`). Tests (Enforce, ohne Gateway-Header): Login `403` und `auth.login_failed`, auch bei richtigem Passwort; Refresh `403`, danach mit Zertifikat derselbe Token gültig; Bootstrap `403`, kein Benutzer; permissiv wie bisher. Stack-Test 15b erwartet `403` statt `401`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_cert_user_binding.py tests/test_auth.py
Doku: docs/developer/api-reference.html + EN · changelog.d/kern-server-2.md

### T2 — Absolute Höchstdauer einer Web-Sitzung, serverseitig (R-0887)  [ ]
Komponente: server · Dateien: apps/server/app/core/config.py, apps/server/app/core/auth.py, apps/server/app/modules/users/auth_router.py, apps/server/tests/test_web_session_max.py, docs/admin/installation.html, docs/en/admin/installation.html, docs/admin/benutzer.html, docs/en/admin/users.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-server-2.md
Änderung: `config.WEB_SESSION_MAX_HOURS` (Env, Standard `24`, `0` = aus, ungültig → 24 mit Warnung, wie `parse_web_idle_timeout` `config.py:126`). Ein Refresh-Token einer Browser-Anmeldung (Header `Sec-Fetch-Site` wie in `_token_response` `auth_router.py:121`) trägt `web: true` und `auth_time` (Zeit des Logins bzw. Bootstraps); die Rotation in `refresh_token` übernimmt beide. Ein Web-Refresh-Token, dessen `auth_time` `WEB_SESSION_MAX_HOURS` oder mehr zurückliegt, gilt nicht mehr: `401`, Cookie gelöscht, keine Rotation, nicht als Reuse gewertet. Ein über das Cookie gekommener Token ohne `web` (vor dem Update ausgestellt) gilt als Web-Token mit `auth_time = iat`. Der Access-Token einer Web-Sitzung läuft spätestens mit ihr ab. Desktop, CLI und Skripte (Body, ohne `Sec-Fetch-Site`) bleiben unverändert. Kein neues Schema, keine OpenAPI-Änderung. Neue Testdatei mit SPDX-Header: Browser-Login → Refresh innerhalb der Dauer ok und `auth_time` bleibt; nach der Dauer `401` und Cookie gelöscht; Access-Token-`exp` ≤ Sitzungsende; Desktop-Login (ohne Header) nach der Dauer weiter ok; Alt-Cookie-Token ohne Claim; `0` = aus; Parser-Fälle.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_web_session_max.py tests/test_auth.py tests/test_openapi_snapshot.py
Doku: docs/admin/installation.html + EN (Env-Tabelle) · docs/admin/benutzer.html + EN users.html · docs/developer/api-reference.html + EN (Refresh) · changelog.d/kern-server-2.md

## Entscheidungen
