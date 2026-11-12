# frps-Plugin prüft mehr Felder, FRP-Konfiguration löschen, Domains über Server — Task-Ledger
Status: bereit · Branch: feature/kern-frp-5 · Review: pro Task
Spec: docs/features/kern-frp-5.md (Roadmap R-1304, R-1305, R-1306, R-1311, R-1318, R-1310, R-1368)
Heavy: scenario --tunnel — Plugin, Agent-frpc und Desktop-Visitor über den echten frps; Kevin 2026-11-12: vor dem Merge. Server-API und Agent-Modul fährt dazu der Sammellauf linux-full
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1310: FRP-Konfiguration mit Tunneln löschen ohne 500  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/models.py, apps/server/tests/test_frp_config.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @e9abd2294 2026-11-12T09:21:24+01:00
Review: approve (.ah-out/review/kern-frp-5/T1.verdict.json)
Beweis: feature/arch-frps-identity@759a99926 (+T3-Test): DELETE /api/frp/server-config/cfg-1 mit 4 Tunneln -> 500 IntegrityError; models.py:35 unverändert gegen origin/main
Dedup-Key: bug:server:apps/server/app/modules/frp/models.py:FrpServerConfig.tunnels
Änderung: Erst der rote Test (Konfiguration mit Tunneln löschen → 204, Tunnel weg), dann `passive_deletes=True` an `FrpServerConfig.tunnels`, damit die Kaskade der DB löscht statt das ORM `frp_config_id` zu leeren.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_config.py
Doku: keine (Fehlerbehebung ohne dokumentiertes Verhalten; CHANGELOG in T7)

### T2 — R-1305, R-1306: Plugin prüft allowUsers und secretKey, frps behält den Host-Schlüssel nicht  [x]
Komponente: agent · Dateien: apps/agent/internal/frpspolicy/policy.go, apps/agent/internal/frpspolicy/handler.go, apps/agent/internal/frpspolicy/policy_test.go, apps/agent/internal/frpspolicy/handler_test.go, apps/agent/internal/frpspolicy/testdata/policy.json, apps/agent/internal/frpspolicy/testdata/newproxy.json, apps/server/app/modules/frp/policy.py, apps/server/app/modules/users/router.py, apps/server/tests/test_frp_policy.py, apps/server/tests/test_frps_policy_live.py
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @4be51a3c6 2026-11-12T09:35:31+01:00
Review: approve (.ah-out/review/kern-frp-5/T2.verdict.json)
Änderung: Policy-Format Version 2: je Proxy `allowUsers` (Liste) und `skHash` (SHA-256 hex oder leer); `Decide` verlangt `allow_users` als dieselbe Menge und `sk` passend zum Hash (konstantzeitig). Eine zugelassene Anmeldung beantwortet der Handler mit `unchange=false` und dem ganzen Inhalt, generisch dekodiert (Zahlen exakt), ohne `metas.ahProxyKey`. Tests: falsche/zusätzliche Benutzer, falsches `sk`, Version 1 abgelehnt, Inhalt nach dem Entfernen bis auf den Schlüssel gleich.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/frpspolicy/
Doku: → T7

### T3 — R-1305: Server schreibt Policy v2 mit Benutzerliste und Schlüssel-Hash  [~] (zusammengelegt mit T2: Plugin liest nur Policy v2, ein Commit ohne den Server-Teil wäre rot (Prüfer T2))
Komponente: server · Dateien: apps/server/app/modules/frp/policy.py, apps/server/app/modules/users/router.py, apps/server/tests/test_frp_policy.py, apps/server/tests/test_frps_policy_live.py
Änderung: `build_policy` schreibt Version 2 und liest die Proxys aus `generate_frpc_toml` mit `get_allow_users` (dieselbe Liste wie der Agent bekommt), dazu `allowUsers` und `skHash` je Proxy. Änderungen am Server-Zugriff von Benutzern (Zuordnung, Admin-Flag, Umbenennen, Löschen) rufen `sync_policy`. Der Live-Test belegt über den echten frps: Proxy mit fremder Benutzerliste oder falschem `secretKey` abgelehnt, zugelassener Proxy im Dashboard ohne Schlüssel.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_policy.py tests/test_frps_policy_live.py
Doku: → T7
Abhängt von: T2

