<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Verbindungen: nur bekannte API-Felder gehen in Spalten, extra_data bleibt Beiwerk — Task-Ledger
Status: geplant · Branch: feature/connection-field-mapping · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Spec: Roadmap R-0136
Heavy: none — nur das Mapping im Modell und das Lesen von extra_data; Antwort-Schema, Routen und Clients bleiben gleich, pytest deckt Create, Update, Import und Lesen ab.
DoD je Task: CLAUDE.md (Tests grün, ruff check + ruff format sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-02 von der Aufsicht (adminhelper-ac). Zeilenangaben main@abef751a.
Befund: `Connection.from_dict` und `update_from_dict` (`apps/server/app/modules/connections/models.py:89–106`,
`:109–127`) schreiben einen Schlüssel direkt in die Spalte, wenn er ein bekanntes API-Feld ist **oder** zufällig wie
eine Spalte heißt (`snake_key in {c.key for c in cls.__table__.columns}`, `:99`, `:119`). So landen auch
`extra_data` und `created_at` aus dem Body direkt in ihren Spalten. `to_dict` (`:63–86`) mischt den Inhalt von
`extra_data` zuletzt über das Ergebnis (`result.update(extra)`, `:85`) und liest ihn mit `json.loads` ohne
Fehlerbehandlung (`:84`). Die snake_case-Sperre im Schema (`schemas.py`, `_SNAKE_SPELLINGS`, seit #65) deckt nur die
vier gemappten Felder.

### T1 — Nur bekannte API-Felder gehen in Spalten, alles andere nach extra_data  [ ]
Komponente: server · Dateien: apps/server/app/modules/connections/models.py, apps/server/tests/test_connections_storage.py, CHANGELOG.md
Änderung: In `from_dict` und `update_from_dict` geht ein Schlüssel nur dann in eine Spalte, wenn er in `_KNOWN_FIELDS`
steht (über `_CAMEL_TO_SNAKE`); die Bedingung `or snake_key in … columns` entfällt. Jeder andere Schlüssel, auch ein
Spaltenname wie `extra_data`, `created_at` oder `server_id`, wird ein Eintrag in `extra_data`. `id` bleibt beim
Update unverändert (`:117–118`). Tests (Modell-Ebene, ohne DB möglich, dazu je ein API-Fall über POST und PUT
`/api/connections`): ein Body mit `extra_data` und `created_at` setzt diese Spalten nicht, die Werte stehen als
Einträge in `extra_data`; bekannte Felder werden wie bisher gemappt; ein Import-Eintrag verhält sich gleich. Vor dem
Fix rot: `extra_data` und `created_at` aus dem Body landen in der Spalte.
Beweis: main@abef751a, ohne DB (Aufsicht 2026-10-02): `Connection.from_dict({..., "extra_data": "{\"host\": \"other.example\"}"})`
setzt die Spalte, `to_dict()["host"]` ist danach `other.example`
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_connections_storage.py tests/test_connections_authz.py tests/test_connections_import.py tests/test_connection_schemas.py
Doku: CHANGELOG (Fixed, neutral: „Verbindungen übernehmen nur bekannte Felder in ihre Spalten; alles andere bleibt Zusatzinformation“)
HEAD: abef751a
Semantik: keine Stelle in docs/ — gesucht nach „extra“ und „unbekannte Felder“ in docs/developer und docs/admin; die
Absicht steht im Modell selbst: `extra_data = Column(String, nullable=True)  # JSON for unknown extra fields`
(`models.py:57`) und `_KNOWN_FIELDS` „All known fields (API-side, camelCase)“ (`:22–23`).

### T2 — Lesen: bekannte Felder gewinnen gegen extra_data, unlesbares extra_data bricht nichts  [ ]
Komponente: server · Dateien: apps/server/app/modules/connections/models.py, apps/server/tests/test_connections_storage.py, apps/server/tests/test_connections_isolation.py
Änderung: `to_dict` mischt aus `extra_data` nur Schlüssel, die nicht schon im Ergebnis stehen (bekannte Felder
gewinnen immer, auch `serverId` und `id`), und behandelt ein nicht lesbares `extra_data` (kein JSON oder kein Objekt)
als leer, mit `logger.warning` samt Verbindungs-ID. Das betrifft Zeilen, die vor T1 geschrieben wurden. Tests: eine
Zeile mit `extra_data` `{"host": "x", "serverId": "y", "custom": 1}` liefert die echten `host`/`serverId` und
zusätzlich `custom`; eine Zeile mit `extra_data` `{not json` lässt `GET /api/connections` mit 200 antworten und die
Warnung loggen. Vor dem Fix rot: beide.
Beweis: main@abef751a, ohne DB (Aufsicht 2026-10-02): `extra_data = "{not json"` ⇒ `to_dict()` wirft `JSONDecodeError`
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_connections_storage.py tests/test_connections_isolation.py
Doku: CHANGELOG (Fixed)
HEAD: abef751a
Abhängt von: T1
