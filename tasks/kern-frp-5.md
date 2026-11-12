# frps-Plugin prüft mehr Felder, FRP-Konfiguration löschen, Domains über Server — Task-Ledger
Status: aktiv · Branch: feature/kern-frp-5 · Review: pro Task
Spec: docs/features/kern-frp-5.md (Roadmap R-1304, R-1305, R-1306, R-1311, R-1318, R-1310)
Heavy: scenario --tunnel — Plugin, Agent-frpc und Desktop-Visitor über den echten frps; Kevin 2026-11-12: vor dem Merge. Server-API und Agent-Modul fährt dazu der Sammellauf linux-full
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1310: FRP-Konfiguration mit Tunneln löschen ohne 500  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/models.py, apps/server/tests/test_frp_config.py
Beweis: feature/arch-frps-identity@759a99926 (+T3-Test): DELETE /api/frp/server-config/cfg-1 mit 4 Tunneln -> 500 IntegrityError; models.py:35 unverändert gegen origin/main
Dedup-Key: bug:server:apps/server/app/modules/frp/models.py:FrpServerConfig.tunnels
Änderung: Erst der rote Test (Konfiguration mit Tunneln löschen → 204, Tunnel weg), dann `passive_deletes=True` an `FrpServerConfig.tunnels`, damit die Kaskade der DB löscht statt das ORM `frp_config_id` zu leeren.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_config.py
Doku: keine (Fehlerbehebung ohne dokumentiertes Verhalten; CHANGELOG in T7)

### T2 — R-1305, R-1306: Plugin prüft allowUsers und secretKey, frps behält den Host-Schlüssel nicht  [ ]
Komponente: agent · Dateien: apps/agent/internal/frpspolicy/policy.go, apps/agent/internal/frpspolicy/handler.go, apps/agent/internal/frpspolicy/policy_test.go, apps/agent/internal/frpspolicy/handler_test.go, apps/agent/internal/frpspolicy/testdata/policy.json, apps/agent/internal/frpspolicy/testdata/newproxy.json
Änderung: Policy-Format Version 2: je Proxy `allowUsers` (Liste) und `skHash` (SHA-256 hex oder leer); `Decide` verlangt `allow_users` als dieselbe Menge und `sk` passend zum Hash (konstantzeitig). Eine zugelassene Anmeldung beantwortet der Handler mit `unchange=false` und dem ganzen Inhalt, generisch dekodiert (Zahlen exakt), ohne `metas.ahProxyKey`. Tests: falsche/zusätzliche Benutzer, falsches `sk`, Version 1 abgelehnt, Inhalt nach dem Entfernen bis auf den Schlüssel gleich.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/frpspolicy/
Doku: → T7

### T3 — R-1305: Server schreibt Policy v2 mit Benutzerliste und Schlüssel-Hash  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/policy.py, apps/server/app/modules/users/router.py, apps/server/tests/test_frp_policy.py, apps/server/tests/test_frps_policy_live.py
Änderung: `build_policy` schreibt Version 2 und liest die Proxys aus `generate_frpc_toml` mit `get_allow_users` (dieselbe Liste wie der Agent bekommt), dazu `allowUsers` und `skHash` je Proxy. Änderungen am Server-Zugriff von Benutzern (Zuordnung, Admin-Flag, Umbenennen, Löschen) rufen `sync_policy`. Der Live-Test belegt über den echten frps: Proxy mit fremder Benutzerliste oder falschem `secretKey` abgelehnt, zugelassener Proxy im Dashboard ohne Schlüssel.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_policy.py tests/test_frps_policy_live.py
Doku: → T7
Abhängt von: T2

### T4 — R-1304: Agent nimmt den Login-Schlüssel an, Plugin kann Login prüfen  [ ]
Komponente: agent · Dateien: apps/agent/internal/frpc/servertoml.go, apps/agent/internal/frpc/servertoml_test.go, apps/agent/internal/frpspolicy/policy.go, apps/agent/internal/frpspolicy/handler.go, apps/agent/internal/frpspolicy/policy_test.go, apps/agent/internal/frpspolicy/handler_test.go
Änderung: `serverRootKeys` nimmt `metadatas.ahProxyKey` an (nur dieser Schlüssel, Wert wie die übrigen). Das Plugin beantwortet die Op `Login`: ein User der Policy nur mit passendem Schlüssel in den Login-Metadaten, Bindung der Control-Verbindung an den User (Einzelheiten privat); frps registriert die Op in diesem Release nicht (Supervisor unverändert), der Server schreibt den Schlüssel noch nicht (Kevin 2026-11-12: zwei Releases).
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/frpc/ ./internal/frpspolicy/
Doku: → T7
Abhängt von: T2

### T5 — R-1311: Domain mehrerer Server ohne gemeinsame Gruppe: API 409, Policy lässt weg  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/tunnel_router.py, apps/server/app/modules/frp/policy.py, apps/server/tests/test_frp_tunnels.py, apps/server/tests/test_frp_policy.py
Änderung: `create_tunnel`/`update_tunnel` antworten 409, wenn eine Domain des Tunnels (getrimmt, Kleinschreibung) schon ein Tunnel eines anderen Servers derselben FRP-Konfiguration trägt und nicht beide dieselbe nicht leere `loadBalancer.group` haben. `build_policy` lässt einen Proxy mit solcher Domain bei allen beteiligten Servern weg und warnt einmal je Domain.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_tunnels.py tests/test_frp_policy.py tests/test_openapi_snapshot.py
Doku: → T7
Abhängt von: T3

### T6 — R-1318: Plugin-Neustart als Warnung mit Zähler  [ ]
Komponente: server · Dateien: apps/frps/frps-supervisor.sh, apps/server/tests/test_frps_supervisor_policy.py
Änderung: Startet der Supervisor das Plugin neu, weil es nicht antwortet, schreibt er `warning:` mit der Zahl der Neustarts seit seinem Start; Test über den bestehenden Watchdog-Weg.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_supervisor_policy.py
Doku: → T7

### T7 — Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, docs/admin/betrieb.html, docs/en/admin/operations.html, docs/developer/server.html, docs/en/developer/server.html, changelog.d/kern-frp-5.md
Änderung: Tunnel-Doku: Domain nur bei einem Server oder mit gemeinsamer Gruppe (409), Policy prüft Benutzerliste und Schlüssel; Betrieb: Plugin-Neustart als Warnung; Entwickler: Policy-Format v2; neutraler CHANGELOG-Eintrag (Fixed: FRP-Konfiguration löschen; Changed: frps prüft weitere Felder, Agent-Update vor dem nächsten Release).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die genannten Dateien
Task-Review: am Ende

## Entscheidungen
- 2026-11-12 Policy-Format Version 2 ohne Lesen von Version 1: Plugin und Server kommen im selben Release, das Fenster ist fail-closed wie ohne Datei.
- 2026-11-12 Benutzerliste als Menge verglichen: frpc gibt `allowUsers` in der Reihenfolge der Datei weiter, der Generator sortiert; die Menge hält den Vergleich unabhängig davon.