### T4 — R-1304: Agent nimmt den Login-Schlüssel an, Plugin kann Login prüfen  [x]
Komponente: agent · Dateien: apps/agent/internal/frpc/servertoml.go, apps/agent/internal/frpc/servertoml_test.go, apps/agent/internal/frpspolicy/policy.go, apps/agent/internal/frpspolicy/handler.go, apps/agent/internal/frpspolicy/policy_test.go, apps/agent/internal/frpspolicy/handler_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @25b025626 2026-11-12T09:53:51+01:00
Review: approve (.ah-out/review/kern-frp-5/T4.verdict.json)
Änderung: `serverRootKeys` nimmt `metadatas.ahProxyKey` an (nur dieser Schlüssel, Wert wie die übrigen). Das Plugin beantwortet die Op `Login`: ein User der Policy nur mit passendem Schlüssel in den Login-Metadaten, Bindung der Control-Verbindung an den User (Einzelheiten privat); frps registriert die Op in diesem Release nicht (Supervisor unverändert), der Server schreibt den Schlüssel noch nicht (Kevin 2026-11-12: zwei Releases).
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/frpc/ ./internal/frpspolicy/
Doku: → T7
Abhängt von: T2

### T5 — R-1311: Domain mehrerer Server ohne gemeinsame Gruppe: API 409, Policy lässt weg  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/tunnel_router.py, apps/server/app/modules/frp/policy.py, apps/server/tests/test_frp_tunnels.py, apps/server/tests/test_frp_policy.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @891e4d8d2 2026-11-12T09:57:05+01:00
Review: approve (.ah-out/review/kern-frp-5/T5.verdict.json)
Änderung: `create_tunnel`/`update_tunnel` antworten 409, wenn eine Domain des Tunnels (getrimmt, Kleinschreibung) schon ein Tunnel eines anderen Servers derselben FRP-Konfiguration trägt und nicht beide dieselbe nicht leere `loadBalancer.group` haben. `build_policy` lässt einen Proxy mit solcher Domain bei allen beteiligten Servern weg und warnt einmal je Domain.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_tunnels.py tests/test_frp_policy.py tests/test_openapi_snapshot.py
Doku: → T7
Abhängt von: T3

### T6 — R-1318: Plugin-Neustart als Warnung mit Zähler  [x]
Komponente: server · Dateien: apps/frps/frps-supervisor.sh, apps/server/tests/test_frps_supervisor_policy.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @d961ea0a5 2026-11-12T09:39:03+01:00
Review: approve (.ah-out/review/kern-frp-5/T6.verdict.json)
Änderung: Startet der Supervisor das Plugin neu, weil es nicht antwortet, schreibt er `warning:` mit der Zahl der Neustarts seit seinem Start; Test über den bestehenden Watchdog-Weg.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_supervisor_policy.py
Doku: → T7

### T7 — Doku DE+EN und CHANGELOG  [x]
Komponente: scripts · Dateien: docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, docs/admin/betrieb.html, docs/en/admin/operations.html, docs/developer/server.html, docs/en/developer/server.html, changelog.d/kern-frp-5.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @120719e23 2026-11-12T09:59:37+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Tunnel-Doku: Domain nur bei einem Server oder mit gemeinsamer Gruppe (409), Policy prüft Benutzerliste und Schlüssel; Betrieb: Plugin-Neustart als Warnung; Entwickler: Policy-Format v2; neutraler CHANGELOG-Eintrag (Fixed: FRP-Konfiguration löschen; Changed: frps prüft weitere Felder, Agent-Update vor dem nächsten Release).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die genannten Dateien
Task-Review: am Ende

