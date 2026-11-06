<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-verbindungen-4 — Task-Ledger
Status: aktiv · Branch: feature/kern-verbindungen-4 · Review: pro Task
Spec: docs/features/kern-verbindungen-4.md (Roadmap R-1140, R-1143, R-1158)
Heavy: linux-full — Server-API (neue 403-Antworten an den Verbindungs-Routen); der Sammellauf fährt den Stack
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@ddfec795`. Kevins Antworten vom 2026-11-06 in den Roadmap-Zeilen.

### T1 — Server: bestimmte Verbindungs-Optionen nur per Nutzer-Login ändern (R-1140)  [x]
Komponente: server · Dateien: apps/server/app/modules/connections/router.py, apps/server/tests/test_connections_options_authz.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @8b65622d 2026-11-06T07:32:23+01:00
Review: approve (.ah-out/review/kern-verbindungen-4/T1.verdict.json)
Änderung: `create_connection`/`update_connection` vergleichen bei einem API-Key `ssh.agentForwarding`, `ssh.forwards`, `ssh.jumpHost`, `rdp.drives`, `rdp.printers`, `rdp.gateway` (Wert) und `rdp.nla` (nur „ist false“) der gesendeten `options` (kompakte Form wie gespeichert) mit dem gespeicherten Stand (beim Anlegen: leer); weicht eines ab → `403` mit englischem `detail`, das die Felder nennt. Ein Admin-JWT darf alles. Neue Testdatei (SPDX) mit Key-/JWT-Fällen je Feld, unverändertem Zurückschreiben, `nla` true/false und `options: null`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_connections_options_authz.py tests/test_connections_options.py tests/test_connections_authz.py tests/test_openapi_snapshot.py
Doku: → T5

### T2 — Server: Sitzungsverlauf nur für Nutzer-Konten (R-1143)  [x]
Komponente: server · Dateien: apps/server/app/modules/connections/router.py, apps/server/tests/test_api_key_server_binding.py, apps/server/tests/test_connection_sessions.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @01fa13f6 2026-11-06T07:35:04+01:00
Review: approve (.ah-out/review/kern-verbindungen-4/T2.verdict.json)
Änderung: `list_connection_sessions` antwortet jedem API-Key `403`, vor dem Scope-Check (keine Unterscheidung nach Existenz). Die `_SESSIONS`-Zeilen in `test_api_key_server_binding.py` erwarten jetzt `403` (gewollte Verhaltensänderung, kein Test entfällt), dazu ein Test in `test_connection_sessions.py`, dass ein Key ohne Fix den Verlauf sah. Docstring unverändert (OpenAPI-Snapshot).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_connection_sessions.py tests/test_api_key_server_binding.py tests/test_openapi_snapshot.py
Doku: → T5
Abhängt von: T1

### T3 — Server: IPv6-Literal im Jump-Host nur im ersten Hop (R-1158)  [ ]
Komponente: server · Dateien: apps/server/app/modules/connections/schemas.py, apps/server/tests/test_connections_options.py
Änderung: `_JUMP_RE`: der erste Hop nimmt `_HOST`, jeder weitere einen Hostnamen ohne `[…]`. Tests: `[2001:db8::1],h2` gut, `h1,[2001:db8::1]` → `422`; die bestehende gute Fixture mit IPv6 im zweiten Hop auf den ersten Hop umstellen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_connections_options.py tests/test_openapi_snapshot.py
Doku: → T5

### T4 — Desktop: dieselbe Jump-Host-Regel beim Start (R-1158)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/validation.rs, apps/desktop/src-tauri/src/connection/ssh.rs
Änderung: `JUMP_RE` wie T3 (erster Hop `HOST`, weitere ohne IPv6-Literal). Tests in `validation.rs`: guter Fall mit IPv6 im ersten Hop, böser mit IPv6 im zweiten; die Fixtures in `validation.rs` und `connection/ssh.rs` mit IPv6 im zweiten Hop umstellen.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- validation -- ssh
Doku: → T5

### T5 — Hinweis am Jump-Host-Feld, Doku und CHANGELOG (R-1140, R-1143, R-1158)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/i18n/dictionaries.ts, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/admin/index.html, docs/en/admin/index.html, changelog.d/kern-verbindungen-4.md
Änderung: `editor.field.jumpHost.hint` DE/EN um „IPv6-Adresse in eckigen Klammern nur im ersten Hop“ / „an IPv6 address in brackets only in the first hop“. API-Referenz DE+EN: `403` für API-Keys bei den Optionen aus T1 und bei `GET …/sessions`, Jump-Host-Regel aus T3. Admin-Doku DE+EN: Jump-Host-Format im Reiter *Optionen*. Changelog-Fragment (ohne Umlaute) unter `### Changed`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/i18n/i18n.test.ts src/components/ConnectionEditor.options.test.ts
Doku: die genannten Dateien

## Entscheidungen
- T1: Ein API-Key darf auch `host`, `port` und `kind` nicht ändern, solange die gespeicherte Verbindung eine geschützte Option trägt (sonst wanderte die Option mit zum neuen Ziel); Folge aus Kevins Regel in R-1140, Kevin gemeldet.
