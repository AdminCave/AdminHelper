<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Zeitstempel der Server-API mit UTC-Offset — Task-Ledger
Status: aktiv · Branch: feature/tz-aware-datetimes · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Freigabe: Kevin, 2026-10-06 (Design-Gate R-0064: Weg (a), Serialisierung mit „Z“ ohne Migration; to_dict-Antworten mit „Z“, Format „Z“, die str-Felder bleiben str; `last_run` im Hook-Skript-Kontext mit „Z“ und CHANGELOG-Hinweis; Monitoring als eigene Roadmap-Zeile)
Spec: docs/features/tz-aware-datetimes.md (Roadmap R-0064)
Heavy: linux-full — die API-Antworten ändern ihr Zeitformat; `run.sh integration` liest sie vom echten Stack. Ob `e2e` mitläuft, prüft der Abschluss am Diff (die Desktop-Live-E2E zeigt Provisioning- und Notification-Zeiten an).
DoD je Task: CLAUDE.md (Tests grün, ruff check + ruff format sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-06 von Worker B im Auftrag der Aufsicht (adminhelper-ac). Das Ledger plant den empfohlenen Weg (a)
der Spec: Serialisierung mit UTC-Offset `Z`, ohne Migration. Entscheidet Kevin (b) oder (c) (offene Frage 1), kommt
ein zweites Ledger dazu; die Tasks hier bleiben gültig. T6 hängt an der offenen Frage 4. Zeilenangaben main@9fece775.

### T1 — `UtcDatetime` und `iso_utc()` in `app/core/time.py`  [x]
Komponente: server · Dateien: apps/server/app/core/time.py, apps/server/tests/test_time_utc.py
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped @56043cbf 2026-10-06T08:25:51+02:00
Review: approve (sonnet)
Änderung: Ein Annotated-Typ `UtcDatetime` (Pydantic, Serialisierung im JSON-Modus) und eine Funktion `iso_utc(dt)`:
`None` bleibt `None`, ein naiver Wert gilt als UTC (die Konvention von `app/core/time.py:5-18`), ein aware Wert wird
nach UTC umgerechnet; die Ausgabe ist RFC 3339 mit `Z` (Mikrosekunden wie bei `isoformat()`). Neue Testdatei mit
SPDX-Kopf (`reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later`): naiv, aware UTC, aware
`+02:00`, Mikrosekunden, `None`, ein Modell mit `UtcDatetime` über `model_dump_json`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_time_utc.py
Doku: keine (intern)

### T2 — Typisierte Antworten: API-Keys und Hooks mit `Z`, Schemathesis-Ausschlüsse weg  [x]
Komponente: server · Dateien: apps/server/app/modules/api_keys/schemas.py, apps/server/app/modules/hooks/schemas.py, apps/server/tests/schemathesis_exclude.toml, apps/server/tests/test_api_keys.py, apps/server/tests/test_hooks.py
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped @99cbf0d5 2026-10-06T09:10:16+02:00
Review: approve (opus)
Änderung: `ApiKeyResponse.created_at` (`api_keys/schemas.py:22`) und `HookResponse.created_at/last_run/next_run`
(`hooks/schemas.py:63`, `:66`, `:67`) werden `UtcDatetime`. Die drei Ausschlüsse von `response_schema_conformance`
(`tests/schemathesis_exclude.toml:142-154`, `:170-175`) entfallen. Der OpenAPI-Snapshot bleibt unverändert
(`format: date-time` stand schon da; `test_openapi_snapshot.py` grün). Tests: `GET /api/api-keys` und die Hook-Antworten
enden auf `Z`, vor dem Fix rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_api_keys.py tests/test_hooks.py tests/test_openapi_snapshot.py
Doku: keine (T7)
Abhängt von: T1
Abweichung (Bau): Zwei der drei Ausschlüsse entfallen (`list_api_keys`, `create_api_key`). `create_hook` bleibt mit neuer
Begründung: ohne den `created_at`-Grund antwortet `_validate_create` (`hooks/router.py`) im Lauf mit 422 und einem
String in `detail`, das Schema verspricht `HTTPValidationError`. Das liegt außerhalb dieser Task und geht als
Roadmap-Kandidat an die Aufsicht.

### T3 — `to_dict` mit `Z`: FRP, Server, Ansible  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/models.py, apps/server/app/modules/servers/models.py, apps/server/app/modules/ansible/models.py, apps/server/tests/test_frp_config.py, apps/server/tests/test_servers_schemas.py, apps/server/tests/test_ansible.py
Änderung: Die `isoformat()`-Stellen in `frp/models.py:60-61`, `:130`, `servers/models.py:49` und
`ansible/models.py:32-33` werden `iso_utc(...)`. Die `str`-Felder in `frp/schemas.py` bleiben `str` (offene Frage 5).
Tests: je Modul ein Zeitstempel der Antwort endet auf `Z`, vor dem Fix rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_config.py tests/test_servers_schemas.py tests/test_ansible.py
Doku: keine (T7)
Abhängt von: T1

### T4 — `to_dict` mit `Z`: Provisioning, Enrollment, Users  [ ]
Komponente: server · Dateien: apps/server/app/modules/provisioning/models.py, apps/server/app/modules/provisioning/router.py, apps/server/app/modules/enrollment/models.py, apps/server/app/modules/users/router.py, apps/server/tests/test_provisioning.py, apps/server/tests/test_enrollment_mint.py, apps/server/tests/test_users.py
Änderung: Die `isoformat()`-Stellen in `provisioning/models.py:53-56`, `provisioning/router.py:82`,
`enrollment/models.py:60-63` und `users/router.py:33` werden `iso_utc(...)`; `users/schemas.py:77-79` bleibt `str`
(offene Frage 5). `tests/test_users.py:228` vergleicht heute mit `jsonable_encoder(user.created_at)` und erwartet dann
den Wert mit `Z`. Tests: je Modul ein Zeitstempel der Antwort endet auf `Z`, vor dem Fix rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_provisioning.py tests/test_enrollment_mint.py tests/test_users.py
Doku: keine (T7)
Abhängt von: T1

### T5 — `to_dict` mit `Z`: Audit und Notifications (`timestamptz`)  [ ]
Komponente: server · Dateien: apps/server/app/modules/audit/models.py, apps/server/app/modules/notifications/models.py, apps/server/tests/test_audit_api.py, apps/server/tests/test_notifications.py
Änderung: `audit/models.py:41` und `notifications/models.py:106`, `:115` werden `iso_utc(...)`. Diese Werte kommen
aware in der Zeitzone der Verbindung; `iso_utc` rechnet sie nach UTC um. Tests mit einer Session-Zeitzone ungleich
UTC (`SET LOCAL TIME ZONE 'Europe/Berlin'`, wie `tests/test_utc_timestamp_defaults.py:22`): die Antwort endet auf `Z`
und zeigt dieselbe Zeit, vor dem Fix `+02:00` bzw. `+01:00`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_audit_api.py tests/test_notifications.py
Doku: keine (T7)
Abhängt von: T1

### T6 — Hook-Skript-Kontext: `last_run` mit `Z`  [ ]
Komponente: server · Dateien: apps/server/app/modules/hooks/router.py, apps/server/app/modules/hooks/scheduler.py, apps/server/tests/test_hooks.py
Änderung: `last_run` im Kontext, den ein Hook-Skript bekommt (`hooks/router.py:340`, `hooks/scheduler.py:72`), wird
`iso_utc(...)`, wie `triggered_at` schon einen Offset trägt. Nur bei Ja zu offener Frage 4; sonst
`ledger.sh mark-skip` mit Verweis auf die Antwort. Test: der Kontext eines Testlaufs trägt `last_run` mit `Z`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hooks.py
Doku: CHANGELOG.md (in T7, mit dem Hinweis für Hook-Skripte)
Abhängt von: T1

### T7 — Doku: Zeitstempel in UTC mit `Z`  [ ]
Komponente: server · Dateien: docs/developer/api-reference.html, docs/en/developer/api-reference.html, CHANGELOG.md
Änderung: `api-reference.html` (DE + EN) sagt in einem Satz, dass Zeitstempel RFC 3339 in UTC mit `Z` sind. Der
CHANGELOG nennt unter Fixed die korrigierte Zeitanzeige in Web und Desktop und, bei Ja zu Frage 4, das neue Format von
`last_run` für Hook-Skripte.
Verify: bash scripts/dev/verify.sh server --strict
Doku: docs/developer/api-reference.html + docs/en/developer/api-reference.html · CHANGELOG.md
Abhängt von: T2–T6