### T8 — R-1368: Domain-Prüfung erfasst alle Hostnamen eines HTTPS-Tunnels  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/policy.py, apps/server/app/modules/frp/tunnel_router.py, apps/server/tests/test_frp_policy.py, apps/server/tests/test_frp_tunnels.py, docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, docs/developer/server.html, docs/en/developer/server.html, changelog.d/kern-frp-5.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @fcf30f552 2026-11-12T10:16:38+01:00
Review: approve (.ah-out/review/kern-frp-5/T8.verdict.json)
Änderung: Die Konfliktprüfung aus T5 nimmt je Proxy alle Hostnamen, die frps ihm zuordnet (`customDomains` und `subdomain` + `subDomainHost` der FRP-Konfiguration, frp v0.72 `buildDomains`), und behandelt Platzhalter wie frps (`*.example.net` deckt jeden Namen darunter, `*` alle, vhost `getByRoute`). Zwei Server kollidieren, wenn ein Name des einen einen des anderen deckt; eine gemeinsame nicht leere Gruppe hilft nur bei genau gleichem Namen. API 409 und Policy wie T5; Tests für subdomain, subdomain gegen customDomain, Platzhalter gegen Namen und `*`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_tunnels.py tests/test_frp_policy.py tests/test_openapi_snapshot.py
Doku: die genannten Dateien (Absatz Domain-Konflikt DE+EN, CHANGELOG-Zeile)
Abhängt von: T5

### T9 — R-1368: nur HTTPS-Proxys tragen Hostnamen, Platzhalter-Test dreiteilig  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/policy.py, apps/server/tests/test_frp_policy.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @5f3cbd7db 2026-11-12T10:24:22+01:00
Review: approve (.ah-out/review/kern-frp-5/T9.verdict.json)
Änderung: Nits aus Review und Security T8: frps baut Hostnamen nur für HTTP(S)-Proxys, `_conflicts` zählt daher nur Proxys vom Typ `https` (eine `subdomain` per `extra_config` an einem STCP-Tunnel nimmt keinen HTTPS-Proxy mehr aus der Policy); Docstring von `_covers` genauer; Test „Platzhalter über gruppiertem Namen derselben Gruppe“ mit dreiteiligem Namen, wie frps ihn tatsächlich routet.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_policy.py tests/test_frp_tunnels.py
Doku: keine (Verhalten wie dokumentiert: die Doku spricht von HTTPS-Tunneln)
Abhängt von: T8

### T10 — API-Referenz: 409 bei Hostnamen-Konflikt, DELETE der FRP-Konfiguration  [x]
Komponente: scripts · Dateien: docs/developer/api-reference.html, docs/en/developer/api-reference.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @976d463ce 2026-11-12T10:26:31+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Fund der Abschlussprüfung: `POST`/`PUT /api/frp/tunnels` nennen die 409, wenn ein Hostname des Tunnels auch einem Tunnel eines anderen Servers zugeordnet ist (ohne gemeinsame Gruppe bei genau gleichem Namen); `DELETE /api/frp/server-config/{id}` löscht die Tunnel der Konfiguration mit.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die genannten Dateien
Task-Review: am Ende

## Entscheidungen
- 2026-11-12 Policy-Format Version 2 ohne Lesen von Version 1: Plugin und Server kommen im selben Release, das Fenster ist fail-closed wie ohne Datei.
- 2026-11-12 Benutzerliste als Menge verglichen: frpc gibt `allowUsers` in der Reihenfolge der Datei weiter, der Generator sortiert; die Menge hält den Vergleich unabhängig davon.
- 2026-11-12 T1: `passive_deletes="all"` statt `True`: die Route lädt die Tunnel (selectin) mit, und bei `True` leert das ORM `frp_config_id` geladener Kinder trotzdem; erst `"all"` überlässt das Löschen der Kaskade der DB.
- 2026-11-12 T3 in den Commit von T2: das Plugin liest ab T2 nur Version 2, der Server schrieb bis T3 Version 1; getrennt wäre der Stand dazwischen rot (Prüfer T2). Der Commit trägt beide Verify-Läufe, der Server-Lauf steht im Body.
- 2026-11-12 T4: Logins von Usern außerhalb der Policy (Desktop-Visitor melden sich als AdminHelper-User an) lässt das Plugin ohne Schlüssel zu, gebunden an eine run_id unter ihrem eigenen Präfix; nur Hosts der Policy brauchen ihren Schlüssel, ein leerer User wird abgelehnt (Prüfer T4).
- 2026-11-12 R-1368 (Kevin-Triage: Zusatz-Task im laufenden Zug) als T8 nach dem Abschluss von T7; R-1316 in den Folgezug kern-frp-6 (Gate-Fragen Migration/UI, Rollout mit dem Scharfschalten von R-1304).
- 2026-11-12 T9/T10 aus Abschlussprüfung (API-Referenz, wichtig) und den Nits von Prüfer und Security zu T8; Kopf zurück auf aktiv.
