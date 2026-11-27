# Gateway: Webhook-Trigger auf :8444, Upstream-Keepalive — Task-Ledger
Status: aktiv · Branch: feature/kern-gateway-2 · Review: pro Task
Spec: docs/features/kern-gateway-2.md (Roadmap R-1687, R-1717)
Heavy: linux-full — Gateway-Konfiguration und Server-API; der Stack-Test unter enforce läuft im PR (integration-stack)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- Kevin 2026-11-27 (Notiz R-1687): Webhook-Route auf :8444 ohne mTLS, mit Token und Ratelimit.
- Kevin 2026-11-27: Port im Dialog aus `trigger_port` der Token-Antworten (additives API-Feld), nicht fest 8444.

### T1 — Gateway: Connection "" an jedem Weg zum Upstream (R-1717)  [~] (Befund widerlegt: nginx sendet seit 1.29.7 keinen Connection-Header mehr, Upstream-Keepalive ist Default (nginx.org CHANGES 1.29.7); das Gateway-Image ist 1.30.6. Gegenprobe 2026-11-27 auf dem alten Stand: ein Upstream-Stub sah auf 443 und 8444 (location /, /ca/trust, /enroll, provision/activate) keinen Connection-Header)
Komponente: server · Dateien: apps/gateway/identity-headers.conf, apps/gateway/nginx.conf, apps/server/tests/test_gateway_container.py
Änderung: `proxy_set_header Connection ""` in `identity-headers.conf` und im :8444-Server samt `activate`-Location. Test aus
nginx.conf: jede Location mit `proxy_pass` auf `app`/`issuer` erbt oder setzt den leeren Connection-Header; im Container:
ein Stub-Upstream unter dem Namen `server` meldet für Anfragen über :443 und :8444 kein `Connection: close`.
Beweis: Code-Lesung main@6895f8eaf nginx.conf:50-60,114,187-188; der Container-Test ist vor dem Fix rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_gateway_container.py
Doku: keine (internes Verhalten ohne Doku-Stelle)

### T2 — Gateway: Webhook-Trigger auf :8444 (R-1687)  [x]
Komponente: server · Dateien: apps/gateway/nginx.conf, apps/server/tests/test_gateway_container.py, scripts/tests/integration_stack_test.sh
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @7bfd0bc16 2026-11-27T11:35:57+01:00
Review: approve (.ah-out/review/kern-gateway-2/T2.verdict.json)
Änderung: Zone `hooks`; auf :8444 `location = /api/hooks/trigger` und `location ~ ^/api/hooks/trigger/[^/]+$`, nur POST,
`limit_req zone=hooks`, `client_max_body_size 1m`, Identitäts-Header geleert, `proxy_pass http://app`. Tests: aus nginx.conf
(Zone, Locations, geleerte Header); im Container gehen beide Pfade auf :8444 an den Server, `/api/hooks` und andere
`/api`-Pfade bleiben 404; Stack-Test unter `MTLS_ENFORCE=true`: ein Trigger mit falschem Token über :8444 ohne Zertifikat
bekommt die Antwort des Servers (401/404), nicht die des Gateways.
Beweis: Code-Lesung main@6895f8eaf nginx.conf:166-210, docker-entrypoint.sh:38-41; der Container-Test ist vor dem Fix rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_gateway_container.py
Doku: → T5
Abhängt von: T1

### T3 — Server: trigger_port in den Token-Antworten (R-1687)  [x]
Komponente: server · Dateien: apps/server/app/modules/hooks/router.py, apps/server/app/modules/hooks/schemas.py, apps/server/tests/test_hooks.py, apps/server/tests/test_openapi_snapshot.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @569db7975 2026-11-27T11:40:18+01:00
Review: approve (.ah-out/review/kern-gateway-2/T3.verdict.json)
Änderung: `HookCreatedResponse` (mit Token) und `HookTokenOut` tragen `trigger_port = ENROLL_PORT`. Test: Anlegen und
Rotieren eines Webhooks nennen den Port; ein geänderter `ENROLL_PORT` erscheint.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hooks.py tests/test_openapi_snapshot.py
Doku: → T5

### T4 — Web: Dialog zeigt die URL auf dem Enrollment-Port (R-1687)  [x]
Komponente: web · Dateien: apps/web/src/modals/WebhookTokenModal.svelte, apps/web/src/modals/WebhookTokenModal.test.ts, apps/web/src/pages/Hooks.svelte, apps/web/src/lib/api/types.ts, apps/web/src/modals/HookModal.svelte, apps/web/src/modals/HookModal.test.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @a3a75fc32 2026-11-27T11:44:27+01:00
Review: approve (.ah-out/review/kern-gateway-2/T4.verdict.json)
Änderung: Das curl-Beispiel nennt `https://<Host der Seite>:<trigger_port>/api/hooks/trigger`. Test: der Dialog zeigt
Host und Port; ohne Port fällt er auf die Herkunft der Seite zurück. Neue Testdatei mit SPDX-Header.
Verify: bash scripts/dev/verify.sh web --strict -- src/modals/WebhookTokenModal.test.ts src/modals/HookModal.test.ts
Doku: → T5
Abhängt von: T3

### T5 — Doku DE+EN und CHANGELOG (R-1687)  [x]
Komponente: scripts · Dateien: docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/admin/installation.html, docs/en/admin/installation.html, docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/kern-gateway-2.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @6db2a1d67 2026-11-27T11:47:20+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: API-Referenz: Trigger auf :8444 ohne Zertifikat, `trigger_port`. Installation: Port 8444 auch für Webhooks.
Betrieb: Ratelimit und Body-Grenze des Triggers auf der zertifikatslosen Ebene. Fragment umlautfrei.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/admin/installation.html, docs/en/admin/installation.html, docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/kern-gateway-2.md
Task-Review: am Ende

### T6 — Doku: Trigger-Absatz DE und Spec nachziehen (Abschlussprüfung, R-1687)  [x]
Komponente: scripts · Dateien: docs/developer/api-reference.html, docs/features/kern-gateway-2.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ce989ec52 2026-11-27T11:58:53+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Den verstümmelten deutschen Trigger-Absatz der API-Referenz reparieren (doppelte Phrase, Edit-Rest). Die Spec
an das verworfene T1 und die beantwortete Port-Frage anpassen.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/api-reference.html, docs/features/kern-gateway-2.md
Task-Review: am Ende

### T7 — Server: Form-Test der rotate-Antwort nennt trigger_port (PR-CI, R-1687)  [ ]
Komponente: server · Dateien: apps/server/tests/test_response_shapes.py
Änderung: `TestHookShape::test_rotate_answers_with_the_new_token` erwartet die Schlüssel `token` und `trigger_port`
(gewollte Vertragsänderung aus T3, Kevin 2026-11-27) und prüft `trigger_port` als Zahl.
Beweis: PR #695 CI Server shard 2/4: `assert ['token', 'trigger_port'] == ['token']`
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py tests/test_hooks.py
Doku: keine (Test)
