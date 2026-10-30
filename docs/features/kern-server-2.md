<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-server-2 — Anmelde-Routen unter MTLS_ENFORCE nur mit Zertifikat; Höchstdauer der Web-Sitzung

Roadmap: R-0900 (T1), R-0887 (T2)

## Problem / Motivation

Unter `MTLS_ENFORCE=true` (Standard) verlangt das Gateway auf `:443` ein Client-Zertifikat, und jede Datenroute
prüft den Scope (`require_scope`). Die Anmelde-Routen `POST /api/auth/login`, `/api/auth/refresh` und
`/api/auth/bootstrap` prüfen nur, ob ein vorhandenes Zertifikat zum Benutzer gehört (`require_cert_user`); fehlt
ein vom Gateway geprüftes Zertifikat, prüfen sie nichts. Der Server sollte unter `MTLS_ENFORCE` dasselbe verlangen
wie das Gateway.

R-0887: Die Abmeldung nach Inaktivität im Web-Panel ist rein clientseitig; das Refresh-Cookie bleibt bis zu 7 Tage
gültig und rotiert bei jeder Verwendung weiter. Der Server begrenzt eine Browser-Sitzung bisher nicht.

## Ziel & Nicht-Ziele

- Ziel (T2, Kevin 2026-10-30): eine serverseitige absolute Höchstdauer für Browser-Sitzungen, `WEB_SESSION_MAX_HOURS`,
  Standard 24 h, `0` = aus. Gezählt ab dem Login, unabhängig von Aktivität; danach weist der Refresh ab, und der
  Access-Token läuft spätestens zum selben Zeitpunkt ab. Desktop, CLI und Skripte bleiben unverändert.

- Ziel: Unter `MTLS_ENFORCE=true` antworten die drei Routen ohne vom Gateway geprüftes Client-Zertifikat mit `403`,
  vor jeder Prüfung von Passwort, Token oder Setup-Token; ein abgewiesener Login wird wie heute als
  `auth.login_failed` auditiert; ein abgewiesener Refresh verbraucht den Token nicht. Entscheidung Kevin 2026-10-30:
  fail-closed.
- Unverändert: `MTLS_ENFORCE=false` (permissiv, manueller Erst-Bootstrap); die Bindung an den Benutzer
  (`ERR_CERT_USER_MISMATCH`, `ERR_CERT_REVOKED`) für ein vorhandenes Zertifikat; alle Clients, die über das Gateway
  kommen (Desktop und Browser haben unter Enforce immer ein Zertifikat).
- Nicht-Ziel: `logout` (beendet nur Sitzungen) und die JWT-Routen über `get_current_user` (sie tragen
  `require_scope`).

## Betroffene Komponenten & Dateien

- `apps/server/app/core/identity.py`: kleine Prüfung „unter Enforce nur mit geprüftem Zertifikat“, neben
  `require_cert_user`.
- `apps/server/app/modules/users/auth_router.py`: `login` (im auditierten `try`), `refresh_token` (vor jeder
  Token-Prüfung), `bootstrap`.
- `apps/server/tests/test_cert_user_binding.py`: Fälle ohne Zertifikat unter Enforce.
- `scripts/tests/integration_stack_test.sh` Schritt 15b: Der Login vom Scheduler direkt an `server:8080` ist dort
  bisher ein `401`; künftig `403`, der Audit-Eintrag mit der Adresse des Schedulers bleibt.

- T2: `apps/server/app/core/config.py` (Env), `apps/server/app/core/auth.py` (Claims `web`, `auth_time`),
  `auth_router.py` (Login, Refresh, Bootstrap), neue Testdatei `tests/test_web_session_max.py`.

## Datenmodell / API / Migrationen

Keine Migration. Kein neues Schema, kein neuer Fehlercode: dieselbe `403` wie die Scope-Prüfung. OpenAPI bleibt
gleich (keine neue Abhängigkeit in der Signatur). T2: zwei neue Claims im Refresh-Token (`web`, `auth_time`), kein
neues Schema.

## Trade-offs & Alternativen

- `require_scope("access")` als Abhängigkeit: liefe vor Rate-Limit und Audit und änderte bei einem Zertifikat mit
  fremdem Scope den Fehlercode (heute `ERR_CERT_USER_MISMATCH`). Verworfen.
- Die Prüfung in `require_cert_user` selbst: träfe auch `get_current_user` und den Stream. Größerer Eingriff ohne
  Auftrag. Verworfen.

- T2, Erkennung „Browser“: am Header `Sec-Fetch-Site` beim Ausstellen (wie `_token_response`) und als Claim im Token,
  nicht am Transportweg beim Refresh: so hilft es nicht, den Cookie-Wert im Body zu schicken. Ein Alt-Token im Cookie
  ohne Claim gilt als Web-Token ab seinem `iat` (einmal bis zu 24 h Kulanz nach dem Update).
- T2, Alternative serverseitiges Idle-Limit: der Server sieht keine Bedienung (offene Tabs refreshen auch ohne).
  Verworfen.

## Risiken & Rollback

Ein Werkzeug, das unter Enforce im Compose-Netz direkt an `server:8080` anmeldet, scheitert künftig mit `403`. Im Repo
tut das nur der Stack-Test 15b (wird angepasst). T2: Web-Nutzer melden sich spätestens nach 24 h neu an.
Rollback: Revert des Task-Commits.

## Doku-Impact

`docs/developer/api-reference.html` + EN (Login, Refresh, Bootstrap: unter `MTLS_ENFORCE=true` nur mit Zertifikat;
Refresh: Höchstdauer der Web-Sitzung), `docs/admin/installation.html` + EN (`WEB_SESSION_MAX_HOURS`),
`docs/admin/benutzer.html` + EN, `changelog.d/kern-server-2.md`.

## Offene Fragen

Keine (Kevin 2026-10-30).
