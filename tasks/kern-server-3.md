<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-server-3 — Task-Ledger
Status: bereit · Branch: feature/kern-server-3 · Review: pro Task
Spec: docs/features/kern-server-3.md (Roadmap R-0960, R-0959, R-0958, R-0990, R-0991, R-0957, R-0976)
Heavy: linux-full — Server-Auth und Proxy-Vertrauen hinter dem Gateway; der Stack-Test prüft Login und Bootstrap
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben `origin/main@725fbb4c`, vor dem Bauen neu greppen. Neue Code-Strings englisch, CHANGELOG umlautfrei.
`security` bei T1, T2 und T6. R-0979 abgelehnt (Kevin 2026-10-30).

### T1 — Namensauflösung: Fehlerpfad fail-closed (R-0960)  [x]
Komponente: server · Dateien: apps/server/app/core/middleware.py, apps/server/tests/test_ip_filter.py, changelog.d/kern-server-3.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @0afa6285 2026-10-30T11:44:57+01:00
Review: approve (.ah-out/review/kern-server-3/T1.verdict.json)
Änderung: Im `except` von `_NameResolver._run` (`middleware.py:185`) gelten die Adressen der letzten Runde nicht mehr (`_networks` leer), wie der Docstring es zusagt. Test: eine Runde mit Ausnahme nach einer erfolgreichen lässt keine Adresse mehr vertraut, die nächste erfolgreiche Runde stellt sie wieder her.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ip_filter.py tests/test_identity_source.py
Doku: changelog.d/kern-server-3.md (neutral)

### T2 — Sign-in-Routen: Refresh-Audit, Sitzungsdauer ohne Überlauf, 403-Text, Bootstrap-Kommentar (R-0990, R-0991a/b/d/e, R-0958)  [x]
Komponente: server · Dateien: apps/server/app/modules/users/auth_router.py, apps/server/app/core/auth.py, apps/server/app/core/identity.py, apps/server/tests/test_web_session_max.py, apps/server/tests/test_cert_user_binding.py, apps/server/tests/test_identity_source.py, apps/server/tests/test_stream.py, changelog.d/kern-server-3.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @fd48ade5 2026-10-30T11:51:47+01:00
Review: approve (.ah-out/review/kern-server-3/T2.verdict.json)
Änderung:
- R-0990: `refresh_token` (`auth_router.py:263`) auditiert einen ohne Zertifikat abgewiesenen Refresh als `auth.refresh_failed`, wie `login` (`:211`).
- R-0991a: `_token_pair` (`:147`) vergleicht die Restdauer in Sekunden, bevor ein `timedelta` entsteht. Damit gibt es bei riesigem `WEB_SESSION_MAX_HOURS` keinen `OverflowError` mehr.
- R-0991b: `require_cert_if_enforced` (`identity.py:206`) bekommt einen eigenen `403`-Text ohne „Scope“; die Scope-Prüfung (`:330`) behält `_NO_CERT`.
- R-0991d: `web_session_start` (`auth.py:188`) decodiert ohne zweite `exp`-Prüfung, weil der Token unmittelbar vorher geprüft ist.
- R-0991e: ein Test für `web`/`auth_time` beim Browser-Bootstrap.
- R-0958: In `bootstrap` (`auth_router.py:397`) beschreibt der Kommentar zur `409`-Antwort den Code richtig; der Vertrag bleibt `409`.
Tests: Refresh ohne Zertifikat unter Enforce → `403` und eine Audit-Zeile `auth.refresh_failed`; Browser-Login mit `WEB_SESSION_MAX_HOURS` = 10**12 → `200`; neuer Text in den Tests, die ihn prüfen; ein abgelaufener Token in `web_session_start` liefert `auth_time` statt eines Fehlers.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_web_session_max.py tests/test_cert_user_binding.py tests/test_identity_source.py tests/test_stream.py tests/test_auth.py tests/test_bootstrap.py tests/test_openapi_snapshot.py
Doku: → T5

