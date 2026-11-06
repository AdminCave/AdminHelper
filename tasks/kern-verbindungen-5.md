<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-verbindungen-5 — Task-Ledger
Status: geplant · Branch: feature/kern-verbindungen-5 · Review: pro Task
Spec: docs/features/kern-verbindungen-5.md (Roadmap R-1161)
Heavy: linux-full — Server-API (`POST`/`PUT /api/connections`), Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@79878e61`. Kevins Entscheidung vom 2026-11-06 in R-1161.

### T1 — Server: `trustCert` folgt der Login-Regel der Optionen (R-1161)  [ ]
Komponente: server · Dateien: apps/server/app/modules/connections/router.py, apps/server/tests/test_connections_options_authz.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-verbindungen-5.md
Änderung: `_require_login_for_options` prüft zusätzlich `trustCert`: ein API-Key, der es beim Anlegen auf `true` setzt oder beim Ändern von gespeichert `false` auf `true` wechselt, bekommt `403` mit `trustCert` im `detail`; `_require_login_to_move` behandelt eine Verbindung mit `trustCert = true` wie eine mit einer geschützten Option. Tests: Key legt mit `true` an (403), wechselt auf `true` (403), sendet `true` unverändert zurück (200), setzt `false` (200), verschiebt eine Verbindung mit `true` (403); Admin-Login setzt `true` (200). Risikopfad: `security`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_connections_options_authz.py tests/test_openapi_snapshot.py
Doku: docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-verbindungen-5.md

## Entscheidungen
