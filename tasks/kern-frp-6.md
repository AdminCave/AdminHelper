<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# FRP: Tunnel-Schlüssel je Host erneuern — Task-Ledger
Status: geplant · Branch: feature/kern-frp-6 · Review: pro Task
Spec: docs/features/kern-frp-6.md (Roadmap R-1316)
Heavy: scenario --tunnel — der Schlüssel jedes Proxys und die frps-Policy ändern sich (FRP-Tunnel-Datenpfad); Server-API und Migration fährt dazu der Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1316: Schlüssel-Generation je Server (Migration, Ableitung, alle Aufrufer)  [ ]
Komponente: server · Dateien: apps/server/alembic/versions/b7c9d1e3f5a7_server_frp_key_generation.py, apps/server/app/modules/servers/models.py, apps/server/app/modules/frp/proxy_key.py, apps/server/app/modules/frp/config_generator.py, apps/server/app/modules/frp/policy.py, apps/server/app/modules/frp/provisioner.py, apps/server/app/modules/frp/provision_router.py, apps/server/app/modules/frp/generate_router.py, apps/server/app/modules/provisioning/helpers.py, apps/server/tests/test_frp_proxy_key.py, apps/server/tests/test_frp_policy.py, apps/server/tests/test_config_generator.py, apps/server/tests/test_frp_provision_sync.py, apps/server/tests/test_frp_key_generation_migration.py
Änderung: Spalte `servers.frp_key_generation` (Integer, NOT NULL, Server-Default 0; neue Revision nach `d3e5f7a9b1c3` mit SPDX-Header, Downgrade entfernt sie). `proxy_key`/`proxy_key_hash` nehmen die Generation: 0 ergibt die heutige Nachricht `frp-proxy-v1:<id>` (Test mit festem Wert gegen ein Fixture-`SECRET_KEY`), n > 0 hängt `:<n>` an. `generate_frpc_toml` bekommt die Generation als Pflicht-Keyword; jeder Aufrufer reicht die des Servers durch (Policy-Hash, Config-Hash, Provisionierungs-Bundle, Sync-Route, Einzel- und Bulk-Download). Tests: Migration up/down (bestehende Zeile trägt 0, neue Testdatei mit SPDX-Header wie `test_server_hostname_migration.py`); Generation > 0 ändert Schlüssel, Policy-Hash und Config-Hash konsistent; Generation 0 lässt beides wie heute. Mehr als acht Dateien, weil jeder Aufrufer dieselbe Signatur braucht.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_proxy_key.py tests/test_frp_policy.py tests/test_config_generator.py tests/test_frp_provision_sync.py tests/test_frp_key_generation_migration.py
Doku: → T5

### T2 — R-1316: Auslöser Provisionierung und Admin-Route `POST /api/servers/{id}/frp-key/rotate`  [ ]
Komponente: server · Dateien: apps/server/app/modules/provisioning/router.py, apps/server/app/modules/servers/router.py, apps/server/app/modules/servers/schemas.py, apps/server/tests/test_provisioning.py, apps/server/tests/test_servers_frp_key_rotate.py, apps/server/tests/openapi.snapshot.json
Änderung: `activate_provision` erhöht die Generation unter der bestehenden Zeilensperre vor dem FRP-Bundle und schreibt nach dem Commit die Policy (`sync_policy`). Neue Admin-Route erhöht die Generation unter `with_for_update`, committet, `sync_policy`, Audit `server.frp_key.rotated`, Antwort `{"generation": n}`, 404 für unbekannte Server, 403 für Nicht-Admins. Tests: Bundle der Aktivierung trägt den neuen Schlüssel, Rotation ändert Config-Hash und Policy-Hash, Audit-Eintrag, Authz; OpenAPI-Snapshot neu (neue Testdatei mit SPDX-Header).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_provisioning.py tests/test_servers_frp_key_rotate.py tests/test_openapi_snapshot.py
Doku: → T5
Abhängt von: T1

### T3 — R-1316: Desktop-Knopf „Tunnel-Schlüssel erneuern“  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/frp.ts, apps/desktop/ui/src/lib/api/frp.test.ts, apps/desktop/ui/src/components/infra/tabs/TunnelsTab.svelte, apps/desktop/ui/src/components/infra/tabs/TunnelsTab.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: `frpApi.rotateKey(session, serverId)` (POST auf die Route aus T2); im Tunnel-Reiter ein Knopf nur für Admins (`session.isAdmin`), Bestätigungsdialog mit dem Hinweis, dass der Host seine Tunnel nach dem nächsten Agent-Lauf neu anmeldet und von Hand verteilte `frpc.toml` neu zu verteilen sind; Erfolg/Fehler über die Statusleiste. Texte DE+EN. Tests: Knopf fehlt für Nicht-Admins, Abbruch ruft nichts, Bestätigen ruft die Route (neue Testdatei mit SPDX-Header).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/api/frp.test.ts src/components/infra/tabs/TunnelsTab.test.ts
Doku: → T5
Abhängt von: T2

### T4 — R-1316: Web-Knopf  [~] (Kevin 2026-11-13: nur Desktop, das Web verwaltet keine Server)
Komponente: web · Dateien: apps/web/src/pages/Frp.svelte, apps/web/src/pages/Frp.test.ts, apps/web/src/lib/api/frp.ts, apps/web/src/lib/i18n/dictionaries.ts
Änderung: auf der FRP-Seite ein Abschnitt mit Server-Auswahl (`/api/servers/summary`) und Knopf mit Bestätigung, ruft die Route aus T2; nur wenn Kevin den Web-Knopf trotz der Architektur will.
Verify: bash scripts/dev/verify.sh web --strict -- src/pages/Frp.test.ts
Doku: → T5
Abhängt von: T2

### T5 — Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/developer/server.html, docs/en/developer/server.html, changelog.d/kern-frp-6.md
Änderung: Schlüssel je Host mit Generation; Erneuern im Desktop und per Route; jede Provisionierung erneuert ihn; von Hand verteilte `frpc.toml` danach neu verteilen. Neutral formuliert (kein Angriffspfad). Fragment `### Security` bzw. `### Added`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- Kevin 2026-11-13 (Gate): Migration mit Generation 0 = heutiger Schlüssel; Auslöser Provisionierung + Admin-Aktion; API + Knopf (Web und Desktop gewählt, Web als Rückfrage T4).
- Kevin 2026-11-13: Web-Knopf entfällt (nur Desktop); Heavy scenario --tunnel vor dem Merge: ja.
