<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server: Key-Bindung in allen Key-Routen, 422 des Imports und BIGINT-Grenze im Schema

Roadmap: R-0055, R-0056, R-0069 · Stand: main@8224e84c · Geplant 2026-09-30 von der Aufsicht, Entscheidungen Kevin 2026-09-30

## Problem / Motivation

- **Key-Bindung.** Ein API-Key kann an einen Server gebunden sein (`api_key.server_id`). Genau sechs Routen nehmen
  einen API-Key an (`ApiKeyOrUser`): `GET /api/connections`, `POST /api/connections/{id}/touch`, `POST` und `PUT
  /api/connections(/{id})` sowie `GET /api/frp/provision/{sid}/config` und `…/config-hash`. Suchen und FRP beachten die
  Bindung (`connections/router.py:50–51` `_scope_connections`, `frp/provision_router.py` `_require_server_scope`). Die
  Schreibpfade (`create_connection` `:99`, `update_connection` `:126`) prüfen eine gesendete `serverId` nicht gegen die
  Bindung. Kein Test deckt die Bindung über alle Key-Routen; Fuzzing kann das nicht belegen.
- **422 des Imports.** `POST /api/connections/import` antwortet bei abgelehnten Einträgen mit
  `{"detail": {"message", "rejected": [...]}}`, das Schema deklariert FastAPIs `HTTPValidationError`
  (`detail: array`). `schemathesis_exclude.toml` klammert dafür `response_schema_conformance` aus. create und update
  nutzen schon die FastAPI-Form (`_reject_unknown_server`, `:55–81`).
- **BIGINT-Grenze.** FastAPI tippt `maximum` als Float (`fastapi/openapi/models.py`); im Request-Body erscheint
  `BigIntPk` (`app/core/bounds.py:36`) deshalb als `9.223372036854776e+18`. Schemathesis liest die Grenze als
  Dezimalzahl ihres JSON-Texts und hält damit Werte bis 9223372036854776000 für gültig, 193 über der echten Grenze.
  Die Laufzeit prüft korrekt (pydantic behält den int).

## Ziel & Nicht-Ziele

Ziel:
- Ein server-gebundener Key darf in den Schreibpfaden nur `serverId` gleich seinem Server senden. Eine andere oder
  eine leere (`null`) `serverId` ergibt 403 „Kein Zugriff auf diesen Server“, geprüft vor der Existenzprüfung (wie bei
  FRP), damit keine Server-IDs aufzählbar werden. Ungebundene Keys und Benutzer bleiben unverändert.
- Eine Test-Matrix über alle Key-Routen pinnt Lesen, Schreiben und FRP je Key-Art; ein Wächter-Test verlangt, dass die
  Menge der Key-Routen gleich der Menge der Matrix-Routen ist.
- Der Import antwortet bei abgelehnten Einträgen in der FastAPI-Form (`detail` als Liste,
  `loc = ["body", "connections", <index>, …]`); der Schemathesis-Ausschluss fällt.
- Das veröffentlichte Schema trägt die exakte int-Grenze; kein `maximum`/`minimum` ≥ 2⁵³ steht als Float im Schema.

Nicht-Ziele: gebundene read_write-Keys herabstufen (Kevin 2026-09-30: der Fix reicht); das Schema für die 422 des
Imports deklarieren (macht den Pflicht-Check oasdiff rot); `POST /import` 200 typisieren (YAGNI); die Grenze auf 2⁵³−1
verengen (Produktentscheidung, oasdiff ERR).

## Betroffene Komponenten & Dateien

- Server: `apps/server/app/modules/connections/router.py`, `apps/server/app/main.py` (oder neu `app/core/openapi.py`),
  `apps/server/app/core/bounds.py` (Kommentar), `apps/server/tests/test_api_key_server_binding.py` (neu),
  `test_connections_import.py`, `test_connections_isolation.py`, `test_bounds.py`, `tests/openapi.snapshot.json`,
  `tests/schemathesis_exclude.toml`.
- Doku: `docs/developer/api-reference.html` + EN (`:85`, Import), `CHANGELOG.md`.

## Datenmodell / API / Migrationen

Keine Migration. API: 403 für gebundene Keys mit fremder oder leerer `serverId` in `POST`/`PUT /api/connections`; der
422-Body des Imports wechselt in die deklarierte Form (Schema unverändert, oasdiff grün); das Schema ändert nur die
Zahl der BIGINT-Grenze (oasdiff: keine Änderung, laut Explorer mit einem Snapshot-Prototyp gemessen).

## Externe Integrationen

FastAPI „Extending OpenAPI“ (https://fastapi.tiangolo.com/how-to/extending-openapi/, vom Explorer geprüft): `app.openapi`
überschreiben, das erzeugte Schema einmal cachen. Nicht verifiziert: ob FastAPI upstream `maximum` auf `int | float`
umstellt.

## Trade-offs & Alternativen

- 422 statt 403 für fremde `serverId`: verriete, ob ein fremder Server existiert.
- `null` still auf den eigenen Server setzen: weniger explizit, ein Client merkt seinen Fehler nicht.
- Import-422 deklarieren statt angleichen: oasdiff ERR, Ausnahme in einem Harness-Skript nötig.
- BIGINT hinnehmen: heute wirkungslos (`positive_data_acceptance` ist nicht in `CHECKS`), die Abweichung bliebe.

## Risiken & Rollback

- Externe Skripte, die `detail.rejected` des Imports lesen, müssen auf `detail[]` umstellen (im Repo liest keiner die
  Antwort; CHANGELOG „Changed“). Zwei bestehende Tests prüfen die alte Form und werden per `Test-Löschung:` ersetzt.
- Ein gebundener Key, der heute eine fremde `serverId` sendet, bekommt 403. Das ist gewollt.
- Rollback: Revert je Task.

## Doku-Impact

API-Referenz DE+EN beim Import (`:85`): Fehlerform; CHANGELOG (Security neutral, Changed, Fixed).

## Offene Fragen

Keine; entschieden am 2026-09-30 (403 vor Existenzprüfung, auch für `null`; Body angleichen; `app.openapi` überschreiben;
gebundene rw-Keys nicht herabstufen).