### T3 — Server-Start: ADMIN_PASSWORD über 128 Zeichen wie zu kurzes (R-0957)  [x]
Komponente: server · Dateien: apps/server/app/main.py, apps/server/tests/test_bootstrap.py, changelog.d/kern-server-3.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @29d53b46 2026-10-30T11:58:21+01:00
Review: approve (.ah-out/review/kern-server-3/T3.verdict.json)
Beweis: Code-Lesung `apps/server/app/main.py:92` prüft nur `len(ADMIN_PASSWORD) < 8`; das Schema begrenzt auf `PASSWORD_MAX_LEN` (`users/schemas.py:16`) · Dedup-Key: bug:server:main.py:admin-password-max-len
Änderung: Ein `ADMIN_PASSWORD` länger als `PASSWORD_MAX_LEN` wird wie ein zu kurzes ignoriert: Warnung, Bootstrap-Token, kein Admin. Der Test (erst rot): 129 Zeichen → kein Benutzer, Token geschrieben; 128 Zeichen → Admin angelegt.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_bootstrap.py
Doku: changelog.d/kern-server-3.md

### T4 — Connection.to_dict: tags aus Altzeilen immer als Liste (R-0976)  [x]
Komponente: server · Dateien: apps/server/app/modules/connections/models.py, apps/server/tests/test_connections_storage.py, changelog.d/kern-server-3.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @33040f43 2026-10-30T11:58:34+01:00
Review: approve (.ah-out/review/kern-server-3/T4.verdict.json)
Beweis: Code-Lesung `apps/server/app/modules/connections/models.py:79` (`json.loads(self.tags)` ungeprüft); `from_dict` (`:118`) speichert Nicht-Listen roh · Dedup-Key: bug:server:connections/models.py:tags-non-list
Änderung: `to_dict` liest `tags` defensiv wie `_extra` (`:93`): eine JSON-Liste bleibt, alles andere (kein JSON, Objekt, Zahl, String) wird `[]` mit Warnung. Der Test (erst rot): Altzeilen mit `"a,b"`, `"{}"` und `"5"` → `tags == []`, die Liste der Verbindungen antwortet `200`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_connections_storage.py
Doku: changelog.d/kern-server-3.md

### T5 — API-Referenz: Bootstrap-Reihenfolge und Refresh-Audit (R-0991c, R-0990)  [x]
Komponente: server · Dateien: docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-server-3.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @baf6fcb6 2026-10-30T11:58:59+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Beim Bootstrap kann das Rate-Limit (`429`) vor dem `403` ohne Zertifikat kommen (`api-reference.html:77` + EN). Bei Login (`:61`) steht: Ein ohne Zertifikat abgewiesener Refresh erscheint als `auth.refresh_failed`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_openapi_snapshot.py
Doku: docs/developer/api-reference.html + EN
Task-Review: am Ende
Abhängt von: T2

### T6 — Gateway-Namen kürzer zwischenspeichern (R-0959)  [x]
Komponente: server · Dateien: apps/server/app/core/middleware.py, apps/server/app/core/identity.py, apps/server/tests/test_identity_source.py, changelog.d/kern-server-3.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @6f34fa86 2026-10-30T11:58:45+01:00
Review: approve (.ah-out/review/kern-server-3/T6.verdict.json)
Änderung: `_NameResolver` bekommt eine TTL je Instanz (Standard `_NAME_TTL`, `middleware.py:74`); die Gateway-Namen (`identity.py:64`) lösen alle 5 s neu auf (Kevin 2026-10-30). Test: die Gateway-Instanz plant ihre nächste Runde nach 5 s, die Proxy-Namen weiter nach 30 s.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_identity_source.py tests/test_ip_filter.py
Doku: changelog.d/kern-server-3.md (neutral)
Abhängt von: T1

## Entscheidungen
- 2026-10-30 Kevin: R-0959 mit kürzerer TTL für die Gateway-Namen (Empfehlung angenommen); R-0979 abgelehnt.
- 2026-10-30 T4: Der Test prüft `to_dict` am Modell (Altzeilen mit `"a,b"`, `"{}"`, `"5"`, `"\"x\""` und einer gültigen Liste). Ein eigener API-Listentest entfällt: die Liste ruft für jede Zeile nur `to_dict` auf.
- 2026-10-30 T6: Die Gateway-TTL ist eine Konstante (`_GATEWAY_TTL = 5.0`), keine Konfiguration (YAGNI).
