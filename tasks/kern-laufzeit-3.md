# Laufzeit: Redis-Netz und -Module, Proxy-Header des Servers — Task-Ledger
Status: bereit · Branch: feature/kern-laufzeit-3 · Review: pro Task
Spec: docs/features/kern-laufzeit-3.md (Roadmap R-1139, R-1125)
Heavy: linux-full — `docker-compose*.yml` und `scripts/tests/integration_stack_test.sh` im Diff: der Sammellauf über `main` fährt den Stack; vor dem Merge der Stack-Job per `gh workflow run ci.yml --ref feature/kern-laufzeit-3`. Kein `scenario`, kein `windows`.
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1139: Redis im eigenen Netz, ohne ladbare Module  [x]
Komponente: server · Dateien: docker-compose.yml, docker-compose.test.yml, scripts/tests/integration_stack_test.sh, apps/server/tests/test_compose_hardening.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @9a276a6c5 2026-11-10T06:25:06+01:00
Review: approve (.ah-out/review/kern-laufzeit-3/T1.verdict.json)
Änderung: Netz `redis` (intern) nur für `redis`, `server`, `scheduler`; `redis` startet `redis-server` direkt als
`redis`; Test-Compose nimmt `internal` für den Loopback-Port zurück; Stack-Test: Platzhalter `victoria`, neue
Negativ-Probe aus dem Default-Netz und `MODULE LIST`; Compose-Tests für Netz, Mitglieder und Entrypoint.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_compose_hardening.py
Doku: → T3

### T2 — R-1125: uvicorn wertet keine Proxy-Header aus  [x]
Komponente: server · Dateien: apps/server/docker-entrypoint.sh, apps/server/app/core/identity.py, apps/server/tests/test_server_entrypoint.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @e7bee3e6f 2026-11-10T06:27:56+01:00
Review: approve (.ah-out/review/kern-laufzeit-3/T2.verdict.json)
Änderung: `--no-proxy-headers` im uvicorn-Aufruf; Docstring von `_peer_is_gateway` nachgezogen; neuer Test (SPDX)
prüft die Option im `exec uvicorn`-Aufruf und dass kein `--forwarded-allow-ips` daneben steht.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_server_entrypoint.py
Doku: → T3

### T3 — Doku und CHANGELOG  [x]
Komponente: server · Dateien: docs/developer/index.html, docs/en/developer/index.html, changelog.d/kern-laufzeit-3.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @3d3f13ef3 2026-11-10T06:28:56+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: DE+EN: Redis im eigenen Netz mit Server und Scheduler; CHANGELOG-Eintrag neutral.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_compose_hardening.py
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
