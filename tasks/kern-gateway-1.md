# Gateway: interne Dienst-Routen nur im Compose-Netz — Task-Ledger
Status: geplant · Branch: feature/kern-gateway-1 · Review: am Ende
Spec: docs/features/kern-gateway-1.md (Roadmap R-1604)
Heavy: linux-full — Gateway-Konfiguration (Sammellauf, Stack-Job der PR-CI)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1604: Gateway sperrt /api/internal auf :443  [ ]
Komponente: server · Dateien: apps/gateway/nginx.conf, apps/server/tests/test_gateway_container.py, docs/developer/server.html, docs/en/developer/server.html, changelog.d/kern-gateway-1.md
Änderung: Im Server-Block `listen 443` `location ^~ /api/internal { return 404; }`. Test: die Location steht nur auf :443 und antwortet 404 ohne `proxy_pass`; im Container antworten `/api/internal`, `/api/internal/servers` und kodierte bzw. verdoppelte Schreibweisen 404, während ein anderer API-Pfad an den (fehlenden) Server geht (502). `security` prüft mit.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_gateway_container.py
Doku: docs/developer/server.html, docs/en/developer/server.html, changelog.d/kern-gateway-1.md
