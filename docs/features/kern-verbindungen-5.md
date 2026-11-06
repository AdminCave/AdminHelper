<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-verbindungen-5 — `trustCert` nur per Benutzer-Login

Roadmap R-1161 (Zug `tasks/kern-verbindungen-5.md`), Folgearbeit zu `kern-verbindungen-4` (R-1140). Kevins
Entscheidung vom 2026-11-06 steht in der Roadmap-Zeile. Stand `origin/main@79878e61`.

## Problem / Motivation
- `kern-verbindungen-4` hat die Optionen, die ändern, wohin und womit der Desktop eine Sitzung aufbaut, einem
  Benutzer-Login vorbehalten (`_LOGIN_ONLY_OPTIONS`, `apps/server/app/modules/connections/router.py:83`). Das Feld
  `trustCert` der Verbindung (`schemas.py:153`, `:187`) gehört in dieselbe Gruppe: Es entscheidet, ob der Desktop das
  Zertifikat des Ziels prüft (`apps/desktop/src-tauri/src/connection/rdp.rs:313`). Ein `read_write`-API-Key darf es
  heute beim Anlegen und Ändern setzen.

## Ziel & Nicht-Ziele
Ziel:
- Ein API-Key bekommt `403`, wenn er `trustCert` beim Anlegen auf `true` setzt oder beim Ändern von `false` auf
  `true` wechselt. `true` unverändert zurückzusenden und `false` zu setzen bleibt erlaubt, wie bei `nla` nur die
  eine Richtung geprüft wird.
- Trägt eine Verbindung `trustCert = true`, darf ein Key auch `host`, `port`, `kind`, `username` und `domain`
  nicht ändern (`_require_login_to_move`, `router.py:129`), wie bei den Optionen aus R-1140.
- Die Antwort nennt das Feld wie die übrigen (`detail` mit `trustCert`).

Jede Änderung kommt mit einem Test, der ohne sie rot ist.

Nicht-Ziele:
- Der Import (nur Admin) und Admin-Logins: sie setzen `trustCert` wie bisher.
- Der Desktop: er liest `trustCert` weiter wie bisher.

## Betroffene Komponenten & Dateien
- Server: `apps/server/app/modules/connections/router.py` (`_require_login_for_options`, `_require_login_to_move`,
  Aufrufe in `create_connection` und `update_connection`); Test `apps/server/tests/test_connections_options_authz.py`.
- Doku: `docs/developer/api-reference.html` (DE+EN, `POST`/`PUT /api/connections`), `changelog.d/kern-verbindungen-5.md`.

## Datenmodell / API / Migrationen
Keine Migration, kein neues Feld. Neu ist ein `403` auf `POST`/`PUT /api/connections` für einen API-Key in den
oben genannten Fällen. Die Docstrings der Routen bleiben (OpenAPI-Snapshot).

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
- **Nur der Wechsel auf `true`** (empfohlen, Kevin 2026-11-06): ein Key kann eine Verbindung weiter lesen, ändern
  und zurückschreiben, und das Abschalten des Vertrauens macht nichts unsicherer.
- Alternative: `trustCert` für Keys ganz sperren. Das bräche Clients, die die ganze Verbindung zurückschreiben.

## Risiken & Rollback
- Ein Client, der per API-Key Verbindungen mit `trustCert = true` anlegt, bekommt `403`; er braucht einen
  Benutzer-Login. CHANGELOG nennt das.
- Rollback per Revert des Task-Commits; Daten ändern sich nicht.

## Doku-Impact
`docs/developer/api-reference.html` DE+EN (Absatz zu `POST` und `PUT /api/connections`), `changelog.d/kern-verbindungen-5.md`.

## Offene Fragen
Keine.
