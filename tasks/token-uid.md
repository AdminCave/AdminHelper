<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server: Tokens an die Benutzer-ID binden — Task-Ledger
Status: erledigt · Branch: feature/token-uid · Review: am Ende
Spec: docs/features/token-uid.md
Heavy: linux-full — Server-Auth (Login, Refresh, alle JWT-Routen und der SSE-Stream gehen über `_get_user_from_token`); der Stack-Test meldet sich über das Gateway an. Kein `scenario` (kein Agent-, PKI- oder Install-Pfad), kein `windows`
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Tokens tragen `uid`, die Zuordnung zum Konto geht über die ID  [x]
Komponente: server · Dateien: apps/server/app/core/auth.py, apps/server/app/modules/users/auth_router.py, apps/server/tests/conftest.py, apps/server/tests/test_token_uid.py, apps/server/tests/test_auth.py, apps/server/tests/test_audit_wiring.py, apps/server/tests/test_cert_user_binding.py, apps/server/tests/test_certificate_check.py, apps/server/tests/test_cli.py, apps/server/tests/test_connections_authz.py, apps/server/tests/test_schemathesis.py, apps/server/tests/test_identity_revocation.py, apps/server/tests/test_identity_source.py, apps/server/tests/test_mtls_scope.py, apps/server/tests/test_user_token_watermark.py, docs/developer/server.html, docs/en/developer/server.html, CHANGELOG.md, apps/server/tests/token_claims.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @80ce6352 2026-10-29T05:05:49+01:00
Review: am Ende (Branch-Review)
Änderung: Ein Helfer in `auth.py` baut die Claims eines Kontos (`sub` = Name, `uid` = `users.id`); die drei Aussteller in `auth_router.py` (Login `:213`, Refresh `:255`, Bootstrap `:391`) nutzen ihn. `_get_user_from_token` (`auth.py:83`) verlangt ein ganzzahliges `uid` und sucht das Konto per ID; ohne `uid` → `None` (Kevin 2026-10-29). `username_from_token_unverified` (`auth.py:167`) bekommt ein Gegenstück für die ID, und `_refuse_reused_refresh` (`auth_router.py:134`) setzt die Marke nur am Konto dieser ID (ohne `uid` keine Marke); der Logout behält `sub` als Audit-Label. Die 43 Aufrufe von `create_access_token`/`create_refresh_token` in den elf Testdateien gehen über einen Helfer in `conftest.py`, der die ID aus der Test-DB sucht (mechanisch, darum mehr als acht Dateien). Neue Datei `tests/test_token_uid.py` (SPDX): (a) Login und Refresh liefern Tokens mit `uid` = `users.id`; (b) ein sonst gültiger Token ohne `uid` → `401` an `/api/auth/me` und an `/api/auth/refresh`; (c) Konto `bob` anlegen, Refresh-Token holen und rotieren (widerrufen), `bob` löschen, neu anlegen und anmelden; der alte widerrufene Refresh-Token erneut eingereicht → `401`, `tokens_valid_after` des neuen `bob` unverändert, seine Sitzung gilt weiter; (d) ein Token, dessen `uid` auf ein anderes Konto zeigt als `sub`, gilt für das Konto der `uid`. Zuerst rot: (a), (b), (c).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_token_uid.py tests/test_auth.py tests/test_user_token_watermark.py tests/test_stream.py tests/test_openapi_snapshot.py
Doku: docs/developer/server.html + docs/en/developer/server.html (Absatz „Token-Claims“: `uid`; Liste Rotation/Reuse-Detection: Zuordnung über die ID, Tokens ohne `uid` gelten nicht) · CHANGELOG.md (Changed, umlautfrei: Tokens nennen das Konto per ID; nach dem Update melden sich alle einmal neu an)

### T2 — Test: der iat-Zweig bleibt gedeckt  [x]
Komponente: server · Dateien: apps/server/tests/test_auth.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @8821b1ed 2026-10-29T05:57:35+01:00
Review: am Ende (Branch-Review)
Änderung: `test_token_without_iat_rejected_when_watermark_set` (`test_auth.py:168`) baut seinen Token ohne `iat` auch mit `uid` = ID des Kontos; sonst scheitert er schon am fehlenden `uid`, und der `iat`-Zweig in `_get_user_from_token` bleibt ungedeckt (reviewer, branch). `test_missing_sub_returns_none` heißt `test_missing_uid_returns_none` (der Token hat weder `sub` noch `uid`, er scheitert am `uid`). Gegenprobe: der `iat`-Zweig auf `return user` → rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_auth.py tests/test_token_uid.py
Doku: keine (nur Tests)
Abhängt von: T1

## Entscheidungen
- 2026-10-29 Kevin: Tokens ohne `uid` gelten nach dem Update nicht mehr; keine Übergangslogik.
