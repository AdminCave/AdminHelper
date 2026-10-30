<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-server-2 — Task-Ledger
Status: geplant · Branch: feature/kern-server-2 · Review: am Ende
Spec: docs/features/kern-server-2.md (Roadmap R-0900)
Heavy: linux-full — Server-Auth hinter dem Gateway; der Stack-Test 15b (enforced) prüft den direkten Login
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben `origin/main@b61444fd`, vor dem Schreiben neu greppen. Neue Code-Strings englisch, CHANGELOG umlautfrei.
Baut erst nach dem Merge von feature/api-contracts (`auth_router.py`). `security` bei T1.

### T1 — Login, Refresh und Bootstrap unter MTLS_ENFORCE nur mit Zertifikat (R-0900)  [ ]
Komponente: server · Dateien: apps/server/app/core/identity.py, apps/server/app/modules/users/auth_router.py, apps/server/tests/test_cert_user_binding.py, scripts/tests/integration_stack_test.sh, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-server-2.md
Änderung: Neue Prüfung in `app/core/identity.py` (neben `require_cert_user`, `:203`): unter `config.MTLS_ENFORCE` und ohne verifizierte Identität `403`. `login` ruft sie im auditierten `try` (`auth_router.py:175`), `refresh_token` vor jeder Token-Prüfung (`:232`), `bootstrap` vor dem Setup-Token (`:367`). Tests (Enforce, ohne Gateway-Header): Login `403` und `auth.login_failed`, auch bei richtigem Passwort; Refresh `403`, danach mit Zertifikat derselbe Token gültig; Bootstrap `403`, kein Benutzer; permissiv wie bisher. Stack-Test 15b erwartet `403` statt `401`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_cert_user_binding.py tests/test_auth.py
Doku: docs/developer/api-reference.html + EN · changelog.d/kern-server-2.md

## Entscheidungen
