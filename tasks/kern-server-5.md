<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-server-5 — Task-Ledger
Status: bereit · Branch: feature/kern-server-5 · Review: am Ende
Spec: docs/features/kern-server-5.md (Roadmap R-1000, R-1010, R-1001)
Heavy: linux-full — Server-Auth (Refresh) und FRP-Ausgabe hinter dem Gateway; der Stack-Test prüft Login und Refresh
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben `origin/main@8c4fe2f5`, vor dem Bauen neu greppen. Neue Code-Strings englisch, CHANGELOG umlautfrei.
`security` bei T1 und T2; Details zu R-1000 und R-1010 nur in `tasks/private/`.

### T1 — Refresh ohne Zertifikat zählt gegen das Rate-Limit (R-1000)  [x]
Komponente: server · Dateien: apps/server/app/modules/users/auth_router.py, apps/server/tests/test_cert_user_binding.py, docs/admin/benutzer.html, docs/en/admin/users.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-server-5.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @0155c7ab 2026-11-02T10:58:05+01:00
Review: am Ende (Branch-Review)
Änderung: Im `except` von `refresh_token` (`auth_router.py:276`) zählt `_check_rate_limit(ip)` den abgewiesenen Refresh im Zähler des Logins, vor `audit.record`; über dem Limit antwortet er `429`. Test: sechs Refreshs ohne Zertifikat aus einer IP, der sechste `429`, höchstens fünf `auth.refresh_failed`; ein Refresh mit Zertifikat zählt nicht.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_cert_user_binding.py tests/test_auth.py
Doku: docs/admin/benutzer.html, docs/en/admin/users.html (Login-Rate-Limit), docs/developer/api-reference.html, docs/en/developer/api-reference.html (Refresh), changelog.d/kern-server-5.md (neutral)

### T2 — Namensprüfung für Altzeilen in Bulk-ZIP und CLI vervollständigen (R-1010)  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/generate_router.py, apps/server/app/cli.py, apps/server/tests/test_frp_input_hardening.py, apps/server/tests/test_cli.py, changelog.d/kern-server-5.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @328e76a6 2026-11-02T11:10:47+01:00
Review: am Ende (Branch-Review)
Änderung: Das Bulk-ZIP (`generate_router.py:217`, `:236`) lässt Server- und Benutzernamen aus, die die API heute als Pfad-Bestandteil abweist (`servers/schemas._validate_server_name`), mit einer Warnung wie `name_refused`. `create_admin` (`cli.py:51`) prüft den Namen wie `UserCreate` (Länge, `_USERNAME_PATTERN`). Tests: Altzeile mit abgewiesenem Namen fehlt im ZIP, die übrigen bleiben; CLI weist einen solchen Namen mit Exit 1 ab und legt nichts an.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_input_hardening.py tests/test_cli.py
Doku: changelog.d/kern-server-5.md (neutral)

### T3 — Namensauflösung: Fehlerpfad unter der Runden-Sperre, Docstring zur TTL (R-1001)  [x]
Komponente: server · Dateien: apps/server/app/core/middleware.py, apps/server/tests/test_ip_filter.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @2ca76a0d 2026-11-02T11:12:40+01:00
Review: am Ende (Branch-Review)
Änderung: `_NameResolver._run` (`middleware.py:183`) leert `_networks` nach einem unerwarteten Fehler unter `self._round`, so dass eine laufende Runde außer der Reihe ihr Ergebnis behält; der Klassen-Docstring nennt die TTL je Instanz (Standard `_NAME_TTL`). Test: hält ein anderer Thread `_round`, wartet das Leeren auf ihn.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ip_filter.py tests/test_identity_source.py
Doku: keine (internes Verhalten, fail-closed bleibt)

### T4 — Bulk-ZIP: Doku der ausgelassenen Namen, Namen getrimmt prüfen (R-1010, Abschlussprüfung)  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/generate_router.py, apps/server/app/core/middleware.py, apps/server/tests/test_frp_input_hardening.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @7079db2a 2026-11-02T11:25:16+01:00
Review: am Ende (Branch-Review)
Beweis: reviewer branch kern-server-5 2026-11-02 — `api-reference.html:153` (DE+EN) zählt nur Namen mit TOML-Brechern als ausgelassen; `_path_refused` (`generate_router.py:41`) prüft ungetrimmt, `_validate_server_name` getrimmt
Änderung: Die API-Referenz (DE+EN) nennt beim Bulk-ZIP auch Namen, die die API heute als Pfad- bzw. Benutzernamen abweist. `_path_refused` vergleicht wie `_validate_server_name` den getrimmten Namen; Test mit `"..  "` und `" "` (erst rot). Der umbrochene Docstring in `middleware.py` hält 100 Zeichen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_input_hardening.py tests/test_ip_filter.py
Doku: docs/developer/api-reference.html, docs/en/developer/api-reference.html

## Entscheidungen
- T3: Das Leeren steht in `refresh` selbst, unter `_round` (Rumpf nach `_lookup` ausgelagert), nicht in `_run`. Unter `_run` mit eigener Sperre käme es nach einer Runde außer der Reihe noch zu spät. Der Test erzwingt diese Reihenfolge über `logger.exception` (vorher rot: `[] == [192.0.2.20/32]`).
