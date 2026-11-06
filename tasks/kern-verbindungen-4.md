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

### T3 — Server: IPv6-Literal im Jump-Host nur im letzten Hop (R-1158)  [x]
Komponente: server · Dateien: apps/server/app/modules/connections/schemas.py, apps/server/tests/test_connections_options.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @f1bbca7a 2026-11-06T07:44:17+01:00
Review: approve (.ah-out/review/kern-verbindungen-4/T3.verdict.json)
Änderung: `_JUMP_RE`: der letzte Hop nimmt `_HOST`, jeder davor einen Hostnamen ohne `[…]`. Tests: `h1,[2001:db8::1]` gut (die bestehende Fixture), `[2001:db8::1],h2` und `h1,[2001:db8::1],h3` → `422`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_connections_options.py tests/test_openapi_snapshot.py
Doku: → T5

### T4 — Desktop: dieselbe Jump-Host-Regel beim Start (R-1158)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/validation.rs, apps/desktop/src-tauri/src/connection/ssh.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @0b50f76b 2026-11-06T07:52:16+01:00
Review: approve (.ah-out/review/kern-verbindungen-4/T4.verdict.json)
Änderung: `JUMP_RE` wie T3 (letzter Hop `HOST`, die davor ohne IPv6-Literal). Tests in `validation.rs`: guter Fall mit IPv6 im letzten Hop, böse mit IPv6 in einem früheren; die Fixture `…,[2001:db8::1],h3` in `validation.rs` umstellen, `connection/ssh.rs` bleibt gültig.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- validation -- ssh
Doku: → T5

### T5 — Hinweis am Jump-Host-Feld, Doku und CHANGELOG (R-1140, R-1143, R-1158)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/i18n/dictionaries.ts, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/admin/index.html, docs/en/admin/index.html, changelog.d/kern-verbindungen-4.md
Änderung: `editor.field.jumpHost.hint` DE/EN um „IPv6-Adresse in eckigen Klammern nur im letzten Hop“ / „an IPv6 address in brackets only in the last hop“. API-Referenz DE+EN: `403` für API-Keys bei den Optionen aus T1 und bei `GET …/sessions`, Jump-Host-Regel aus T3. Admin-Doku DE+EN: Jump-Host-Format im Reiter *Optionen*. Changelog-Fragment (ohne Umlaute) unter `### Changed`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/i18n/i18n.test.ts src/components/ConnectionEditor.options.test.ts
Doku: die genannten Dateien

## Entscheidungen
- T1: Ein API-Key darf auch `host`, `port` und `kind` nicht ändern, solange die gespeicherte Verbindung eine geschützte Option trägt (sonst wanderte die Option mit zum neuen Ziel); Folge aus Kevins Regel in R-1140, Kevin gemeldet.
- T3/T4: IPv6-Literal nur im **letzten** Hop statt im ersten. Gemessen mit OpenSSH 10.0p2: nur der letzte Hop wird von ssh selbst zerlegt, die davor gehen unverändert in den ProxyCommand; „erster Hop“ hätte genau den Fall erlaubt, den R-1158 sperren will. Kevins Absicht übernommen, Kevin gemeldet.
