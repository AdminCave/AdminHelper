<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-server-2 — Anmelde-Routen unter MTLS_ENFORCE nur mit Zertifikat

Roadmap: R-0900

## Problem / Motivation

Unter `MTLS_ENFORCE=true` (Standard) verlangt das Gateway auf `:443` ein Client-Zertifikat, und jede Datenroute
prüft den Scope (`require_scope`). Die Anmelde-Routen `POST /api/auth/login`, `/api/auth/refresh` und
`/api/auth/bootstrap` prüfen nur, ob ein vorhandenes Zertifikat zum Benutzer gehört (`require_cert_user`); fehlt
ein vom Gateway geprüftes Zertifikat, prüfen sie nichts. Der Server sollte unter `MTLS_ENFORCE` dasselbe verlangen
wie das Gateway.

## Ziel & Nicht-Ziele

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

## Datenmodell / API / Migrationen

Keine Migration. Kein neues Schema, kein neuer Fehlercode: dieselbe `403` wie die Scope-Prüfung. OpenAPI bleibt
gleich (keine neue Abhängigkeit in der Signatur).

## Trade-offs & Alternativen

- `require_scope("access")` als Abhängigkeit: liefe vor Rate-Limit und Audit und änderte bei einem Zertifikat mit
  fremdem Scope den Fehlercode (heute `ERR_CERT_USER_MISMATCH`). Verworfen.
- Die Prüfung in `require_cert_user` selbst: träfe auch `get_current_user` und den Stream. Größerer Eingriff ohne
  Auftrag. Verworfen.

## Risiken & Rollback

Ein Werkzeug, das unter Enforce im Compose-Netz direkt an `server:8080` anmeldet, scheitert künftig mit `403`. Im Repo
tut das nur der Stack-Test 15b (wird angepasst). Rollback: Revert des Task-Commits.

## Doku-Impact

`docs/developer/api-reference.html` + EN (Login, Refresh, Bootstrap: unter `MTLS_ENFORCE=true` nur mit Zertifikat),
`changelog.d/kern-server-2.md`.

## Offene Fragen

Keine (Kevin 2026-10-30).
