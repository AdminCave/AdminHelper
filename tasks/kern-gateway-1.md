# Gateway: interne Dienst-Routen nur im Compose-Netz — Task-Ledger
Status: erledigt · Branch: feature/kern-gateway-1 · Review: am Ende
Spec: docs/features/kern-gateway-1.md (Roadmap R-1604)
Heavy: linux-full — Gateway-Konfiguration (Sammellauf, Stack-Job der PR-CI)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1604: Gateway sperrt /api/internal auf :443  [x]
Komponente: server · Dateien: apps/gateway/nginx.conf, apps/server/tests/test_gateway_container.py, docs/developer/server.html, docs/en/developer/server.html, changelog.d/kern-gateway-1.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @c58d2ff16 2026-11-19T19:41:48+01:00
Review: am Ende (Branch-Review)
Änderung: Im Server-Block `listen 443` `location ^~ /api/internal { return 404; }`. Test: die Location steht nur auf :443 und antwortet 404 ohne `proxy_pass`; im Container antworten `/api/internal`, `/api/internal/servers` und kodierte bzw. verdoppelte Schreibweisen 404, während ein anderer API-Pfad an den (fehlenden) Server geht (502). `security` prüft mit.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_gateway_container.py
Doku: docs/developer/server.html, docs/en/developer/server.html, changelog.d/kern-gateway-1.md

### T2 — R-1604: Desktop-E2E speist Events im Compose-Netz ein  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/lib/live.js, scripts/tests/desktop_e2e_sse_push.sh, docs/features/kern-gateway-1.md
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped @7559400ad 2026-11-19T20:01:49+01:00
Review: am Ende (Branch-Review)
Änderung: Fund der security-Abschlussprüfung: `injectEvent` (notification-push.live.js) postete über den Gateway an `/api/internal/events` und bekäme nach T1 404. Jetzt `docker compose exec -T server python` gegen den eigenen uvicorn; der Schlüssel bleibt in der Container-Umgebung, das Event kommt über stdin; die Orchestrierung schreibt einen Compose-Wrapper statt den Schlüssel zu exportieren. Spec-Abschnitt Risiken korrigiert.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test-Harness der GUI-E2E; Spec nachgezogen)
